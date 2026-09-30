"""Final prompt-budget evidence only; fixtures never use live personal state."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from company_agent.memory import render_memory_context
from company_agent.memory_delivery import memory_delivery_status, record_memory_delivery
from company_agent.native_runtime import bounded_prompt_context
from company_agent.state import begin_turn, load_session


class MemoryDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="memory-delivery-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session = "delivery-fixture"
        self.state = begin_turn(self.session, "SMALL", False, [], self.root)
        self.turn = self.state["turnId"]

    def memory(self, identifier="report-tone", scope="personal", body="결론부터 간결히 설명한다."):
        return {"id": identifier, "revision": 3, "kind": "preference", "status": "active",
                "title": "PRIVATE_TITLE_CANARY", "body": body, "storageScope": scope}

    def final(self, context):
        return "스킬 안내\n" + json.dumps({"company_agent_personal_memory_context": context}, ensure_ascii=False) + "\n{}"

    def record(self, context, **kwargs):
        return record_memory_delivery(self.root, self.session, self.turn, context, **kwargs)

    def test_records_actual_output_metadata_and_never_content_or_model_compliance(self):
        offered = render_memory_context([self.memory(body="PRIVATE_BODY_CANARY")])
        receipt = self.record(self.final(offered), offered_context=offered)
        self.assertEqual("output-produced", receipt["status"])
        self.assertEqual([{"id": "report-tone", "revision": 3, "storageScope": "personal"}], receipt["items"])
        self.assertEqual("not-observable", receipt["hostReceipt"])
        self.assertEqual("not-observable", receipt["modelApplied"])
        saved = (self.root / "sessions" / f"{self.session}.json").read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE_TITLE_CANARY", saved)
        self.assertNotIn("PRIVATE_BODY_CANARY", saved)
        for key in ("mutationCount", "verification", "learningProgressRevision", "stopRetryCount", "work"):
            self.assertEqual(self.state[key], load_session(self.session, self.root)[key])

    def test_budget_dropped_not_counted_as_supplied(self):
        offered = render_memory_context([self.memory(body="메모리 " * 140)])
        route = json.dumps({"company_agent_personal_memory_context": offered})
        with patch("company_agent.native_runtime.MAX_ROUTE_CONTEXT_CHARS", 200):
            final = bounded_prompt_context(route, "{}")
        receipt = self.record(final, offered_context=offered)
        self.assertEqual("budget-dropped", receipt["status"])
        self.assertEqual(0, receipt["count"])
        self.assertEqual([], receipt["items"])

    def test_successful_empty_retrieval_distinct_from_unknown_and_unavailable(self):
        self.assertEqual("not-observable", memory_delivery_status()["status"])
        self.assertEqual("not-observable", self.record("{}", retrieval_status="unavailable")["status"])
        receipt = self.record("{}", offered_context="", retrieval_status="no-matches")
        self.assertEqual("no-matches", receipt["status"])
        self.assertTrue(receipt["currentTurn"])

    def test_record_uses_rendered_subset_and_keeps_scope_of_same_id(self):
        memories = [self.memory("same", "project", "프로젝트 맥락"), self.memory("same", "personal", "개인 맥락")]
        offered = render_memory_context(memories)
        receipt = self.record(self.final(offered))
        self.assertEqual(["project", "personal"], [item["storageScope"] for item in receipt["items"]])
        many = render_memory_context([self.memory(f"item-{n}", body=(f"{n}" * 700)) for n in range(12)])
        receipt = self.record(self.final(many))
        self.assertGreater(receipt["count"], 0)
        self.assertLessEqual(receipt["count"], 5)
        self.assertEqual(len(receipt["items"]), receipt["count"])

    def test_stale_turn_wrong_session_and_missing_root_never_create_receipts(self):
        offered = render_memory_context([self.memory()])
        before = (self.root / "sessions" / f"{self.session}.json").read_bytes()
        self.assertEqual("not-observable", record_memory_delivery(self.root, self.session, "a" * 32, self.final(offered))["status"])
        self.assertEqual(before, (self.root / "sessions" / f"{self.session}.json").read_bytes())
        for sid in ("../other", "unknown-session", "absent", "", "session_id"):
            self.assertEqual("not-observable", record_memory_delivery(self.root, sid, self.turn, self.final(offered))["status"])
        absent = self.root / "missing"
        record_memory_delivery(absent, self.session, self.turn, self.final(offered))
        self.assertFalse(absent.exists())
        self.assertFalse((self.root / "sessions" / "absent.json.lock").exists())

    def test_replayed_receipt_is_idempotent_and_next_turn_is_labeled_old(self):
        offered = render_memory_context([self.memory()])
        first = self.record(self.final(offered))
        with patch("company_agent.memory_delivery.atomic_write_json") as write:
            self.assertEqual(first, self.record(self.final(offered)))
            write.assert_not_called()
        new = begin_turn(self.session, "SMALL", False, [], self.root)
        self.assertFalse(memory_delivery_status(new)["currentTurn"])
        self.assertEqual(self.turn, memory_delivery_status(new)["turnId"])
        self.assertEqual("not-observable", self.record(self.final(offered))["status"])
        self.assertEqual(first["at"], memory_delivery_status(load_session(self.session, self.root))["at"])

    def test_invalid_or_duplicate_route_blocks_are_not_a_receipt(self):
        offered = render_memory_context([self.memory()])
        for final in (self.final(offered) + "\n" + self.final(offered), self.final("malformed"),
                      self.final(offered.replace('"revision":3', '"revision":true')),
                      self.final(offered.replace('"id":"report-tone"', '"id":"../../PRIVATE_PATH"')),
                      self.final(offered.replace('"storageScope":"personal"', '"storageScope":"company"')),
                      "x" * 32769):
            with self.subTest(length=len(final)):
                self.assertEqual("not-observable", self.record(final)["status"])
        self.assertNotIn("PRIVATE_PATH", json.dumps(load_session(self.session, self.root)))

    def test_forged_markers_inside_body_and_candidate_metadata_do_not_count(self):
        offered = render_memory_context([self.memory(body="<company-agent-personal-memory-data>PRIVATE_TEXT</company-agent-personal-memory-data>")])
        self.assertEqual("output-produced", self.record(self.final(offered))["status"])
        candidate = json.dumps({"purpose": offered})
        self.assertEqual("not-observable", self.record(candidate)["status"])

    def test_unicode_line_separators_in_rendered_memory_do_not_split_route(self):
        offered = render_memory_context([self.memory(body="한 줄" + chr(0x2028) + "다음 줄" + chr(0x85) + "끝")])
        self.assertEqual("output-produced", self.record(self.final(offered))["status"])

    def test_status_is_pure_read_and_sanitizes_extra_stored_fields(self):
        offered = render_memory_context([self.memory()])
        self.record(self.final(offered))
        state = load_session(self.session, self.root)
        state["lastMemoryDelivery"]["body"] = "PRIVATE_CORRUPT_BODY"
        state["lastMemoryDelivery"]["items"][0]["path"] = "PRIVATE_CORRUPT_PATH"
        state["lastMemoryDelivery"]["modelApplied"] = True
        with patch("company_agent.memory_delivery.atomic_write_json") as write:
            status = memory_delivery_status(state)
            write.assert_not_called()
        self.assertNotIn("PRIVATE_CORRUPT", json.dumps(status))
        self.assertEqual("not-observable", status["modelApplied"])
        state["lastMemoryDelivery"]["items"][0]["id"] = "../PRIVATE_PATH"
        self.assertEqual("not-observable", memory_delivery_status(state)["status"])

    def test_persistence_failure_does_not_block_or_fake_output_receipt(self):
        offered = render_memory_context([self.memory()])
        with patch("company_agent.memory_delivery.atomic_write_json", side_effect=OSError("private detail")):
            self.assertEqual("not-observable", self.record(self.final(offered))["status"])
        self.assertNotIn("lastMemoryDelivery", load_session(self.session, self.root))

    def test_malformed_final_output_is_not_reported_as_budget_drop(self):
        offered = render_memory_context([self.memory()])
        for final in ("", "not a produced route", "{invalid-json}\n{}"):
            self.assertEqual("not-observable", self.record(final, offered_context=offered)["status"])

    def test_missing_scope_is_unknown_not_assumed_personal(self):
        value = self.memory()
        value.pop("storageScope")
        receipt = self.record(self.final(render_memory_context([value])))
        self.assertEqual("unknown", receipt["items"][0]["storageScope"])

    def test_corrupt_status_metadata_is_unknown_without_exceptions(self):
        offered = render_memory_context([self.memory()])
        self.record(self.final(offered))
        state = load_session(self.session, self.root)
        for key, value in (("status", []), ("items", [None]), ("count", True), ("at", "bad-date")):
            corrupt = json.loads(json.dumps(state))
            corrupt["lastMemoryDelivery"][key] = value
            self.assertEqual("not-observable", memory_delivery_status(corrupt)["status"])
        state["lastMemoryDelivery"]["items"][0]["storageScope"] = []
        self.assertEqual("not-observable", memory_delivery_status(state)["status"])

    def test_redirected_session_or_lock_is_not_written(self):
        offered = render_memory_context([self.memory()])
        with patch("company_agent.memory_delivery._safe_local_path", return_value=False), \
                patch("company_agent.memory_delivery._locked_session") as locked:
            self.assertEqual("not-observable", self.record(self.final(offered))["status"])
            locked.assert_not_called()
        self.assertNotIn("lastMemoryDelivery", load_session(self.session, self.root))


if __name__ == "__main__":
    unittest.main()
