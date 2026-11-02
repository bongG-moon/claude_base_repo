"""Bounded, read-only PPTX projection for an HTML design review.

This is a semantic preview, not an Office renderer. Unrepresented objects and
approximated inheritance/effects are reported instead of claiming fidelity.
The native preserve exporter continues to use the original PowerPoint objects.
"""
from __future__ import annotations

import base64
import math
import re


A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
PT = 12700.0
MAX_ELEMENTS = 1200
MAX_SOURCE_OBJECTS = 2400
MAX_IMAGE_BYTES = 32 * 1024 * 1024
SHAPES = {'rect', 'roundRect', 'ellipse', 'rightArrow', 'leftArrow', 'upArrow',
          'downArrow', 'leftRightArrow', 'chevron', 'diamond', 'triangle',
          'hexagon', 'parallelogram', 'trapezoid', 'pentagon', 'octagon'}


def _hex(value, fallback):
    return value.upper() if isinstance(value, str) and re.fullmatch('[a-fA-F0-9]{6}', value) else fallback


def _theme(deck, slide):
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    from lxml import etree
    result = {}
    try:
        master = slide.slide_layout.slide_master
        theme = etree.fromstring(master.part.part_related_by(RT.THEME).blob)
        colors = theme.find('.//{%s}clrScheme' % A)
        for color in colors if colors is not None else []:
            if len(color):
                result[color.tag.split('}')[-1]] = _hex(color[0].get('lastClr') or color[0].get('val'), '000000')
        result['__fonts'] = {}
        for role, tag in (('mj','majorFont'), ('mn','minorFont')):
            fonts = theme.find('.//{%s}fontScheme/{%s}%s' % (A,A,tag))
            if fonts is not None:
                korean = next((n.get('typeface') for n in fonts if n.get('script') == 'Hang'), None)
                for script in ('ea','latin','cs'):
                    node = fonts.find('{%s}%s' % (A,script))
                    result['__fonts'][f'+{role}-'+('lt' if script=='latin' else script)] = korean or (node.get('typeface') if node is not None else None)
    except (AttributeError, KeyError, ValueError):
        pass
    return result


def _paint(parent, theme, fallback):
    """Resolve explicit RGB/theme fills, including simple luminance and alpha."""
    if parent is None:
        return fallback, 1.0, False
    if parent.find('{%s}noFill' % A) is not None:
        return None, 0.0, False
    solid = parent.find('{%s}solidFill' % A)
    if solid is None or not len(solid):
        complex_fill = any(parent.find('{%s}%s' % (A, tag)) is not None for tag in ('gradFill', 'pattFill', 'blipFill'))
        return fallback, 1.0, complex_fill
    color = solid[0]
    tag = color.tag.split('}')[-1]
    if tag == 'srgbClr':
        value = _hex(color.get('val'), fallback)
    elif tag == 'sysClr':
        value = _hex(color.get('lastClr'), fallback)
    elif tag == 'schemeClr':
        alias = {'tx1':'dk1', 'tx2':'dk2', 'bg1':'lt1', 'bg2':'lt2'}
        key = alias.get(color.get('val'), color.get('val'))
        value = theme.get(key, fallback)
    else:
        return fallback, 1.0, True
    alpha = 1.0
    if value:
        rgb = [int(value[i:i+2], 16) for i in (0, 2, 4)]
        for transform in color:
            name = transform.tag.split('}')[-1]
            try:
                factor = int(transform.get('val')) / 100000.0
            except (TypeError, ValueError):
                continue
            if name == 'alpha':
                alpha = min(1.0, max(0.0, factor))
            elif name == 'lumMod':
                rgb = [round(v * factor) for v in rgb]
            elif name in ('lumOff', 'tint'):
                rgb = [round(v + (255-v)*factor) if name == 'tint' else round(v + 255*factor) for v in rgb]
            elif name == 'shade':
                rgb = [round(v * factor) for v in rgb]
        value = ''.join(f'{max(0,min(255,v)):02X}' for v in rgb)
    return value, alpha, False


