"""Installed fixed pywin32 entrypoint for Word and PowerPoint."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from company_agent.office_pywin32 import main

if __name__ == '__main__': raise SystemExit(main())
