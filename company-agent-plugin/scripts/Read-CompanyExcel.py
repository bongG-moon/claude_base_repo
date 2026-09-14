"""Installed fixed xlwings entrypoint; no runtime-generated Python code."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from company_agent.excel_xlwings import main

if __name__=='__main__': raise SystemExit(main())
