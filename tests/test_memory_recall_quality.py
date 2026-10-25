"""Offline recall regressions; no live profile, model or new runtime hook."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "company-agent-plugin/scripts"))
from company_agent import memory
from company_agent.resource_scope import selected_root


class MemoryRecallQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="recall-quality-")
        self.base = Path(self.tmp.name)
        self.state = self.base / "state"

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, identifier, title, body, **extra):
        return memory.upsert_memory({"id": identifier, "kind": "work_context",
                                     "title": title, "body": body, **extra}, self.state)

    def test_short_ascii_terms_do_not_recall_unrelated_substrings(self):
        cases = (
            ("AI", "email", "AI교육", "AI를 사용하는 과정"),
            ("API", "capital", "API 연결", "API로 자료를 가져온다"),
            ("DB", "feedback", "DB 조회", "DB에서 표를 읽는다"),
            ("SUM", "summary", "SUM 계산", "SUM으로 합산한다"),
        )
        for query, unrelated, title, body in cases:
            with self.subTest(query=query):
                folder = self.base / query
                memory.upsert_memory({"id": "a.unrelated", "kind": "work_context",
                                      "title": unrelated, "body": unrelated}, folder)
                memory.upsert_memory({"id": "z.relevant", "kind": "work_context",
                                      "title": title, "body": body}, folder)
                self.assertEqual(["z.relevant"], [item["id"] for item in memory.search_memory(folder, query)])

    def test_polite_request_words_do_not_inject_other_work(self):
        self.save("a.mail", "메일 요약", "정리해줘라고 요청한 메일은 날짜순으로 정리한다.")
        self.save("z.stock", "재고 집계", "재고는 확정 수량을 사용한다.")
        for query in ("재고 정리해줘", "재고를 정리해주세요", "재고 확인해줘"):
            with self.subTest(query=query):
                self.assertEqual(["z.stock"], [item["id"] for item in memory.search_memory(self.state, query)])

    def test_korean_particles_and_mixed_language_retain_domain_match(self):
        self.save("work.stock", "재고 산식", "AI와 Excel을 함께 사용하는 재고 계산이다.")
        for query in ("재고를", "재고에서", "AI를", "Excel로"):
            with self.subTest(query=query):
                self.assertEqual(["work.stock"], [item["id"] for item in memory.search_memory(self.state, query)])

    def test_corrected_revision_wins_without_old_snapshot_or_inactive_items(self):
        self.save("work.stock", "재고 기준", "입고 수량으로 계산한다.")
        self.save("work.stock", "재고 기준", "출고 수량으로 계산한다.")
        for status in ("draft", "inactive", "deprecated"):
            self.save("old." + status, "재고 기준", "이전 임시 기준", status=status)
        found = memory.search_memory(self.state, "재고 기준")
        self.assertEqual(1, len(found))
        self.assertEqual(2, found[0]["revision"])
        self.assertEqual("출고 수량으로 계산한다.", found[0]["body"])
        self.assertEqual(1, len(list((self.state / "memory/versions").rglob("*.md"))))

    def test_old_durable_preferences_remain_available(self):
        with patch("company_agent.memory._now", return_value="2000-01-01T00:00:00+00:00"):
            self.save("style", "설명 방식", "쉬운 한국어로 설명한다.", kind="preference")
        self.assertEqual(["style"], [item["id"] for item in memory.search_memory(self.state, "안녕하세요")])

    def test_current_project_only_and_personal_default_with_no_extra_scans(self):
        project_a, project_b = self.base / "A", self.base / "B"
        with patch.dict(os.environ, {"COMPANY_AGENT_SCOPE": "User"}):
            a = selected_root(self.state, project_a, "project")
            b = selected_root(self.state, project_b, "project")
            self.save("style", "설명 방식", "한국어로 설명한다.", kind="preference")
            for folder, identifier in ((a, "a.stock"), (b, "b.stock")):
                memory.upsert_memory({"id": identifier, "kind": "work_context",
                                      "title": "재고", "body": "확정 수량"}, folder)
            with patch("company_agent.memory._load_safe_memory", wraps=memory._load_safe_memory) as read:
                found = memory.search_scoped_memory(self.state, project_a, "재고")
            self.assertEqual(["a.stock", "style"], [item["id"] for item in found])
            self.assertEqual(2, read.call_count)
            self.assertNotIn(b, [call.args[0].parent.parent.parent for call in read.call_args_list])

    def test_recall_and_render_budgets_remain_bounded(self):
        for index in range(8):
            self.save(f"work.{index}", f"재고 기준 {index}", "재고 수량을 확인한다. " * 100)
        found = memory.search_memory(self.state, "재고", limit=100)
        self.assertEqual(memory.MAX_MEMORY_RESULTS, len(found))
        rendered = memory.render_memory_context(found)
        self.assertLessEqual(len(rendered), 4000)
        data = json.loads(rendered.split(memory.MEMORY_CONTEXT_BEGIN)[1].split(memory.MEMORY_CONTEXT_END)[0])
        self.assertLessEqual(len(data["items"]), 5)
        self.assertTrue(all(len(item["body"]) <= 700 for item in data["items"]))
        self.assertNotIn("score", rendered)

    def test_token_count_stays_bounded_after_filtering(self):
        query = " ".join(["정리해줘"] * 100 + [f"term{index}" for index in range(100)])
        self.assertEqual([f"term{index}" for index in range(32)], memory._query_tokens(query))


if __name__ == "__main__":
    unittest.main()
