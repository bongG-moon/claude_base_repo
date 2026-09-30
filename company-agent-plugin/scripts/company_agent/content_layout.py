"""Optional explicit main-content order; no model, browser, or font service calls."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import PurePosixPath
import zipfile
import xml.etree.ElementTree as ET

TOKENS = ('body', 'bullets', 'chart', 'table', 'image', 'diagram')


class LayoutError(ValueError):
    pass


def normalize(raw, row):
    if 'contentOrder' not in raw and 'contentLayout' not in raw:
        return
    order = raw.get('contentOrder')
    if (not isinstance(order, list) or not order or len(order) > len(TOKENS)
            or any(not isinstance(k, str) or k not in TOKENS for k in order)
            or len(set(order)) != len(order)):
        raise LayoutError('contentOrder에는 body, bullets, chart, table, image, diagram 중 실제 본문 항목을 중복 없이 지정하세요.')
    if raw.get('contentLayout', 'vertical') != 'vertical':
        raise LayoutError('contentOrder의 현재 지원 배치는 contentLayout: vertical입니다. 좌우 배치로 임의 변경하지 않았습니다.')
    present = {k for k in TOKENS if row.get(k)}
    if set(order) != present:
        raise LayoutError('contentOrder에 실제 존재하는 본문 항목을 모두 한 번씩 넣으세요. 없는 항목을 만들거나 빠진 항목을 생략하지 않았습니다.')
    row['contentOrder'] = list(order)
    row['contentLayout'] = 'vertical'


def receipt(items, basis):
    return {'status': 'checked' if items else 'not-requested', 'basis': basis,
            'items': items, 'visualReview': 'not-performed', 'sentenceCount': 'not-checked'}


def check_html(document, sections):
    if not any('contentOrder' in row for row in sections):
        return receipt([], 'html-dom-and-stacked-css')
    class Blocks(HTMLParser):
        def __init__(self):
            super().__init__()
            self.section = None
            self.observed = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'section':
                self.section = attrs.get('id')
            if 'data-content-block' in attrs:
                self.observed.setdefault(self.section, []).append(attrs['data-content-block'])

        def handle_endtag(self, tag):
            if tag == 'section':
                self.section = None

    parser = Blocks()
    parser.feed(document)
    checked = []
    for n, row in enumerate(sections, 1):
        if 'contentOrder' not in row:
            continue
        if parser.observed.get(f'section-{n}') != row['contentOrder']:
            raise LayoutError('생성된 HTML의 본문 순서가 요청과 달라 저장하지 않았습니다.')
        checked.append({'section': n, 'contentOrder': row['contentOrder'], 'contentLayout': 'vertical'})
    return receipt(checked, 'html-dom-and-stacked-css')


def check_plan(data):
    checked = []
    for n, (row, page) in enumerate(zip(data['sections'], data['presentationPlan']['pages']), 1):
        if 'contentOrder' not in row:
            continue
        blocks = page.get('contentBlocks', [])
        if [b['name'] for b in blocks] != row['contentOrder']:
            raise LayoutError('PPT 본문 순서가 요청과 일치하지 않습니다.')
        previous_bottom = -1.
        for block in blocks:
            if block['y'] < previous_bottom - .01:
                raise LayoutError('PPT 본문이 위아래로 겹쳐 저장하지 않았습니다.')
            previous_bottom = block['y'] + block['h']
        checked.append({'slide': n, 'contentOrder': row['contentOrder'], 'contentLayout': 'vertical'})
    return receipt(checked, 'shared-scene-coordinates')


def check_ppt(path, data):
    result = check_plan(data)
    if not result['items']:
        return result
    # Check the saved native coordinates, not just the pre-export scene. This is
    # bounded XML inspection inside generation, not a new Office/render cycle.
    ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
          'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    with zipfile.ZipFile(path) as archive:
        rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(archive.read('ppt/_rels/presentation.xml.rels'))}
        ids = ET.fromstring(archive.read('ppt/presentation.xml')).findall('p:sldIdLst/p:sldId', ns)
        if len(ids) != len(data['sections']):
            raise LayoutError('저장된 PPT 장수가 배치 명세와 다릅니다.')
        for row, page, slide_id in zip(data['sections'], data['presentationPlan']['pages'], ids):
            if 'contentOrder' not in row:
                continue
            target = rels[slide_id.get('{'+ns['r']+'}id')]
            part = str(PurePosixPath(target.lstrip('/'))) if target.startswith('/') else str(PurePosixPath('ppt') / target)
            tree = ET.fromstring(archive.read(part)).find('p:cSld/p:spTree', ns)
            shapes = [node for node in tree if node.tag.rsplit('}', 1)[-1] in ('sp', 'pic', 'graphicFrame')]
            if len(shapes) != len(page['elements']):
                raise LayoutError('저장된 PPT 개체 수가 배치 명세와 다릅니다.')
            for block in page['contentBlocks']:
                for index in block['elementIndices']:
                    node, expected = shapes[index], page['elements'][index]
                    xfrm = node.find('p:xfrm', ns) if node.tag.endswith('graphicFrame') else node.find('p:spPr/a:xfrm', ns)
                    off = xfrm.find('a:off', ns) if xfrm is not None else None
                    ext = xfrm.find('a:ext', ns) if xfrm is not None else None
                    if off is None or ext is None:
                        raise LayoutError('저장된 PPT 개체 좌표를 확인하지 못했습니다.')
                    actual = [float(off.get('x'))/12700, float(off.get('y'))/12700,
                              float(ext.get('cx'))/12700, float(ext.get('cy'))/12700]
                    if expected['kind'] == 'image' and expected.get('fit','contain') == 'contain':
                        mismatch = (actual[0] < expected['x']-.1 or actual[1] < expected['y']-.1
                                    or actual[0]+actual[2] > expected['x']+expected['w']+.1
                                    or actual[1]+actual[3] > expected['y']+expected['h']+.1)
                    else:
                        mismatch = any(abs(v-expected[k]) > .1 for k, v in zip(('x','y','w','h'), actual))
                    if mismatch:
                        raise LayoutError('저장된 PPT 개체 배치가 요청 명세와 달라 저장하지 않았습니다.')
                    if expected['kind'] == 'table' and node.find('a:graphic/a:graphicData/a:tbl', ns) is None:
                        raise LayoutError('편집 가능한 표 개체를 확인하지 못했습니다.')
                    if expected['kind'] == 'text' and node.find('p:txBody', ns) is None:
                        raise LayoutError('편집 가능한 본문 개체를 확인하지 못했습니다.')
                    if expected['kind'] == 'chart' and node.find('a:graphic/a:graphicData/{http://schemas.openxmlformats.org/drawingml/2006/chart}chart', ns) is None:
                        raise LayoutError('편집 가능한 차트 개체를 확인하지 못했습니다.')
    result['basis'] = 'pptx-native-coordinates'
    return result
