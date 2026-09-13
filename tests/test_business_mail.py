"""Synthetic only: these tests must never connect to the user's Outlook."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "company-agent-plugin" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from company_agent import business_mail as mail

STORE = "AABB0011"
PST = "AABB0022"
MESSAGE = "AABB0033"


class MailValidationTests(unittest.TestCase):
    def spec(self):
        return {"account_smtp": "employee@example.invalid", "store_ids": [STORE]}

    def test_search_normalizes_explicit_selection_and_defaults(self):
        spec = self.spec() | {"store_ids": [STORE.lower()], "query": "주간 — 보고"}
        with patch.object(mail, "_invoke", return_value={"ok": True}) as invoke:
            result = mail.search_mail(spec)
            self.assertTrue(result["ok"])
            self.assertFalse(result["search_scope"]["body_searched"])
        normalized = invoke.call_args.args[1]
        self.assertEqual([STORE], normalized["store_ids"])
        self.assertEqual(500, normalized["scan_limit"])
        self.assertNotIn("include_body", normalized)
        self.assertNotIn("_date_assumptions", normalized)

    def test_operator_naive_dates_use_pc_local_timezone_and_expose_assumption(self):
        class KoreanPCDateTime(datetime):
            def astimezone(self, tz=None):
                if self.tzinfo is None:
                    return self.replace(tzinfo=timezone(timedelta(hours=9))).astimezone(tz or timezone(timedelta(hours=9)))
                return super().astimezone(tz)
        spec = self.spec() | {"received_after": "2026-09-08T00:00:00", "received_before": "2026-09-12T00:00:00"}
        with patch.object(mail, "datetime", KoreanPCDateTime), patch.object(mail, "_invoke", return_value={"ok": True}) as invoke:
            result = mail.search_mail(spec)
        request = invoke.call_args.args[1]
        self.assertEqual("2026-09-07T15:00:00+00:00", request["received_after"])
        self.assertEqual("2026-09-11T15:00:00+00:00", request["received_before"])
        self.assertEqual(2, len(result["search_scope"]["timezone_assumptions"]))
        self.assertEqual("pc_local_timezone_at_requested_date", result["search_scope"]["timezone_assumptions"][0]["basis"])

    def test_explicit_timezone_date_range_is_utc_with_no_assumptions(self):
        with patch.object(mail, "_invoke", return_value={"ok": True}) as invoke:
            result = mail.search_mail(self.spec() | {
                "received_after": "2026-09-08T00:00:00+09:00", "received_before": "2026-09-12T00:00:00+09:00"})
        self.assertEqual("2026-09-11T15:00:00+00:00", invoke.call_args.args[1]["received_before"])
        self.assertEqual([], result["search_scope"]["timezone_assumptions"])

    def test_validation_stage_codes_are_specific_and_never_expose_input(self):
        with patch.object(mail, "_invoke") as invoke:
            for extra, reason in [({"received_after": "PRIVATE-invalid-date"}, "date_format_invalid"),
                                  ({"account_smtp": "PRIVATE-invalid-account"}, "account_format_invalid"),
                                  ({"limit": 0}, "limit_invalid"),
                                  ({"received_after": "2026-09-12T00:00:00Z", "received_before": "2026-09-08T00:00:00Z"}, "date_range_invalid")]:
                response = mail.search_mail(self.spec() | extra)
                self.assertEqual(reason, response["reason"])
                self.assertEqual("request_validation", response["stage"])
                self.assertFalse(response["bridge_called"])
                self.assertNotIn("PRIVATE", json.dumps(response))
            invoke.assert_not_called()

    def test_body_needs_explicit_and_internal_guard_grant(self):
        spec = self.spec() | {"message_refs": [{"store_id": STORE, "entry_id": MESSAGE}], "include_body": True}
        with patch.object(mail, "_invoke") as invoke:
            self.assertEqual("permission_denied", mail.read_mail(spec)["status"])
            invoke.assert_not_called()
        with patch.object(mail, "_invoke", return_value={"ok": True}) as invoke:
            mail.read_mail(spec | {"body_access_approved": True})
            self.assertTrue(invoke.call_args.args[1]["include_body"])

    def test_unknown_fields_and_destructive_intents_are_rejected(self):
        with patch.object(mail, "_invoke") as invoke:
            for key in ("send", "move", "delete", "archive", "from", "powershell", "include_body"):
                self.assertEqual("invalid_request", mail.search_mail(self.spec() | {key: True})["status"])
            invoke.assert_not_called()

    def test_limits_types_and_dates_fail_closed(self):
        cases = [{"limit": 0}, {"limit": True}, {"limit": 51}, {"scan_limit": 2001},
                 {"folder_limit": 101}, {"query": "a\nscript"}, {"query": "x" * 201},
                 {"received_after": "2025-01-01"}, {"received_after": "invalid"},
                 {"received_after": "2026-09-01T00:00:00Z", "received_before": "2025-01-01T00:00:00Z"}]
        with patch.object(mail, "_invoke") as invoke:
            for extra in cases:
                with self.subTest(extra=extra):
                    self.assertEqual("invalid_request", mail.search_mail(self.spec() | extra)["status"])
            invoke.assert_not_called()

    def test_pst_and_message_must_be_inside_selected_scope(self):
        self.assertEqual("invalid_request", mail.search_mail(self.spec() | {"pst_store_ids": [PST]})["status"])
        self.assertEqual("invalid_request", mail.read_mail(self.spec() | {
            "message_refs": [{"store_id": PST, "entry_id": MESSAGE}]
        })["status"])

    def test_messages_are_safe_and_no_writes_available(self):
        result = mail.read_mail(self.spec())
        self.assertFalse(result["sending_supported"])
        self.assertTrue(result["read_only"])
        self.assertEqual("not_detectable", result["external_drm"])
        self.assertEqual("profile_account_mapping_only", result["identity_assurance"])
        for name in ("send_mail", "delete_mail", "move_mail", "archive_mail"):
            self.assertFalse(hasattr(mail, name))


class MailTransportTests(unittest.TestCase):
    def invoke_mock(self, result=None, error=None):
        with patch.object(mail.os, "name", "nt"), patch.object(mail.Path, "is_file", return_value=True), \
                patch.object(mail, "windows_powershell", return_value=Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")), \
                patch.object(mail.subprocess, "run", return_value=result, side_effect=error) as run:
            response = mail.capabilities()
        return response, run

    def test_utf8_output_and_ascii_input_without_policy_override(self):
        raw = {"status": "ok", "accounts": [{"display_name": "업무 — 계정"}]}
        result, run = self.invoke_mock(subprocess.CompletedProcess([], 0, json.dumps(raw, ensure_ascii=False).encode("utf-8"), b""))
        self.assertEqual("업무 — 계정", result["accounts"][0]["display_name"])
        args = run.call_args.args[0]
        self.assertNotIn("-ExecutionPolicy", args)
        self.assertNotIn("-Command", args)
        self.assertEqual({}, json.loads(run.call_args.kwargs["input"].decode("ascii")))
        self.assertEqual(45, run.call_args.kwargs["timeout"])
        self.assertEqual("outlook_bridge", result["stage"])
        self.assertTrue(result["bridge_called"])

    def test_bridge_scope_failure_is_distinct_from_request_validation(self):
        raw = {"status": "connection_required", "reason": "account_mapping_required"}
        result, _ = self.invoke_mock(subprocess.CompletedProcess([], 0, json.dumps(raw).encode(), b""))
        self.assertEqual("account_mapping_required", result["reason"])
        self.assertEqual("outlook_bridge", result["stage"])
        self.assertTrue(result["bridge_called"])

    def test_errors_and_stderr_do_not_leak_private_information(self):
        private = "PRIVATE subject mailbox token C:\\private"
        for value, error in ((subprocess.CompletedProcess([], 1, b"", private.encode()), None),
                             (None, OSError(private)),
                             (None, subprocess.TimeoutExpired(private, 45)),
                             (subprocess.CompletedProcess([], 0, private.encode(), b""), None)):
            with self.subTest(error=type(error).__name__):
                response, _ = self.invoke_mock(value, error)
                self.assertNotIn("PRIVATE", json.dumps(response))
                self.assertFalse(response["ok"])

    def test_response_cannot_claim_sending_or_verified_identity(self):
        raw = {"status": "ok", "read_only": False, "sending_supported": True,
               "identity_assurance": "verified", "external_drm": "unrestricted"}
        response, _ = self.invoke_mock(subprocess.CompletedProcess([], 0, json.dumps(raw).encode(), b""))
        self.assertTrue(response["read_only"])
        self.assertFalse(response["sending_supported"])
        self.assertEqual("profile_account_mapping_only", response["identity_assurance"])
        self.assertEqual("not_detectable", response["external_drm"])

    def test_item_errors_have_korean_explanations(self):
        raw = {"status": "partial", "items": [{"status": "blocked"}, {"status": "permission_denied"}, {"status": "unknown"}]}
        response, _ = self.invoke_mock(subprocess.CompletedProcess([], 0, json.dumps(raw).encode(), b""))
        for item in response["items"]:
            self.assertTrue(any(ord(char) > 127 for char in item["message"]))

    def test_actual_partial_envelope_has_restriction_codes_without_overclassifying_failures(self):
        raw = {"status": "partial", "complete": False, "requested_count": 4, "completed_count": 4,
               "items": [{"store_id": STORE, "entry_id": MESSAGE, "status": "blocked", "protection_status": "restricted"},
                         {"store_id": STORE, "entry_id": MESSAGE, "status": "permission_denied", "body_status": "permission_denied"},
                         {"store_id": STORE, "entry_id": MESSAGE, "status": "unknown", "protection_status": "unknown"},
                         {"store_id": STORE, "entry_id": MESSAGE, "status": "unknown"}]}
        response, _ = self.invoke_mock(subprocess.CompletedProcess([], 0, json.dumps(raw).encode(), b""))
        self.assertEqual(["protection_blocked", "permission_denied", "protection_unknown", None],
                         [item.get("code") for item in response["items"]])
        # A disconnected Outlook isn't evidence that any document is protected.
        failed, _ = self.invoke_mock(None, OSError("unavailable"))
        self.assertNotIn("code", failed)

    def test_search_skipped_protected_items_have_structured_warning_without_subjects(self):
        raw = {"status": "partial", "items": [], "blocked_count": 2, "unknown_count": 3,
               "protection_unknown_count": 1}
        response, _ = self.invoke_mock(subprocess.CompletedProcess([], 0, json.dumps(raw).encode(), b""))
        self.assertEqual([{"code": "protection_blocked", "count": 2}, {"code": "protection_unknown", "count": 1}],
                         response["restriction_warnings"])
        raw = {"status": "partial", "items": [], "blocked_count": 0, "unknown_count": 3,
               "protection_unknown_count": 0}
        response, _ = self.invoke_mock(subprocess.CompletedProcess([], 0, json.dumps(raw).encode(), b""))
        self.assertNotIn("restriction_warnings", response)


@unittest.skipUnless(os.name == "nt", "Synthetic Windows PowerShell checks require Windows")
class MailPowerShellSyntheticTests(unittest.TestCase):
    def run_fixture(self, body: str) -> dict:
        # Parse and load function definitions ONLY. Never execute the helper's
        # top-level dispatcher or Get-ProfileContext/GetActiveObject.
        helper = str(mail.HELPER).replace("'", "''")
        source = f"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile('{helper}', [ref]$tokens, [ref]$errors)
if ($errors.Count) {{ throw 'parse_error' }}
$functions=$ast.FindAll({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]}}, $false)
foreach ($function in $functions) {{
    if ($function.Name -eq 'Get-ProfileContext') {{ continue }}
    . ([scriptblock]::Create($function.Extent.Text))
}}
$script:watch=[Diagnostics.Stopwatch]::StartNew()
{body}
"""
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        # EncodedCommand only transports this fixed synthetic test script; no
        # user/mail content or production helper is executed here.
        import base64
        encoded = base64.b64encode(source.encode("utf-16-le")).decode("ascii")
        result = subprocess.run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                                capture_output=True, timeout=20, check=False)
        self.assertEqual(0, result.returncode, result.stderr.decode("utf-8", "replace"))
        return json.loads(result.stdout.decode("utf-8-sig"))

    def test_store_scope_rejects_foreign_mailbox_and_account_owned_pst(self):
        result = self.run_fixture(r"""
$context=@{accounts=@(@{smtp='self@example.invalid';delivery_store_id='AABB0011'},
    @{smtp='other@example.invalid';delivery_store_id='AABB0033'});
    stores=@(@{store_id='AABB0011';is_pst=$false;is_open=$true;object='self'},
             @{store_id='AABB0022';is_pst=$true;is_open=$true;object='standalone'},
             @{store_id='AABB0033';is_pst=$true;is_open=$true;object='other'},
             @{store_id='AABB0044';is_pst=$false;is_open=$true;object='shared'})}
$out=@{}
foreach ($id in @('AABB0011','AABB0022','AABB0033','AABB0044')) {
    $spec=[pscustomobject]@{account_smtp='self@example.invalid';store_ids=@($id);pst_store_ids=@($id)}
    try {$selection=Get-SelectedStores $spec $context; $out[$id]='allowed'} catch {$out[$id]=$_.Exception.Message}
}
$out | ConvertTo-Json -Compress
""")
        self.assertEqual("allowed", result[STORE])
        self.assertEqual("allowed", result[PST])
        self.assertEqual("store_not_allowed", result["AABB0033"])
        self.assertEqual("store_not_allowed", result["AABB0044"])

    def test_fixed_bridge_failure_codes_do_not_leak_exception_text(self):
        result = self.run_fixture(r"""
@{account=(Get-BridgeFailure 'account_mapping_required'); store=(Get-BridgeFailure 'store_not_open');
  denied=(Get-BridgeFailure 'store_not_allowed'); invalid=(Get-BridgeFailure 'invalid_request');
  private=(Get-BridgeFailure 'PRIVATE mail subject')} | ConvertTo-Json -Depth 5 -Compress
""")
        self.assertEqual("account_mapping_required", result["account"]["reason"])
        self.assertEqual("store_not_open", result["store"]["reason"])
        self.assertEqual("permission_denied", result["denied"]["status"])
        self.assertEqual("bridge_request_invalid", result["invalid"]["reason"])
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_unselected_pst_and_ambiguous_accounts_fail_closed(self):
        result = self.run_fixture(r"""
$context=@{accounts=@(@{smtp='self@example.invalid';delivery_store_id='AABB0011'});
    stores=@(@{store_id='AABB0022';is_pst=$true;is_open=$true;object='pst'})}
$spec=[pscustomobject]@{account_smtp='self@example.invalid';store_ids=@('AABB0022');pst_store_ids=@()}
$out=@{}
try {$null=Get-SelectedStores $spec $context; $out.pst='bad'} catch {$out.pst=$_.Exception.Message}
$context.accounts+=@{smtp='self@example.invalid';delivery_store_id='AABB0022'}
try {$null=Get-SelectedStores $spec $context; $out.account='bad'} catch {$out.account=$_.Exception.Message}
$out | ConvertTo-Json -Compress
""")
        self.assertEqual("store_not_allowed", result["pst"])
        self.assertEqual("account_mapping_required", result["account"])

    def test_protected_and_unknown_permission_do_not_read_metadata(self):
        result = self.run_fixture(r"""
$protected=[pscustomobject]@{Class=43;Permission=1;PermissionTemplateGuid=''}
$protected | Add-Member ScriptProperty Subject {throw 'PRIVATE-METADATA-MUST-NOT-BE-READ'}
$unknown=[pscustomobject]@{Class=43}
$unknown | Add-Member ScriptProperty Permission {throw 'PRIVATE-PERMISSION-FAILURE'}
$out=@{protected=(Get-ItemMetadata $protected 'AABB0011' 'AABB0033');
       unknown=(Get-ItemMetadata $unknown 'AABB0011' 'AABB0033')}
$out | ConvertTo-Json -Compress -Depth 6
""")
        self.assertEqual("blocked", result["protected"]["status"])
        self.assertEqual("unknown", result["unknown"]["status"])
        self.assertEqual("restricted", result["protected"]["protection_status"])
        self.assertEqual("unknown", result["unknown"]["protection_status"])
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn("subject", result["protected"])

    def test_helper_has_no_mail_mutations_or_permission_changes(self):
        text = mail.HELPER.read_text(encoding="ascii")
        for forbidden in (".Send(", ".Move(", ".Copy(", ".Delete(", ".Save(", ".SaveAs(",
                          ".SaveAsFile(", ".AddStore", ".Quit(", "New-Object -ComObject",
                          ".Permission =", ".Permission=", "HTMLBody", "PropertyAccessor"):
            self.assertNotIn(forbidden, text)
        self.assertIn("GetActiveObject('Outlook.Application')", text)

    def test_selected_read_does_not_touch_body_without_opt_in(self):
        result = self.run_fixture(r"""
$script:bodyReads=0
$script:fakeItem=[pscustomobject]@{Class=43;Permission=0;PermissionTemplateGuid='';
    Subject='synthetic';SenderName='test';SenderEmailAddress='test@example.invalid';
    ReceivedTime=[datetime]'2026-09-01T00:00:00Z';Size=20;Attachments=[pscustomobject]@{Count=0};
    Parent=[pscustomobject]@{StoreID='AABB0011'}}
$script:fakeItem | Add-Member ScriptProperty Body {$script:bodyReads++; return 'synthetic body'}
$script:session=[pscustomobject]@{}
$script:session | Add-Member ScriptMethod GetItemFromID {param($entry,$store) return $script:fakeItem}
$spec=[pscustomobject]@{message_refs=@(@{store_id='AABB0011';entry_id='AABB0033'});
    include_body=$false;body_access_approved=$false;body_char_limit=9}
$metadata=Read-SelectedMail $spec @{'AABB0011'='selected'}
$before=$script:bodyReads
$spec.include_body=$true;$spec.body_access_approved=$true
$withBody=Read-SelectedMail $spec @{'AABB0011'='selected'}
$script:fakeItem.Permission=1
$protected=Read-SelectedMail $spec @{'AABB0011'='selected'}
@{metadata=$metadata;before=$before;with_body=$withBody;after=$script:bodyReads;protected=$protected} | ConvertTo-Json -Depth 10 -Compress
""")
        self.assertEqual(0, result["before"])
        self.assertEqual(1, result["after"])
        self.assertNotIn("body", result["metadata"]["items"][0])
        self.assertEqual("synthetic", result["with_body"]["items"][0]["body"])
        self.assertTrue(result["with_body"]["items"][0]["body_truncated"])
        self.assertEqual("blocked", result["protected"]["items"][0]["status"])
        self.assertNotIn("body", result["protected"]["items"][0])

    def test_metadata_search_is_bounded_and_never_reads_body(self):
        result = self.run_fixture(r"""
$fake=[pscustomobject]@{Class=43;Permission=0;PermissionTemplateGuid='';EntryID='AABB0033';
    Subject='synthetic report';SenderName='test';SenderEmailAddress='test@example.invalid';
    ReceivedTime=[datetime]'2026-09-01T00:00:00Z';Size=20;Attachments=[pscustomobject]@{Count=0}}
$fake | Add-Member ScriptProperty Body {throw 'BODY-MUST-NOT-BE-READ'}
$collection=[pscustomobject]@{Count=1000;Data=@($fake)}
$collection | Add-Member ScriptMethod Item {param($index) return $this.Data[0]}
$collection | Add-Member ScriptMethod Sort {param($field,$descending)}
$folder=[pscustomobject]@{EntryID='AABB0044';Items=$collection;Folders=[pscustomobject]@{Count=0}}
$store=[pscustomobject]@{Root=$folder}
$store | Add-Member ScriptMethod GetRootFolder {return $this.Root}
$spec=[pscustomobject]@{limit=20;scan_limit=3;folder_limit=1;query='report';include_subfolders=$true;
    folder_ids=@();received_after=$null;received_before=$null}
Search-SelectedMail $spec @{'AABB0011'=$store} | ConvertTo-Json -Depth 10 -Compress
""")
        self.assertEqual("partial", result["status"])
        self.assertEqual(3, result["scanned_count"])
        self.assertEqual(3, len(result["items"]))
        self.assertNotIn("body", result["items"][0])
        self.assertEqual("not_verified", result["server_completeness"])
        self.assertEqual(["scan_limit"], result["partial_reasons"])

    def test_sorted_old_tail_skips_to_child_but_failed_sort_scans_boundedly(self):
        result = self.run_fixture(r"""
$old=[pscustomobject]@{Class=43;Permission=0;PermissionTemplateGuid='';EntryID='AABB0033';
    Subject='report';SenderName='test';SenderEmailAddress='test@example.invalid';
    ReceivedTime=[datetime]'2026-09-01T00:00:00Z';Size=20;Attachments=[pscustomobject]@{Count=0}}
$old | Add-Member ScriptProperty Body {throw 'BODY-MUST-NOT-BE-READ'}
$recent=$old.PSObject.Copy(); $recent.ReceivedTime=[datetime]'2026-09-10T00:00:00Z'
$childItems=[pscustomobject]@{Count=1;Data=@($recent)}
$childItems | Add-Member ScriptMethod Item {param($index) return $this.Data[$index-1]}
$childItems | Add-Member ScriptMethod Sort {param($field,$descending)}
$child=[pscustomobject]@{EntryID='AABB0055';Items=$childItems;Folders=[pscustomobject]@{Count=0}}
$children=[pscustomobject]@{Count=1;Data=@($child)}
$children | Add-Member ScriptMethod Item {param($index) return $this.Data[$index-1]}
$collection=[pscustomobject]@{Count=1000;Data=@($old);FailSort=$false}
$collection | Add-Member ScriptMethod Item {param($index) return $this.Data[0]}
$collection | Add-Member ScriptMethod Sort {param($field,$descending) if ($this.FailSort) {throw 'sort_unavailable'}}
$folder=[pscustomobject]@{EntryID='AABB0044';Items=$collection;Folders=$children}
$store=[pscustomobject]@{Root=$folder}
$store | Add-Member ScriptMethod GetRootFolder {return $this.Root}
$spec=[pscustomobject]@{limit=20;scan_limit=3;folder_limit=2;query='report';include_subfolders=$true;
    folder_ids=@();received_after='2026-09-08T00:00:00Z';received_before='2026-09-12T00:00:00Z'}
$sorted=Search-SelectedMail $spec @{'AABB0011'=$store}
$collection.FailSort=$true
$unsorted=Search-SelectedMail $spec @{'AABB0011'=$store}
@{sorted=$sorted;unsorted=$unsorted} | ConvertTo-Json -Depth 10 -Compress
""")
        self.assertEqual("ok", result["sorted"]["status"])
        self.assertEqual(2, result["sorted"]["scanned_count"])
        self.assertEqual("AABB0055", result["sorted"]["items"][0]["folder_id"])
        self.assertEqual("partial", result["unsorted"]["status"])
        self.assertEqual(3, result["unsorted"]["scanned_count"])
        self.assertEqual(["scan_limit"], result["unsorted"]["partial_reasons"])


if __name__ == "__main__":
    unittest.main()
