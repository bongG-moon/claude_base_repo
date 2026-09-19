"""Build the shipped offline picker from the same CSS used for real reports."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'company-agent-plugin/scripts'))
from company_agent.report_styles import picker_html

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args=parser.parse_args()
    target=ROOT/'company-agent-plugin/skills/html-report/assets/design-picker.html'
    text=picker_html()
    if args.check:
        if not target.is_file() or target.read_text(encoding='utf-8') != text:
            raise SystemExit('Packaged picker is stale. Run this build script.')
        print('Packaged picker matches production themes.')
    else:
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(text,encoding='utf-8',newline='\n')
        print(target)
