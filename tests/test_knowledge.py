from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.frontmatter import dump_frontmatter, load_markdown, parse_frontmatter_text  # noqa: E402
from company_agent.knowledge import (  # noqa: E402
    build_index,
    export_knowledge,
    reconcile_overlays,
    search_catalog,
    upsert_personal,
    validate_pack,
)


def write_doc(path: Path, metadata: dict[str, object], body: str = "# 내용\n\n테스트 문서") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_frontmatter(metadata, body), encoding="utf-8")


class FrontmatterTests(unittest.TestCase):
    def test_supports_yaml_style_lists_and_json_style_values(self) -> None:
        metadata, body = parse_frontmatter_text(
            "---\nid: term.test\naliases:\n  - 하나\n  - 둘\nactive: true\n---\n\n# 본문\n"
        )
        self.assertEqual(["하나", "둘"], metadata["aliases"])
        self.assertTrue(metadata["active"])
        self.assertIn("# 본문", body)

    def test_dump_round_trip_preserves_unicode(self) -> None:
        rendered = dump_frontmatter({"id": "term.test", "title": "재공", "aliases": ["WIP"]}, "# 정의\n\n내용")
        metadata, body = parse_frontmatter_text(rendered)
        self.assertEqual("재공", metadata["title"])
        self.assertIn("내용", body)


class KnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "base"
        self.state = self.root / "state"
        self.base.mkdir()
        (self.base / "pack.json").write_text(json.dumps({"version": "2026.09.03"}), encoding="utf-8")
        write_doc(
            self.base / "glossary" / "wip.md",
            {
                "kind": "term",
                "id": "term.manufacturing.wip",
                "title": "WIP",
                "aliases": ["재공"],
                "domain": "manufacturing",
                "owner": "제조팀",
                "status": "active",
            },
        )
        write_doc(
            self.base / "tables" / "wip-history.md",
            {
                "kind": "table",
                "id": "table.mes.wip_history",
                "title": "WIP 이력",
                "system": "MES",
                "schema": "dbo",
                "table": "WIP_HISTORY",
                "grain": "LOT x 이벤트",
                "owner": "생산시스템팀",
                "status": "active",
                "related": ["term.manufacturing.wip"],
            },
            "# 예시\n\n```sql\nSELECT LOT_ID FROM dbo.WIP_HISTORY;\n```",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_validate_and_build_effective_index(self) -> None:
        documents, issues = validate_pack(self.base)
        self.assertEqual(2, len(documents))
        self.assertFalse([item for item in issues if item.level == "error"])
        output = self.state / "knowledge" / "generated-index"
        catalog, issues = build_index(self.base, self.state / "knowledge", output)
        self.assertFalse([item for item in issues if item.level == "error"])
        self.assertEqual(2, len(catalog["entries"]))
        results = search_catalog(output, "재공")
        self.assertEqual("term.manufacturing.wip", results[0]["id"])

    def test_effective_catalog_excludes_non_active_documents_and_searches_document_content(self) -> None:
        for status in ("draft", "deprecated", "example"):
            write_doc(
                self.base / "authoring" / f"{status}.md",
                {
                    "kind": "term",
                    "id": f"term.{status}",
                    "title": f"{status} only",
                    "owner": "작성자",
                    "status": status,
                    "related": ["missing.draft.reference"],
                },
            )
        output = self.state / "knowledge" / "generated-index"
        catalog, issues = build_index(self.base, self.state / "knowledge", output)
        self.assertFalse([item for item in issues if item.level == "error"])
        self.assertEqual(
            {"term.manufacturing.wip", "table.mes.wip_history"},
            {entry["id"] for entry in catalog["entries"]},
        )
        self.assertEqual("table.mes.wip_history", search_catalog(output, "WIP_HISTORY")[0]["id"])
        self.assertEqual("table.mes.wip_history", search_catalog(output, "LOT_ID")[0]["id"])
        self.assertEqual([], search_catalog(output, "draft only"))

        # Explicit validation still reports authoring problems even though
        # inactive documents cannot break the runtime catalog.
        _, validation_issues = validate_pack(self.base)
        self.assertIn("broken_reference", {item.code for item in validation_issues})

    def test_explicit_personal_overlay_is_written_and_immediately_indexed(self) -> None:
        path = upsert_personal(
            {
                "title": "개인 WIP 조회 기준",
                "mode": "extend",
                "extends": "table.mes.wip_history",
                "body": "# 개인 적용 기준\n\nTEST 이벤트도 제외한다.",
                "reason": "사용자가 명시함",
            },
            self.state,
            self.base,
        )
        document = load_markdown(path)
        self.assertEqual("table.mes.wip_history", document.metadata["extends"])
        self.assertEqual("2026.09.03", document.metadata["base_pack_version"])
        catalog = json.loads((self.state / "knowledge" / "generated-index" / "catalog.json").read_text(encoding="utf-8"))
        table = next(item for item in catalog["entries"] if item["id"] == "table.mes.wip_history")
        self.assertEqual(1, len(table["overlays"]))
        ledger = (self.state / "ledger" / "knowledge.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("TEST 이벤트도 제외", ledger)

    def test_korean_automatic_ids_do_not_overwrite_other_terms_or_overlays(self) -> None:
        paths = [upsert_personal({"title": title, "kind": "term", "mode": "personal-new", "body": "# 정의\n\n업무 지식"},
                                 self.state, self.base)
                 for title in ("재공 기준", "출하 기준", "report+format", "report format")]
        self.assertEqual(4, len(set(paths)))
        first_overlay = upsert_personal({"title": "조회 규칙", "mode": "extend", "extends": "table.mes.wip_history", "body": "첫 규칙"},
                                        self.state, self.base)
        second_overlay = upsert_personal({"title": "정렬 규칙", "mode": "extend", "extends": "table.mes.wip_history", "body": "둘째 규칙"},
                                         self.state, self.base)
        self.assertNotEqual(first_overlay, second_overlay)
        self.assertEqual("조회 규칙", load_markdown(first_overlay).metadata["title"])

    def test_noop_knowledge_upsert_preserves_original_revision_and_history(self) -> None:
        spec = {"title": "재공 기준", "mode": "extend", "extends": "table.mes.wip_history", "body": "추가 필터"}
        path = upsert_personal(spec, self.state, self.base)
        original = (path.read_bytes(), path.stat().st_mtime_ns)
        ledger = self.state / "ledger" / "knowledge.jsonl"
        original_ledger = ledger.read_bytes()
        self.assertEqual(path, upsert_personal({**spec, "reason": "내용 변경 없는 반복 요청"}, self.state, self.base))
        self.assertEqual(original, (path.read_bytes(), path.stat().st_mtime_ns))
        self.assertEqual(original_ledger, ledger.read_bytes())
        self.assertEqual([], list((self.state / "knowledge" / "versions").rglob("*.md")))
        self.assertEqual(1, load_markdown(path).metadata["personal_revision"])
        upsert_personal({**spec, "id": load_markdown(path).metadata["id"], "body": "수정 필터"}, self.state, self.base)
        self.assertEqual(2, load_markdown(path).metadata["personal_revision"])
        self.assertEqual(1, len(list((self.state / "knowledge" / "versions").rglob("*.md"))))

    def test_automatic_knowledge_update_preserves_matching_legacy_id(self) -> None:
        legacy = upsert_personal({"id": "personal.term.knowledge", "title": "재공 기준", "kind": "term", "body": "기존 정의"},
                                 self.state, self.base)
        other = upsert_personal({"title": "출하 기준", "kind": "term", "body": "다른 정의"}, self.state, self.base)
        self.assertNotEqual(legacy, other)
        updated = upsert_personal({"title": "재공 기준", "kind": "term", "body": "변경 정의"}, self.state, self.base)
        self.assertEqual(legacy, updated)
        self.assertEqual("personal.term.knowledge", load_markdown(updated).metadata["id"])
        self.assertEqual("출하 기준", load_markdown(other).metadata["title"])

    def test_active_overlay_alias_tags_and_body_are_searchable(self) -> None:
        upsert_personal(
            {
                "id": "personal.extend.searchable-wip",
                "title": "개인 WIP 검색 기준",
                "mode": "extend",
                "extends": "table.mes.wip_history",
                "aliases": ["내재공"],
                "tags": ["개인품질"],
                "body": "# 개인 기준\n\n플럭스이벤트는 분석에서 제외한다.",
            },
            self.state,
            self.base,
        )
        output = self.state / "knowledge" / "generated-index"
        for query in ("내재공", "개인품질", "플럭스이벤트"):
            self.assertEqual("table.mes.wip_history", search_catalog(output, query)[0]["id"])
        catalog = json.loads((output / "catalog.json").read_text(encoding="utf-8"))
        table = next(entry for entry in catalog["entries"] if entry["id"] == "table.mes.wip_history")
        self.assertIn("내재공", table["aliases"])
        self.assertIn("개인품질", table["tags"])

    def test_corporate_update_rebases_extend_but_conflicts_with_fork(self) -> None:
        extend_path = upsert_personal(
            {
                "id": "personal.extend.wip",
                "title": "WIP 추가 기준",
                "mode": "extend",
                "extends": "table.mes.wip_history",
                "body": "# 개인 기준\n\n추가 필터",
            },
            self.state,
            self.base,
        )
        fork_path = upsert_personal(
            {
                "id": "personal.fork.wip",
                "title": "WIP 개인 포크",
                "mode": "fork",
                "extends": "table.mes.wip_history",
                "body": "# 내 기준\n\n다른 계산 기준",
            },
            self.state,
            self.base,
        )
        table_path = self.base / "tables" / "wip-history.md"
        table = load_markdown(table_path)
        changed_metadata = dict(table.metadata)
        changed_metadata["updated_at"] = "2026-09-04"
        table_path.write_text(dump_frontmatter(changed_metadata, table.body), encoding="utf-8")
        report = reconcile_overlays(self.state, self.base, apply_safe=True)
        self.assertIn("personal.extend.wip", report["rebased"])
        self.assertEqual("personal.fork.wip", report["conflicts"][0]["overlayId"])
        self.assertNotEqual(
            load_markdown(extend_path).metadata["base_content_hash"],
            load_markdown(fork_path).metadata["base_content_hash"],
        )

    def test_extend_rebase_rejects_base_body_meaning_change(self) -> None:
        upsert_personal(
            {
                "id": "personal.extend.body-contract",
                "title": "WIP 의미 의존 기준",
                "mode": "extend",
                "extends": "table.mes.wip_history",
                "body": "# 개인 기준\n\n추가 필터",
            },
            self.state,
            self.base,
        )
        table_path = self.base / "tables" / "wip-history.md"
        table_path.write_text(
            table_path.read_text(encoding="utf-8") + "\n# 변경\n\n기존 컬럼 의미를 변경한다.\n",
            encoding="utf-8",
        )

        report = reconcile_overlays(self.state, self.base, apply_safe=True)
        self.assertEqual([], report["rebased"])
        self.assertEqual("personal.extend.body-contract", report["conflicts"][0]["overlayId"])

    def test_extend_rebase_requires_unchanged_base_contract(self) -> None:
        upsert_personal(
            {
                "id": "personal.extend.contract",
                "title": "WIP 구조 의존 기준",
                "mode": "extend",
                "extends": "table.mes.wip_history",
                "body": "# 개인 기준\n\n추가 필터",
            },
            self.state,
            self.base,
        )
        table_path = self.base / "tables" / "wip-history.md"
        table = load_markdown(table_path)
        changed_metadata = dict(table.metadata)
        changed_metadata["grain"] = "LOT x 이벤트 x 설비"
        table_path.write_text(dump_frontmatter(changed_metadata, table.body), encoding="utf-8")

        report = reconcile_overlays(self.state, self.base, apply_safe=True)
        self.assertEqual([], report["rebased"])
        self.assertEqual("personal.extend.contract", report["conflicts"][0]["overlayId"])
        self.assertIn("자동 rebase", report["conflicts"][0]["reason"])

    def test_detached_overlay_is_reported_but_does_not_block_catalog_rebuild(self) -> None:
        upsert_personal(
            {
                "id": "personal.extend.detached",
                "title": "분리될 WIP 기준",
                "mode": "extend",
                "extends": "table.mes.wip_history",
                "body": "# 개인 기준\n\n회사 원본 제거 후 보존",
            },
            self.state,
            self.base,
        )
        (self.base / "tables" / "wip-history.md").unlink()
        output = self.state / "knowledge" / "generated-index"
        catalog, issues = build_index(self.base, self.state / "knowledge", output)

        self.assertTrue((output / "catalog.json").exists())
        self.assertFalse([item for item in issues if item.level == "error"])
        self.assertIn("detached_overlay", {item.code for item in issues})
        self.assertEqual(["personal.extend.detached"], catalog["detachedOverlays"])
        self.assertNotIn("personal.extend.detached", json.dumps(catalog["entries"], ensure_ascii=False))
        report = reconcile_overlays(self.state, self.base)
        self.assertEqual(["personal.extend.detached"], report["detached"])

    def test_other_active_broken_references_still_block_catalog_build(self) -> None:
        write_doc(
            self.base / "bad-reference.md",
            {
                "kind": "term",
                "id": "term.bad-reference",
                "title": "잘못된 활성 참조",
                "owner": "팀",
                "status": "active",
                "related": ["missing.active.target"],
            },
        )
        output = self.state / "knowledge" / "generated-index"
        _, issues = build_index(self.base, self.state / "knowledge", output)
        self.assertIn("broken_reference", {item.code for item in issues if item.level == "error"})
        self.assertFalse((output / "catalog.json").exists())

    def test_rejects_non_select_sql_and_secret_like_values(self) -> None:
        write_doc(
            self.base / "bad.md",
            {
                "kind": "term",
                "id": "term.bad",
                "title": "Bad",
                "owner": "팀",
                "status": "draft",
            },
            "# Bad\n\npassword=real-secret\n\n```sql\nDELETE FROM T;\n```",
        )
        _, issues = validate_pack(self.base)
        codes = {item.code for item in issues}
        self.assertIn("possible_secret", codes)
        self.assertIn("non_select_sql", codes)

    def test_export_redacts_email_and_local_user_path(self) -> None:
        path = upsert_personal(
            {
                "id": "personal.term.export",
                "kind": "term",
                "title": "공유 지식",
                "mode": "personal-new",
                "body": "# 참고\n\n문의: me@example.corp\n경로: C:\\Users\\alice\\work\\report.md",
            },
            self.state,
            self.base,
        )
        output = self.root / "share.zip"
        export_knowledge(self.state, ["personal.term.export"], output)
        import zipfile

        with zipfile.ZipFile(output) as archive:
            exported = archive.read(path.name).decode("utf-8")
            self.assertNotIn("me@example.corp", exported)
            self.assertNotIn("C:\\Users\\alice", exported)
            self.assertIn("[REDACTED_EMAIL]", exported)
            self.assertIn("change-summary.md", archive.namelist())

    def test_export_recursively_redacts_sensitive_metadata_and_session_ids(self) -> None:
        path = upsert_personal(
            {
                "id": "personal.term.nested-export",
                "kind": "term",
                "title": "중첩 메타데이터 공유",
                "mode": "personal-new",
                "metadata": {
                    "contact": "owner@example.corp",
                    "provenance": {
                        "local_path": "C:\\Users\\alice\\private\\source.md",
                        "session_id": "session-secret-123",
                    },
                },
                "body": "# 참고\n\nconversation_id=conversation-secret-456에서 정리함.",
            },
            self.state,
            self.base,
        )
        output = self.root / "nested-share.zip"
        export_knowledge(self.state, ["personal.term.nested-export"], output)
        import zipfile

        with zipfile.ZipFile(output) as archive:
            exported = archive.read(path.name).decode("utf-8")
        self.assertNotIn("owner@example.corp", exported)
        self.assertNotIn("C:\\Users\\alice", exported)
        self.assertNotIn("session-secret-123", exported)
        self.assertNotIn("conversation-secret-456", exported)
        self.assertIn("[REDACTED_EMAIL]", exported)
        self.assertIn("[REDACTED_LOCAL_PATH]", exported)
        self.assertIn("[REDACTED_SESSION_ID]", exported)


if __name__ == "__main__":
    unittest.main()
