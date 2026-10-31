# 필요한 범위만 로컬에서 읽기

Python 3.11 이상을 사용합니다. EML은 추가 패키지가 없고, Classic Outlook은 Windows와 승인된 `pywin32`가 필요합니다. 실행 중인 Outlook에만 연결하며 실행/로그인/설정 변경/프로필 등록을 하지 않습니다. 사용자가 자료의 처리를 요청한 범위에만 사용합니다.

`<스킬폴더>`는 이 참고자료의 상위 `SKILL.md`가 있는 실제 절대경로로 바꿉니다. 명령은 현재 업무 폴더와 무관하게 해당 도우미를 실행합니다.

| 목적 | 명령 |
|---|---|
| 실행 중 Outlook의 읽기 대상 목록 | `python -X utf8 "<스킬폴더>/scripts/mail_read.py" folders` |
| 지정 폴더의 제목·발신자 검색 | `python -X utf8 "<스킬폴더>/scripts/mail_read.py" search --store-id "실제 storeId" --folder-id "실제 folderId" --query "검색어" --limit 20 --scan-limit 500` |
| 필요한 ID만 읽기 | `python -X utf8 "<스킬폴더>/scripts/mail_read.py" read --store-id "실제 storeId" --ids "메시지 ID 배열.json의 절대경로" --body-chars 4000 --total-chars 12000` |
| EML 제목/첨부 이름만 읽기 | `python -X utf8 "<스킬폴더>/scripts/mail_read.py" eml --file "선택한 파일.eml의 절대경로"` |
| EML 본문도 읽기 | 위 EML 명령에 `--body --body-chars 4000` 추가 |

EML은 이 `mail_read.py eml`로 MIME 헤더, 문자셋과 본문을 해석합니다. 고정 줄 번호나 임의 Base64 해독 코드로 본문을 추출하지 않습니다. 반환된 잘림 정보만 확인하며 같은 파일을 원문으로 다시 읽지 않습니다.

Outlook의 `folders`는 각 store의 기본 받은편지함을 최대 20개 보여줍니다. 주소/프로필 표시가 권한 검증을 대신하지 않으며 사용자가 선택한 계정을 유지합니다. 하위 폴더까지 자동 탐색하지 않습니다. ID는 실제 결과 그대로 전달합니다.

검색은 지정 폴더에서 최신 순으로 **최대 scan-limit개**의 제목/발신자만 확인합니다. 기본 500, 최대 2000개입니다. `--after`, `--before`는 타임존이 포함된 ISO 시각이며 시작 포함·끝 제외입니다. 검색어는 제목/발신자의 대소문자 구분 없는 문자열입니다. 본문 검색이나 전체 서버 검색이 아닙니다. `partial`, `scanned`, `folderCount`를 보고 범위를 설명합니다.

본문 읽기는 최대 20개 ID를 지원하지만 기본은 5건 이내를 선택합니다. 개별 4000·총 12000자는 **모델에 반환할 텍스트**의 제한입니다. CLI의 전체 JSON도 32,000자 이내로 제한하며, 초과하면 본문을 더 줄이거나 항목을 생략하고 `outputTruncated`로 알립니다. ID는 자르지 않습니다. Outlook COM의 Body 속성은 한 메시지 전체를 로컬로 가져오며 스트리밍 제한은 아닙니다. EML은 파일 크기 10 MiB 이하를 로컬로 해석하고 첨부 내용을 반환하거나 별도로 디코딩하지 않습니다. HTML 전용 메일은 텍스트로 단순 변환하므로 정확한 시각적 배치까지 재현하지 않습니다.

결과의 `truncated`, `bodyReadCount`, `omitted`를 확인합니다. 접근 거절/보호된 메일은 다른 방식으로 우회하지 않습니다. 새 Outlook만 있거나 COM 연결을 못하면 실제 메일 연결 준비가 필요하다고 안내합니다.