def _text_style(props, fallback, theme):
    """Read OOXML directly; python-pptx Font getters can create missing rPr."""
    result = dict(fallback)
    if props is None:
        return result
    if props.get('sz') is not None:
        result['size'] = float(props.get('sz')) / 100.0
    for attr, key in (('b','bold'), ('i','italic')):
        if props.get(attr) is not None:
            result[key] = props.get(attr) not in ('0','false')
    if props.get('u') is not None:
        result['underline'] = props.get('u') != 'none'
    for tag in ('ea','latin','cs'):
        node = props.find('{%s}%s' % (A,tag))
        if node is not None and node.get('typeface'):
            declared = node.get('typeface')
            result['font'] = theme.get('__fonts',{}).get(declared) or declared
            break
    result['color'] = _paint(props, theme, fallback['color'])[0] or fallback['color']
    return result


def _reference_paint(reference, theme, fallback):
    """Resolve the explicit color token on a theme fill/line/background ref."""
    from copy import deepcopy
    from lxml import etree
    if reference is None:
        return fallback, 1.0, False
    holder = etree.Element('{%s}holder' % A)
    solid = etree.SubElement(holder, '{%s}solidFill' % A)
    for child in reference:
        if child.tag.split('}')[-1] in ('srgbClr','schemeClr','sysClr'):
            solid.append(deepcopy(child))
            return _paint(holder, theme, fallback)
    return fallback, 1.0, True


