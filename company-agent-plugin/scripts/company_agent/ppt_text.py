"""Bounded Korean rich text shared by the HTML preview and native PPT output."""
from __future__ import annotations

from functools import lru_cache
import html
import math
import os
from pathlib import Path
import re
import unicodedata


def normalize_runs(raw, element, palette):
    from .business_artifacts import ArtifactError, _text
    from .ppt_scene import ink, number
    rows = raw.get('runs')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 400:
        raise ArtifactError('invalid_ppt_runs', '부분 강조는 1~400개 글자 구간으로 지정해 주세요.')
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row)-{'text','size','color','bold','font','italic','underline'}:
            raise ArtifactError('invalid_ppt_runs', '글자 구간의 내용과 서식 항목을 확인해 주세요.')
        run = {'text':_text(row.get('text',''),12000),
               'size':number(row.get('size',element['size']),6,200),
               'color':ink(row.get('color',element['color']),palette),
               'font':_text(row.get('font',element.get('font','')),80)}
        for field in ('bold','italic','underline'):
            value = row.get(field, element.get(field,False))
            if type(value) is not bool:
                raise ArtifactError('invalid_ppt_runs', '글자 구간의 굵기, 기울임과 밑줄은 true 또는 false입니다.')
            run[field] = value
        result.append(run)
    joined = ''.join(run['text'] for run in result)
    if not joined or len(joined)>12000 or ('text' in raw and raw['text'] != joined):
        raise ArtifactError('invalid_ppt_runs', '부분 강조 구간을 합친 내용이 text와 같아야 합니다. 글자를 생략하거나 바꾸지 않았습니다.')
    return joined, result


def html_runs(element, canvas_width):
    """No source HTML or CSS is accepted in a run."""
    output = []
    for run in element['runs']:
        face = ''.join(c for c in run.get('font','') if c.isalnum() or c in ' -_')
        style = (f"font-size:{run['size']/canvas_width*100:.6f}cqw;"
                 f"color:#{run['color']};font-weight:{700 if run['bold'] else 400};"
                 f"font-style:{'italic' if run['italic'] else 'normal'};"
                 f"text-decoration:{'underline' if run['underline'] else 'none'}")
        if face:
            style += f";font-family:'{face}',sans-serif"
        output.append(f'<span style="{html.escape(style,quote=True)}">{html.escape(run["text"])}</span>')
    return ''.join(output)


def write_runs(frame, element, palette, default_font):
    from pptx.dml.color import RGBColor
    from pptx.oxml.xmlchemy import OxmlElement
    from pptx.util import Pt
    frame.clear()
    paragraph = frame.paragraphs[0]
    for item in element['runs']:
        segments = re.split('(\n|\v)',item['text'])
        for segment in segments:
            if segment in ('\n','\v'):
                paragraph = frame.add_paragraph()
                continue
            if not segment:
                continue
            run = paragraph.add_run()
            run.text = segment
            run.font.name = item.get('font') or default_font
            run.font.size = Pt(item['size'])
            run.font.bold,run.font.italic,run.font.underline = item['bold'],item['italic'],item['underline']
            run.font.color.rgb = RGBColor.from_string(palette.get(item['color'],item['color']))
            for tag in ('a:ea','a:cs'):
                child = run.font._rPr.find('{http://schemas.openxmlformats.org/drawingml/2006/main}'+tag[2:])
                if child is None:
                    child = OxmlElement(tag)
                    run.font._rPr.append(child)
                child.set('typeface',run.font.name)
            run.font._rPr.set('lang','ko-KR')
    return frame


@lru_cache(maxsize=32)
def _font_path(name):
    if os.name != 'nt':
        return None
    aliases = {'맑은 고딕':'malgun gothic'}
    requested = aliases.get(name.strip().casefold(), name.strip().casefold())
    if requested=='malgun gothic':
        candidate=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'Fonts'/'malgun.ttf'
        if candidate.is_file():
            return str(candidate)
    import winreg
    for hive in (winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts') as key:
                for i in range(winreg.QueryInfoKey(key)[1]):
                    label,value,_ = winreg.EnumValue(key,i)
                    label = re.sub(r'\s*\([^)]*\)$','',label).strip().casefold()
                    if label != requested or not isinstance(value,str):
                        continue
                    path = Path(value)
                    if not path.is_absolute():
                        path = Path(os.environ.get('SystemRoot',r'C:\Windows'))/'Fonts'/path
                    if path.is_file():
                        return str(path)
        except OSError:
            pass
    return None


@lru_cache(maxsize=64)
def _measured_font(name,size):
    path = _font_path(name)
    if not path:
        return None
    try:
        from PIL import ImageFont
        return ImageFont.truetype(path,round(size*4))
    except (ImportError,OSError,ValueError):
        return None


def estimate_lines(text,width,size,font='Malgun Gothic'):
    """Measure installed fonts once per role; never install or alter the text."""
    if not text:
        return 0
    if width<=0 or size<=0:
        return 1
    measured = _measured_font(font or 'Malgun Gothic',float(size))
    if measured is None:
        return sum(max(1,math.ceil(sum(1 if unicodedata.east_asian_width(c) in 'WF' else .5 for c in line)*size/width))
                   for line in str(text).split('\n'))
    lines = 0
    for line in str(text).split('\n'):
        lines += 1
        segment = ''
        for token in re.findall(r'\S+\s*|\s+',line):
            candidate = segment+token
            if measured.getlength(candidate)/4<=width:
                segment = candidate
                continue
            if segment.strip():
                lines += 1
                segment = ''
            for char in token:
                if segment and measured.getlength(segment+char)/4>width:
                    lines += 1
                    segment = ''
                segment += char
    return lines
