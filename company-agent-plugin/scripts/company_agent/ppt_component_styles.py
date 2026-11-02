"""Bounded table/chart appearance shared by the draft and native PPT writer.

Only data tokens are accepted. No CSS, templates, source code or external URLs
are loaded. An absent style keeps the legacy renderer and its defaults intact.
"""
from __future__ import annotations

from copy import deepcopy
import html
import math
import re
import xml.etree.ElementTree as ET

from .business_artifacts import ArtifactError


TABLE_KEYS = {'headerFill', 'headerText', 'bodyFill', 'bodyText', 'alternateFill',
              'borderColor', 'borderWidth', 'headerBold', 'fontSize', 'align', 'padding'}
CHART_KEYS = {'seriesColors', 'legendPosition', 'fontSize', 'labelSize', 'gridColor',
              'showGrid', 'marker', 'lineWidth'}


def normalize(kind, value):
    """Validate a sparse override. Empty dictionaries deliberately stay sparse."""
    allowed = TABLE_KEYS if kind == 'table' else CHART_KEYS
    if not isinstance(value, dict) or set(value) - allowed:
        raise ArtifactError('invalid_ppt_component_style', f'{kind}Style의 지원되는 스타일 항목을 확인해 주세요.')
    result = deepcopy(value)
    colors = ('headerFill', 'headerText', 'bodyFill', 'bodyText', 'alternateFill', 'borderColor', 'gridColor')
    for key in colors:
        if key in result:
            result[key] = _color(result[key])
    if 'seriesColors' in result:
        values = result['seriesColors']
        if not isinstance(values, list) or not 1 <= len(values) <= 12:
            raise ArtifactError('invalid_ppt_component_style', '차트 계열 색상은 1~12개 RGB 값으로 지정해 주세요.')
        result['seriesColors'] = [_color(value) for value in values]
    ranges = {'borderWidth': (0, 6), 'fontSize': (6, 48 if kind == 'table' else 32),
              'padding': (0, 24), 'labelSize': (6, 32), 'lineWidth': (.25, 8)}
    for key, (low, high) in ranges.items():
        if key in result:
            value = result[key]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ArtifactError('invalid_ppt_component_style', f'{kind}Style.{key}는 {low}~{high} 범위의 숫자입니다.')
            result[key] = float(value)
    for key in ('headerBold', 'showGrid'):
        if key in result and type(result[key]) is not bool:
            raise ArtifactError('invalid_ppt_component_style', f'{kind}Style.{key}는 true 또는 false입니다.')
    for key, options in (('align', ('left', 'center', 'right')),
                         ('legendPosition', ('bottom', 'top', 'right', 'left', 'none')),
                         ('marker', ('circle', 'square', 'diamond', 'none'))):
        if key in result and (not isinstance(result[key], str) or result[key] not in options):
            raise ArtifactError('invalid_ppt_component_style', f'{kind}Style.{key}의 선택값을 확인해 주세요.')
    return result


def normalize_table_style(raw, palette=None):
    return normalize('table', raw)


def normalize_chart_style(raw, palette=None):
    return normalize('chart', raw)


def _color(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-fA-F]{6}', value):
        raise ArtifactError('invalid_ppt_component_style', '표와 차트의 색상은 # 없는 여섯 자리 RGB 값입니다.')
    return value.upper()


def inherit(elements, defaults):
    """Copy styles onto components, retaining field-level element precedence."""
    result = []
    for element in elements:
        if not isinstance(element, dict) or element.get('kind') not in ('table', 'chart'):
            result.append(element)
            continue
        kind = element['kind']
        key = kind + 'Style'
        e = dict(element)
        if key in defaults or key in e:
            e[key] = {**normalize(kind, defaults.get(key, {})), **normalize(kind, e.get(key, {}))}
            if kind == 'table' and 'fontSize' in e[key]:
                e['size'] = e[key]['fontSize']
        result.append(e)
    return result


