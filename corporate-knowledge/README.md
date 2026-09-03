# Corporate Knowledge Pack

This directory is the administrator-maintained source for company terminology, data catalog entries, joins, metrics, and business rules. The deployed copy is read-only to ordinary users. Personal additions are written to `%LOCALAPPDATA%\CompanyAgent\knowledge`, never here.

The initial pack deliberately contains no invented company facts. Copy a file from `templates/`, replace every placeholder, validate it, and then publish a new content version.

```powershell
python ..\company-agent-plugin\scripts\harness_cli.py knowledge validate --base .
```
