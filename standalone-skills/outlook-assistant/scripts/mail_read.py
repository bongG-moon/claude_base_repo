"""메일 메타데이터/선택 본문을 한도 안에서 읽습니다. 발송·이동·설정 변경 없음."""
from __future__ import annotations

import argparse
from datetime import datetime
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
import json
from pathlib import Path

MAX_RESULT_CHARS = 32000


def bound(value: int, minimum: int, maximum: int, label: str) -> int:
    if not minimum <= value <= maximum:
        raise ValueError(f"{label}: {minimum}~{maximum} 범위를 지정하세요.")
    return value


def date(value):
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("날짜에는 타임존(+09:00 등)을 포함하세요.")
    return parsed


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"): self.hidden += 1
        if tag in ("p", "div", "br", "li", "tr"): self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script", "style"): self.hidden = max(0, self.hidden - 1)
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def eml(path: Path, include_body=False, body_chars=4000) -> dict:
    bound(body_chars, 1, 12000, "본문 글자수")
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("EML 파일은 10 MiB 이내로 지정하세요.")
    msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    result = {"subject": str(msg.get("subject", ""))[:500], "sender": str(msg.get("from", ""))[:500],
              "date": str(msg.get("date", ""))[:100], "attachments": [], "bodyReadCount": 0}
    for part in msg.iter_attachments():
        result["attachments"].append(str(part.get_filename() or "이름 없는 첨부")[:250])
        if len(result["attachments"]) >= 100: break
    if include_body:
        part = msg.get_body(preferencelist=("plain", "html"))
        body = part.get_content() if part else ""
        if part and part.get_content_type() == "text/html":
            parser = PlainHTML(); parser.feed(body); body = "".join(parser.parts)
        result.update(body=body[:body_chars], truncated=len(body) > body_chars, bodyReadCount=1 if part else 0)
    return result


def connect():
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("Classic Outlook 읽기에는 Windows의 승인된 pywin32가 필요합니다.") from exc
    try:
        return win32com.client.GetActiveObject("Outlook.Application").GetNamespace("MAPI")
    except Exception as exc:
        raise RuntimeError("실행 중인 Classic Outlook에 연결하지 못했습니다. Outlook을 직접 열고 계정을 확인하세요.") from exc


def folders(namespace) -> dict:
    rows, errors = [], 0
    count = namespace.Stores.Count
    for index in range(1, min(count, 20) + 1):
        try:
            store = namespace.Stores.Item(index)
            inbox = store.GetDefaultFolder(6)
            rows.append({"storeId": store.StoreID, "folderId": inbox.EntryID,
                         "accountLabel": str(store.DisplayName)[:250], "folder": str(inbox.Name)[:100]})
        except Exception:
            errors += 1
    return {"folders": rows, "omittedStores": max(0, count - 20), "unavailableStores": errors}


def metadata(item):
    return {"id": item.EntryID, "subject": str(item.Subject or "")[:500],
            "sender": str(item.SenderName or "")[:250], "received": item.ReceivedTime.isoformat(),
            "attachmentCount": item.Attachments.Count}


def search(namespace, store_id, folder_id, query="", limit=20, scan_limit=500, after=None, before=None):
    bound(limit, 1, 50, "결과 개수"); bound(scan_limit, 1, 2000, "확인 개수")
    after, before = date(after), date(before)
    if after and before and after >= before: raise ValueError("시작 날짜가 끝보다 앞이어야 합니다.")
    folder = namespace.GetFolderFromID(folder_id, store_id)
    items = folder.Items
    items.Sort("[ReceivedTime]", True)
    total, scanned, failures, rows = items.Count, 0, 0, []
    for index in range(1, min(total, scan_limit) + 1):
        scanned += 1
        try:
            item = items.Item(index)
            if item.Class != 43: continue
            received = item.ReceivedTime
            if after and received < after or before and received >= before: continue
            row = metadata(item)
            if query.casefold() not in (row["subject"] + " " + row["sender"]).casefold(): continue
            rows.append(row)
            if len(rows) >= limit: break
        except Exception:
            failures += 1
    return {"messages": rows, "scanned": scanned, "folderCount": total,
            "partial": scanned < total or failures > 0, "unavailable": failures, "bodyReadCount": 0}