def preview_slide(slide, deck, palette, font):
    """Project supported fixed and edited objects without changing the source.

    Return ``elements/background/warnings/coverage``. Coverage counts source leaf
    objects; groups are containers and are reported separately. A complete
    supported object projection still does not prove pixel or Office fidelity.
    """
    theme = _theme(deck, slide)
    background = palette.get('background', 'FFFFFF')
    page = {'elements':[], 'background':background, 'warnings':[],
            'coverage':{'totalObjects':0, 'projectedObjects':0, 'groups':0,
                        'unsupported':[], 'approximations':[], 'sourceLayers':[],
                        'visualReview':'not_performed'}}
    coverage = page['coverage']
    image_bytes = 0
    stopped = False

    def warn(message):
        if message not in page['warnings'] and len(page['warnings']) < 30:
            page['warnings'].append(message)

    def issue(shape, layer, reason, *, unsupported=False):
        target = coverage['unsupported' if unsupported else 'approximations']
        if len(target) < 80:
            target.append({'shapeId':shape.shape_id, 'sourceLayer':layer, 'reason':reason})
        warn('기존 양식 미리보기에서 일부 개체나 상속 서식은 근사하거나 표시하지 못했습니다. 원본과 최종 PPT를 함께 확인해 주세요.')

    def emit(element):
        nonlocal stopped
        if len(page['elements']) >= MAX_ELEMENTS:
            stopped = True
            warn('한 장의 미리보기 개체가 1,200개를 넘어 나머지를 표시하지 않았습니다. 원본에서 해당 범위를 확인해 주세요.')
            return False
        if all(math.isfinite(element[k]) for k in ('x','y','w','h')) and element['w'] > 0 and element['h'] > 0:
            page['elements'].append(element)
            return True
        return False

    def bounds(shape, sx, sy, ox, oy):
        return {'x':(ox+sx*shape.left)/PT, 'y':(oy+sy*shape.top)/PT,
                'w':sx*shape.width/PT, 'h':sy*shape.height/PT}

    def text_elements(frame, box, shape, layer, *, sx=1.0, sy=1.0, anchor_override=None):
        # Do not access shape.text_frame on an empty decorative auto-shape;
        # python-pptx otherwise creates a new txBody as a side effect.
        default = {'font':font, 'size':18.0, 'bold':False, 'color':palette.get('text','333333')}
        paragraphs = list(frame.paragraphs)
        runs = []
        for index, paragraph in enumerate(paragraphs):
            if index:
                runs.append({'text':'\n'})
            props = paragraph._p.find('{%s}pPr' % A)
            base = props.find('{%s}defRPr' % A) if props is not None else None
            para_style = _text_style(base, default, theme)
            for child in paragraph._p:
                tag = child.tag.split('}')[-1]
                if tag == 'br':
                    runs.append({'text':'\n', **para_style})
                elif tag in ('r','fld'):
                    style = _text_style(child.find('{%s}rPr' % A), para_style, theme)
                    value = child.find('{%s}t' % A)
                    if value is not None:
                        runs.append({'text':(value.text or '').replace('\v','\n'), **style})
            if base is None and not all(c.find('{%s}rPr' % A) is not None for c in paragraph._p if c.tag.endswith('}r')):
                issue(shape, layer, 'text_style_inheritance')
        value = ''.join(r['text'] for r in runs)
        if not value.strip():
            return
        if len(value) > 12000:
            issue(shape, layer, 'text_too_large', unsupported=True)
            return
        margins = {k:getattr(frame,k)/PT for k in ('margin_left','margin_right','margin_top','margin_bottom')}
        text_box = {**box, 'x':box['x']+margins['margin_left']*sx, 'y':box['y']+margins['margin_top']*sy,
                    'w':box['w']-(margins['margin_left']+margins['margin_right'])*sx,
                    'h':box['h']-(margins['margin_top']+margins['margin_bottom'])*sy}
        first_props = paragraphs[0]._p.find('{%s}pPr' % A) if paragraphs else None
        align = {'ctr':'center','r':'right'}.get(first_props.get('algn') if first_props is not None else None,'left')
        e = {'kind':'text', **text_box, 'text':value, 'runs':runs,
             'font':font, 'size':max((r.get('size',18.0) for r in runs), default=18.0),
             'bold':False, 'color':default['color'], 'align':align,
             'wrap':frame.word_wrap is not False, 'lineSpacing':1.15}
        anchor = anchor_override or frame._txBody.bodyPr.get('anchor')
        if anchor in ('ctr','b'):
            e['verticalAlign'] = 'middle' if anchor == 'ctr' else 'bottom'
        # Non-uniform group scaling stretches the native glyphs, which a plain
        # HTML text box cannot reproduce. Keep text readable and report it.
        if abs(sx-sy) > .001:
            issue(shape, layer, 'nonuniform_text_scale')
        if any(p._p.find('{%s}pPr' % A) is not None and p._p.find('{%s}pPr' % A).get('lvl','0')!='0' for p in paragraphs) or any(p._p.find('{%s}pPr/{%s}buChar' % (A,A)) is not None for p in paragraphs):
            issue(shape, layer, 'paragraph_bullets_or_indents')
        if any(p._p.find('{%s}pPr/{%s}%s' % (A,A,tag)) is not None
               for p in paragraphs for tag in ('lnSpc','spcBef','spcAft')):
            issue(shape,layer,'paragraph_spacing_projection')
        emit(e)

    def table_elements(shape, box, layer):
        table = shape.table
        rows, cols = list(table.rows), list(table.columns)
        total_w, total_h = sum(c.width for c in cols), sum(r.height for r in rows)
        if not total_w or not total_h or len(rows)*len(cols) > 500:
            issue(shape, layer, 'table_size_limit', unsupported=True)
            return False
        ys = [box['y']]
        xs = [box['x']]
        for r in rows: ys.append(ys[-1]+box['h']*r.height/total_h)
        for c in cols: xs.append(xs[-1]+box['w']*c.width/total_w)
        for ri, row in enumerate(rows):
            for ci, cell in enumerate(row.cells):
                if cell.is_spanned:
                    continue
                span_w = cell.span_width if cell.is_merge_origin else 1
                span_h = cell.span_height if cell.is_merge_origin else 1
                cell_box = {'x':xs[ci], 'y':ys[ri], 'w':xs[ci+span_w]-xs[ci], 'h':ys[ri+span_h]-ys[ri]}
                fill, opacity, approximate = _paint(cell._tc.find('{%s}tcPr' % A), theme, 'FFFFFF')
                if approximate:
                    issue(shape, layer, 'complex_table_fill')
                emit({'kind':'shape', **cell_box, 'shape':'rect', 'fill':fill,
                      'opacity':opacity, 'border':'D5D5D5', 'borderWidth':.4})
                text_elements(cell.text_frame, cell_box, shape, layer,
                              anchor_override=cell._tc.find('{%s}tcPr' % A).get('anchor') if cell._tc.find('{%s}tcPr' % A) is not None else None)
        issue(shape, layer, 'table_style_and_border_projection')
        return True

    def walk(shapes, layer, sx=1.0, sy=1.0, ox=0.0, oy=0.0, depth=0):
        nonlocal image_bytes, stopped
        if depth > 20:
            stopped = True
            warn('중첩 그룹이 20단계를 넘어 더 깊은 개체를 표시하지 않았습니다.')
            return
        for shape in shapes:
            if stopped:
                return
            if layer != 'slide' and shape.is_placeholder:
                continue
            if hasattr(shape, 'shapes'):
                coverage['groups'] += 1
                xfrm = shape._element.grpSpPr.xfrm
                if shape.rotation or (xfrm is not None and (xfrm.get('flipH') in ('1','true') or xfrm.get('flipV') in ('1','true'))):
                    coverage['totalObjects'] += 1
                    issue(shape, layer, 'rotated_or_flipped_group', unsupported=True)
                    continue
                if xfrm is None or not xfrm.chExt.cx or not xfrm.chExt.cy:
                    coverage['totalObjects'] += 1
                    issue(shape, layer, 'invalid_group_transform', unsupported=True)
                    continue
                rx, ry = xfrm.ext.cx/xfrm.chExt.cx, xfrm.ext.cy/xfrm.chExt.cy
                walk(shape.shapes, layer, sx*rx, sy*ry,
                     ox+sx*(xfrm.off.x-rx*xfrm.chOff.x), oy+sy*(xfrm.off.y-ry*xfrm.chOff.y), depth+1)
                continue
            coverage['totalObjects'] += 1
            if coverage['totalObjects'] > MAX_SOURCE_OBJECTS:
                stopped = True
                warn('원본 개체가 너무 많아 미리보기를 제한했습니다. 원본과 최종 PPT를 함께 확인해 주세요.')
                return
            box = bounds(shape, sx, sy, ox, oy)
            if shape.rotation:
                issue(shape, layer, 'rotated_object', unsupported=True)
                continue
            try:
                if shape.has_table:
                    done = table_elements(shape, box, layer)
                elif shape.has_chart:
                    from pptx.enum.chart import XL_CHART_TYPE
                    chart = shape.chart
                    kind = {XL_CHART_TYPE.COLUMN_CLUSTERED:'column', XL_CHART_TYPE.BAR_CLUSTERED:'bar',
                            XL_CHART_TYPE.LINE:'line', XL_CHART_TYPE.PIE:'pie'}.get(chart.chart_type)
                    categories = [c.label for c in chart.plots[0].categories]
                    if not kind or len(categories)>12 or len(chart.series)>4:
                        issue(shape, layer, 'unsupported_chart', unsupported=True)
                        continue
                    data = {'type':kind, 'categories':categories,
                            'series':[{'name':s.name,'values':[float(v) for v in s.values]} for s in chart.series]}
                    emit({'kind':'chart', **box, 'chart':data})
                    issue(shape, layer, 'chart_style_projection')
                    done = True
                elif getattr(shape, 'shape_type', None) == 13:  # PICTURE
                    image = shape.image
                    if image.content_type not in ('image/png','image/jpeg') or len(image.blob)>10*1024*1024 or image_bytes+len(image.blob)>MAX_IMAGE_BYTES:
                        issue(shape, layer, 'unsupported_or_large_picture', unsupported=True)
                        continue
                    image_bytes += len(image.blob)
                    emit({'kind':'image', **box, 'image':{'data':base64.b64encode(image.blob).decode('ascii'),
                         'mime':image.content_type, 'alt':shape.name[:200]}, 'fit':'stretch'})
                    if any(getattr(shape,k) for k in ('crop_left','crop_right','crop_top','crop_bottom')):
                        issue(shape, layer, 'picture_crop_projection')
                    done = True
                else:
                    props = shape._element.find('{%s}spPr' % P)
                    preset = props.find('{%s}prstGeom' % A) if props is not None else None
                    custom = props.find('{%s}custGeom' % A) if props is not None else None
                    drawing = False
                    if shape._element.tag == '{%s}cxnSp' % P and preset is not None and preset.get('prst') == 'line':
                        line = props.find('{%s}ln' % A)
                        border, _, approximate = _paint(line,theme,palette.get('muted','666666'))
                        xfrm = props.find('{%s}xfrm' % A)
                        flip_x = xfrm is not None and xfrm.get('flipH') in ('1','true')
                        flip_y = xfrm is not None and xfrm.get('flipV') in ('1','true')
                        w,h = max(.01,box['w']),max(.01,box['h'])
                        points = [[w if flip_x else 0,h if flip_y else 0],
                                  [0 if flip_x else box['w'],0 if flip_y else box['h']]]
                        ends=[]
                        for tag in ('headEnd','tailEnd'):
                            end=line.find('{%s}%s' % (A,tag)) if line is not None else None
                            kind=end.get('type','none') if end is not None else 'none'
                            ends.append('triangle' if kind in ('triangle','arrow','stealth') else 'none')
                            if kind not in ('none','triangle'):
                                issue(shape,layer,'line_end_projection')
                        emit({'kind':'line',**box,'w':w,'h':h,'points':points,
                              'border':border or '666666','borderWidth':float(line.get('w','12700'))/PT if line is not None else 1,
                              'startArrow':ends[0],'endArrow':ends[1]})
                        if approximate: issue(shape,layer,'line_style_projection')
                        drawing=True
                    elif preset is not None:
                        name = preset.get('prst')
                        if name not in SHAPES:
                            issue(shape, layer, 'unsupported_preset', unsupported=True)
                        else:
                            fill, opacity, approximate = _paint(props, theme, None)
                            line = props.find('{%s}ln' % A)
                            border, _, border_approx = _paint(line, theme, None)
                            style = shape._element.find('{%s}style' % P)
                            inherited_fill = style.find('{%s}fillRef' % A) if style is not None else None
                            inherited_line = style.find('{%s}lnRef' % A) if style is not None else None
                            if (fill is None and props.find('{%s}noFill' % A) is None and
                                    inherited_fill is not None and inherited_fill.get('idx') != '0'):
                                fill, opacity, _ = _reference_paint(inherited_fill,theme,None)
                                issue(shape,layer,'theme_fill_inheritance')
                            if line is None and inherited_line is not None and inherited_line.get('idx') != '0':
                                border, _, _ = _reference_paint(inherited_line,theme,None)
                                issue(shape,layer,'theme_line_inheritance')
                            if fill or border:
                                emit({'kind':'shape', **box, 'shape':name, 'fill':fill, 'opacity':opacity,
                                      'border':border, 'borderWidth':float(line.get('w', '0'))/PT if line is not None else (1 if border else 0),
                                      'radius':min(box['w'],box['h'])*.15 if name=='roundRect' else 0})
                                drawing = True
                            if approximate or border_approx or name not in ('rect','ellipse'):
                                issue(shape, layer, 'preset_or_effect_projection')
                    elif custom is not None:
                        issue(shape, layer, 'custom_geometry', unsupported=True)
                    effects = props.find('{%s}effectLst' % A) if props is not None else None
                    if effects is not None and len(effects):
                        issue(shape, layer, 'shape_effect_projection')
                    body = shape._element.find('{%s}txBody' % P)
                    if body is not None:
                        text_elements(shape.text_frame, box, shape, layer, sx=sx, sy=sy)
                        done = True
                    elif drawing:
                        done = True
                    elif not drawing and preset is None and custom is None:
                        issue(shape, layer, 'unsupported_object', unsupported=True)
                        done = False
                    else:
                        done = drawing
                if done:
                    coverage['projectedObjects'] += 1
            except (AttributeError, IndexError, KeyError, TypeError, ValueError, NotImplementedError):
                issue(shape, layer, 'unsupported_object_format', unsupported=True)

    # The effective background follows Slide -> Layout -> Master. Read XML so
    # merely asking for a preview does not materialize a new background node.
    master = slide.slide_layout.slide_master
    for owner in (master, slide.slide_layout, slide):
        background_node = owner._element.find('{%s}cSld/{%s}bg' % (P,P))
        bg = background_node.find('{%s}bgPr' % P) if background_node is not None else None
        if bg is not None:
            value, _, approximate = _paint(bg, theme, page['background'])
            page['background'] = value or page['background']
            if approximate: warn('배경의 복잡한 채움은 단색으로 근사했습니다.')
        elif background_node is not None:
            bg_ref=background_node.find('{%s}bgRef' % P)
            value,_,_= _reference_paint(bg_ref,theme,page['background'])
            page['background']=value or page['background']
    show_master = slide._element.get('showMasterSp') not in ('0','false')
    layers = [('master', master.shapes), ('layout', slide.slide_layout.shapes)] if show_master else []
    layers.append(('slide',slide.shapes))
    for label, shapes in layers:
        coverage['sourceLayers'].append(label)
        walk(shapes, label)
    coverage['completeObjectProjection'] = not stopped and not coverage['unsupported']
    coverage['fidelity'] = 'approximate' if coverage['approximations'] or coverage['unsupported'] else 'supported_semantic_projection'
    return page