def table_style(element, palette):
    return {'headerFill': palette['title'], 'headerText': palette['background'],
            'bodyFill': palette['background'], 'bodyText': palette['text'],
            'alternateFill': palette['tint'], 'borderColor': palette['tint'],
            'borderWidth': 1., 'headerBold': True, 'fontSize': element.get('size', 16),
            'align': 'left', 'padding': 6., **normalize('table', element.get('tableStyle', {}))}


def chart_style(element, palette):
    return {'seriesColors': [palette['accent'], palette['title'], '52667C', 'B05C32'],
            'legendPosition': 'bottom', 'fontSize': 13., 'labelSize': 12.,
            'gridColor': palette['tint'], 'showGrid': True, 'marker': 'circle',
            'lineWidth': 3., **normalize('chart', element.get('chartStyle', {}))}


def cell_style(style, row):
    return (style['headerFill'] if row == 0 else style['alternateFill'] if row % 2 else style['bodyFill'],
            style['headerText'] if row == 0 else style['bodyText'],
            bool(row == 0 and style['headerBold']))


def table_cell_css(style, row, width):
    fill, text, bold = cell_style(style, row)
    return (f'background:#{fill};color:#{text};font-weight:{700 if bold else 400};'
            f'text-align:{style["align"]};padding:{style["padding"]/width*100:.6f}cqw;'
            f'border:{style["borderWidth"]/width*100:.6f}cqw solid #{style["borderColor"]}')


def native_cell_border(cell, style):
    from pptx.oxml.xmlchemy import OxmlElement
    from pptx.util import Pt
    properties = cell._tc.get_or_add_tcPr()
    for position, side in enumerate(('lnL', 'lnR', 'lnT', 'lnB')):
        for old in list(properties):
            if old.tag.rsplit('}', 1)[-1] == side:
                properties.remove(old)
        line = OxmlElement('a:' + side)
        line.set('w', str(int(Pt(style['borderWidth']))))
        fill = OxmlElement('a:solidFill' if style['borderWidth'] else 'a:noFill')
        if style['borderWidth']:
            color = OxmlElement('a:srgbClr')
            color.set('val', style['borderColor'])
            fill.append(color)
        line.append(fill)
        # DrawingML requires edge lines before cell3D/fill/header properties.
        properties.insert(position, line)


