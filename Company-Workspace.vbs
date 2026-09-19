Option Explicit
Dim shell, fs, root, command, result
Set shell = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
' Use the same Windows PowerShell profile/environment as an ordinary terminal.
command = "powershell.exe -NoLogo -WindowStyle Hidden -File " & Chr(34) & root & "\deploy\Start-CompanyWorkspace.ps1" & Chr(34)
If WScript.Arguments.Count > 0 Then
    If LCase(WScript.Arguments(0)) = "demo" Then command = command & " -Demo"
End If
result = shell.Run(command, 0, True)
If result <> 0 Then MsgBox "Company Workspace could not start. Please check your approved Python installation and organizational script policy.", vbExclamation, "Company Workspace"
