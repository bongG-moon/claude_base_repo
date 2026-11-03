"""Build/check offline HTML reference examples with synthetic, non-business data."""
from pathlib import Path
import argparse
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'company-agent-plugin/scripts'))
from company_agent import business_artifacts, report_gallery, report_styles, report_typography


def main():
    parser = argparse.ArgumentParser(description='HTML 양식 갤러리 생성 또는 일치 확인')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    documents = {'design-picker.html': report_styles.picker_html()}
    with tempfile.TemporaryDirectory() as folder:
        examples = {key: report_gallery.example_spec(key) for key, *_ in report_styles.REFERENCE_PRESETS}
        examples.update({'style-' + key: report_gallery.style_example_spec(key) for key, *_ in report_styles.STYLES})
        for key, spec in examples.items():
            target = Path(folder) / (key + '.html')
            # 정적 갤러리 묶음은 두 글꼴을 공유합니다. 실제 제작 결과는 선택한
            # 글꼴을 한 HTML에 넣는 기본 동작을 그대로 사용합니다.
            spec['fontSource'] = 'system'
            result = business_artifacts.create_html(spec, target)
            if not result.get('ok'):
                raise RuntimeError(result)
            document = target.read_text(encoding='utf-8')
            face = report_typography.bundled_css(result['typography']['family'], '../fonts')
            document = document.replace('<style>', '<style>' + face, 1).replace('font-src data:', "font-src &#x27;self&#x27; file: data:")
            documents['examples/' + key + '.html'] = document
    mismatches = []
    for base in ('company-agent-plugin/skills/html-report/assets', 'standalone-skills/html-report/assets'):
        for relative, document in documents.items():
            path = ROOT / base / relative
            if args.check:
                if not path.is_file() or path.read_text(encoding='utf-8') != document:
                    mismatches.append(str(path.relative_to(ROOT)))
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(document, encoding='utf-8')
    if mismatches:
        print('갤러리 갱신 필요: ' + ', '.join(mismatches))
        return 1
    print('HTML 갤러리 2곳 / 디자인 10종 + 구성 예제 3종: ' + ('일치 확인' if args.check else '생성 완료'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