def styled_chart_html(chart, index, element, palette, page_width, font):
    """Restyle our own trusted SVG geometry with validated tokens only."""
    from .report_design import svg_chart, PALETTE
    style = chart_style(element, palette)
    legacy = svg_chart(chart, index)
    svg_start, svg_end = legacy.index('<svg '), legacy.index('</svg>') + 6
    svg = ET.fromstring(legacy[svg_start:svg_end])
    namespace = '{http://www.w3.org/2000/svg}'
    colors = style['seriesColors']
    replacements = {value: '#' + colors[i % len(colors)] for i, value in enumerate(PALETTE)}
    legend_position = style['legendPosition']
    # Match the native automatic default unless the user names a legend position.
    show_legend = (legend_position != 'none' and
                   ('legendPosition' in element.get('chartStyle', {}) or len(chart['series']) > 1 or chart['type'] == 'pie'))
    safe_font = ''.join(c for c in font if c.isalnum() or c in ' -_')
    # SVG sizes use the chart's viewBox; convert point sizes from slide space.
    svg_width, svg_height = [float(v) for v in svg.get('viewBox').split()[2:]]
    legend_space = style['fontSize'] * 1.8 if show_legend else 0
    render_width = element['w'] - (element['w'] * .23 if show_legend and legend_position in ('left', 'right') else 0)
    render_height = element['h'] - (legend_space if show_legend and legend_position in ('top', 'bottom') else 0)
    scale = min(render_width / svg_width, max(1, render_height) / svg_height)
    pie_indices = iter(i for i, value in enumerate(chart['series'][0]['values']) if value != 0)
    for parent in list(svg.iter()):
        for node in list(parent):
            tag = node.tag.rsplit('}', 1)[-1]
            if chart['type'] == 'pie' and parent is svg:
                # Replace the report-only donut annotations with a native-style
                # category legend so all four legend positions use one contract.
                if tag == 'text' or (tag == 'rect' and float(node.get('x', 0)) >= 420) or (tag == 'circle' and node.get('r') == '72'):
                    parent.remove(node)
                    continue
                if tag in ('path', 'circle') and node.get('fill') in replacements:
                    node.set('fill', '#' + colors[next(pie_indices) % len(colors)])
            for key in ('fill', 'stroke'):
                if node.get(key) in replacements:
                    node.set(key, replacements[node.get(key)])
            if node.get('class') == 'gridline':
                if not style['showGrid']:
                    parent.remove(node)
                    continue
                node.set('style', f'stroke:#{style["gridColor"]}')
            if tag == 'text':
                size = style['labelSize'] if node.get('class') == 'chart-value' else style['fontSize']
                node.set('style', f"font-size:{size/scale:.4f}px;font-family:'{safe_font}',sans-serif")
            if tag == 'polyline':
                node.set('stroke-width', f'{style["lineWidth"]/scale:.4f}')
                # The report renderer has its own inline default. A presentation
                # element's explicit width must override that default as well.
                node.set('style', f'stroke-width:{style["lineWidth"]/scale:.4f}px')
            if chart['type'] == 'line' and tag == 'circle':
                marker = style['marker']
                if marker == 'none':
                    parent.remove(node)
                    continue
                x, y = float(node.get('cx')), float(node.get('cy'))
                radius = 2.5 / scale
                if marker == 'circle':
                    node.set('r', f'{radius:.4f}')
                elif marker == 'square':
                    node.tag = namespace + 'rect'
                    for key in ('cx', 'cy', 'r'):
                        node.attrib.pop(key, None)
                    node.attrib.update(x=f'{x-radius:.4f}', y=f'{y-radius:.4f}', width=f'{2*radius:.4f}', height=f'{2*radius:.4f}')
                else:
                    node.tag = namespace + 'path'
                    for key in ('cx', 'cy', 'r'):
                        node.attrib.pop(key, None)
                    node.set('d', f'M{x:.4f},{y-radius:.4f} L{x+radius:.4f},{y:.4f} L{x:.4f},{y+radius:.4f} L{x-radius:.4f},{y:.4f} Z')
                node.set('data-marker', marker)
    # Keep the SVG namespace local; global ElementTree namespace registration can
    # affect unrelated renderers running in this process.
    for node in svg.iter():
        node.tag = node.tag.removeprefix(namespace)
    svg.set('xmlns', namespace[1:-1])
    svg.set('style', 'min-width:0;min-height:0;width:100%;height:100%;flex:1')
    drawing = ET.tostring(svg, encoding='unicode')
    labels = chart['categories'] if chart['type'] == 'pie' else [s['name'] for s in chart['series']]
    legend = ''
    if show_legend:
        vertical = legend_position in ('left', 'right')
        legend_css = (f'font-size:{style["fontSize"]/page_width*100:.6f}cqw;'
                      f'flex-direction:{"column" if vertical else "row"};flex-wrap:wrap;'
                      'flex-shrink:0;align-items:center;' + ('max-width:23%;' if vertical else ''))
        entries = ''.join(f'<span><i style="background:#{colors[i % len(colors)]}"></i>{html.escape(label)}</span>' for i, label in enumerate(labels))
        legend = f'<div class="legend" style="{legend_css}">{entries}</div>'
    contents = legend + drawing if legend_position in ('top', 'left') else drawing + legend
    direction = 'row' if legend_position in ('left', 'right') else 'column'
    return f'<figure class="chart-frame" data-legend-position="{legend_position if show_legend else "none"}" style="flex-direction:{direction}">{contents}</figure>'
