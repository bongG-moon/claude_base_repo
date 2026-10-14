"""Read-only diagnostics and scoped execution of our synthetic VBA fixture.

Never sets registry, trusted locations, VBOM access or AutomationSecurity Low.
Only a SHA-bound, locally authored workbook is opened in an owned Excel process.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
from pathlib import Path
import sys
import time
import winreg

ROOT = Path(__file__).resolve().parents[3]
ORIGINAL = ROOT / "outputs/excel-xlsm-migration-test/fixtures/고급_내장VBA_혼합.xlsm"
EXPECTED = "34e03d7bcc1db17e83d448c156449d8ff34c11ad5190edf69ca4c17a2298901c"
OUT = ROOT / "outputs/excel-xlsm-native-check/native"


def observe(call):
    try:
        return {"ok": True, "value": call()}
    except Exception as error:
        return {"ok": False, "type": type(error).__name__, "message": str(error)}


def registry():
    values = []
    for label, hive in [("HKCU", winreg.HKEY_CURRENT_USER), ("HKLM", winreg.HKEY_LOCAL_MACHINE)]:
        for policy in [False, True]:
            path = ("Software\\Policies\\Microsoft" if policy else "Software\\Microsoft") + "\\Office\\16.0\\Excel\\Security"
            record = {"hive": label, "path": path}
            try:
                with winreg.OpenKey(hive, path, access=winreg.KEY_READ) as key:
                    record["exists"] = True
                    record["values"] = {}
                    for name in ["VBAWarnings", "AccessVBOM", "blockcontentexecutionfrominternet", "disablealltrustedlocations"]:
                        try:
                            record["values"][name] = winreg.QueryValueEx(key, name)[0]
                        except FileNotFoundError:
                            record["values"][name] = "not_configured_at_this_key"
            except FileNotFoundError:
                record["exists"] = False
            except PermissionError:
                record["read_status"] = "access_denied"
            values.append(record)
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-name", default="original-diagnostics.json")
    parser.add_argument("--observe-ui-seconds", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.observe_ui_seconds <= 60:
        raise ValueError("UI observation must be bounded to 60 seconds")
    if Path(args.output_name).name != args.output_name:
        raise ValueError("Output name must be a basename")
    OUT.mkdir(parents=True, exist_ok=True)
    output = OUT / args.output_name
    if output.exists():
        raise FileExistsError(output)
    digest = hashlib.sha256(ORIGINAL.read_bytes()).hexdigest()
    if digest != EXPECTED:
        raise ValueError("Synthetic source hash mismatch")
    import pythoncom
    import win32com.client
    import win32gui
    import win32process
    import win32api
    import win32con

    report = {"source_sha256": digest, "security_settings_changed": False,
              "automation_security": "ByUI (2), never Low", "registry_before": registry(),
              "attempts": [], "native_results": [], "status": "not_started"}
    report["zone_identifier"] = observe(lambda: Path(str(ORIGINAL) + ":Zone.Identifier").read_text(encoding="utf-8"))
    app = book = None
    handle = None
    pythoncom.CoInitialize()
    try:
        app = win32com.client.DispatchEx("Excel.Application")
        report["excel_version"] = app.Version
        report["excel_build"] = app.Build
        report["initial_automation_security"] = app.AutomationSecurity
        app.Visible = bool(args.observe_ui_seconds)
        app.EnableEvents = False
        app.DisplayAlerts = False
        app.AskToUpdateLinks = False
        app.AutomationSecurity = 2
        hwnd = int(app.Hwnd)
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        report["owned_pid"] = pid
        handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid)
        book = app.Workbooks.Open(str(ORIGINAL), UpdateLinks=0, ReadOnly=True,
                                  IgnoreReadOnlyRecommended=True, AddToMru=False)
        report["workbook"] = {"name": book.Name, "read_only": book.ReadOnly,
                              "has_vba_project": book.HasVBProject,
                              "vba_signed": book.VBASigned, "code_name": book.CodeName,
                              "sheets": [{"name": sheet.Name, "code_name": sheet.CodeName}
                                         for sheet in book.Worksheets]}
        report["protected_view_count"] = app.ProtectedViewWindows.Count
        report["vbproject_access"] = observe(lambda: {"name": book.VBProject.Name,
                                                       "protection": book.VBProject.Protection,
                                                       "component_count": book.VBProject.VBComponents.Count})
        # Exact known source procedures only; both naming forms are legitimate.
        for procedure in ([] if args.observe_ui_seconds else ["TrainingPreparation.CodeOf", "CodeOf"]):
            target = f"'{book.Name}'!{procedure}"
            check = observe(lambda: app.Run(target, " a01 "))
            report["attempts"].append({"procedure": procedure, **check})
            if check["ok"]:
                break
        if any(x["ok"] for x in report["attempts"]):
            for mixed, include_exceptions in [(False, False), (True, False), (False, True), (True, True)]:
                started = time.perf_counter()
                matrix = app.Run(f"'{book.Name}'!FixtureBridge.ValidateTraining", mixed, include_exceptions)
                report["native_results"].append({"mixed": mixed, "include_exceptions": include_exceptions,
                                                   "elapsed_seconds": round(time.perf_counter()-started, 3),
                                                   "matrix": matrix})
            report["status"] = "native_executed"
        else:
            report["status"] = "macro_unavailable_or_policy_blocked"
        windows = []
        def child(window, _):
            caption = win32gui.GetWindowText(window)
            if caption:
                windows.append({"class": win32gui.GetClassName(window), "text": caption[:300]})
            return len(windows) < 60
        win32gui.EnumChildWindows(hwnd, child, None)
        report["excel_child_window_captions"] = windows
        if args.observe_ui_seconds:
            print(json.dumps({"status": "ui_observation_ready", "owned_pid": pid,
                              "window_handle": hwnd, "seconds": args.observe_ui_seconds}), flush=True)
            time.sleep(args.observe_ui_seconds)
    except Exception as error:
        report["status"] = "diagnostic_error"
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if book is not None:
            report["close"] = observe(lambda: book.Close(SaveChanges=False))
        book = None
        if app is not None:
            report["quit"] = observe(lambda: app.Quit())
        app = None
        gc.collect()
        pythoncom.CoUninitialize()
        if handle is not None:
            import win32event
            report["owned_process_exited"] = win32event.WaitForSingleObject(handle, 5000) == win32event.WAIT_OBJECT_0
            win32api.CloseHandle(handle)
        report["registry_after"] = registry()
        report["registry_unchanged"] = report["registry_before"] == report["registry_after"]
        report["source_unchanged"] = hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == digest
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"registry_before", "registry_after", "native_results"}}, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