def read(namespace, store_id, ids, body_chars=4000, total_chars=12000):
    bound(body_chars, 1, 12000, "개별 본문 글자수"); bound(total_chars, 1, 24000, "전체 본문 글자수")
    if not isinstance(ids, list) or not 1 <= len(ids) <= 20 or any(not isinstance(i, str) or not i or len(i) > 4096 for i in ids):
        raise ValueError("메시지 ID는 1~20개 문자열 배열입니다.")
    rows, remaining, read_count, failures = [], total_chars, 0, 0
    unique_ids = list(dict.fromkeys(ids))
    for message_id in unique_ids:
        if remaining <= 0: break
        try:
            item = namespace.GetItemFromID(message_id, store_id)
            if item.Class != 43: raise ValueError("메일 아님")
            row = metadata(item)
            body = str(item.Body or "")
            read_count += 1
            size = min(body_chars, remaining)
            row.update(body=body[:size], truncated=len(body) > size)
            remaining -= len(row["body"])
            rows.append(row)
        except Exception:
            failures += 1
    return {"messages": rows, "bodyReadCount": read_count, "bodyCharacters": total_chars - remaining,
            "unavailable": failures, "omitted": len(unique_ids) - len(rows)}


def bounded_result(result: dict) -> dict:
    """본문 외 제목·식별자까지 합친 실제 JSON 크기를 제한합니다. ID를 자르지 않습니다."""
    def fits():
        return len(json.dumps(result, ensure_ascii=False)) <= MAX_RESULT_CHARS
    if fits():
        return result
    result["outputTruncated"] = True
    result["partial"] = True
    # 긴 본문부터 줄여 메일 출처는 가능한 한 남깁니다.
    rows = result.get("messages", [result])
    for row in reversed(rows):
        while row.get("body") and not fits():
            row["body"] = row["body"][:len(row["body"]) // 2]
            row["truncated"] = True
            if "messages" in result:
                result["bodyCharacters"] = sum(len(item.get("body", "")) for item in result["messages"])
    # 메타데이터가 큰 경우 항목 단위로 생략합니다. 읽었다는 수치는 그대로 보존합니다.
    for key, count_key in (("messages", "omitted"), ("folders", "omittedStores"), ("attachments", "omittedAttachments")):
        while result.get(key) and not fits():
            result[key].pop()
            result[count_key] = result.get(count_key, 0) + 1
            if key == "messages":
                result["bodyCharacters"] = sum(len(item.get("body", "")) for item in result[key])
    if not fits():
        return {"status": "unavailable", "message": "응답 메타데이터가 너무 큽니다. 범위를 줄여 주세요.", "outputTruncated": True}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("folders")
    p = sub.add_parser("search")
    p.add_argument("--store-id", required=True); p.add_argument("--folder-id", required=True); p.add_argument("--query", default="")
    p.add_argument("--limit", type=int, default=20); p.add_argument("--scan-limit", type=int, default=500)
    p.add_argument("--after"); p.add_argument("--before")
    p = sub.add_parser("read")
    p.add_argument("--store-id", required=True); p.add_argument("--ids", type=Path, required=True)
    p.add_argument("--body-chars", type=int, default=4000); p.add_argument("--total-chars", type=int, default=12000)
    p = sub.add_parser("eml")
    p.add_argument("--file", type=Path, required=True); p.add_argument("--body", action="store_true"); p.add_argument("--body-chars", type=int, default=4000)
    args = parser.parse_args()
    try:
        if args.command == "eml": result = eml(args.file, args.body, args.body_chars)
        elif args.command == "folders": result = folders(connect())
        elif args.command == "search": result = search(connect(), args.store_id, args.folder_id, args.query, args.limit, args.scan_limit, args.after, args.before)
        else:
            if args.ids.stat().st_size > 100_000: raise ValueError("메시지 ID 파일이 너무 큽니다.")
            result = read(connect(), args.store_id, json.loads(args.ids.read_text(encoding="utf-8-sig")), args.body_chars, args.total_chars)
        print(json.dumps(bounded_result(result), ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "unavailable", "message": str(exc)}, ensure_ascii=False)); return 1
    except Exception:
        # COM 오류 원문에 계정/경로/인증정보가 있을 수 있으므로 그대로 출력하지 않습니다.
        print(json.dumps({"status": "unavailable", "message": "선택한 메일 범위를 읽지 못했습니다. 계정·폴더·권한을 확인하세요."}, ensure_ascii=False)); return 1


if __name__ == "__main__":
    raise SystemExit(main())
