"""Generate a metadata-only HTML preview from the existing complex fixture."""
import argparse
from pathlib import Path
import sys

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from excel_pipeline import analyze
from workflow_report import render_workflow, build_workflow
from test_fixture_paths import fixture_root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = analyze(fixture_root() / "고급_내장VBA_혼합.xlsm")
    html = render_workflow(result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(html)
    model = build_workflow(result)
    print(f"{args.output}: tables={model['table_count']}, nodes={len(model['nodes'])}, edges={len(model['edges'])}, warnings={len(model['warnings'])}")


if __name__ == "__main__":
    main()
