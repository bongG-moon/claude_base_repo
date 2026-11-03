"""One bounded advisory pass over the already prepared slide scene."""
from __future__ import annotations

from .ppt_text import estimate_lines


def _diamond_label_crosses(shape, text, size, font):
    """Estimate each ink line against a diamond, without rewriting the scene.

    A text box may contain substantial blank padding. Only its estimated ink
    is relevant, including horizontal/vertical alignment and explicit breaks.
    Font rendering remains a separate visual check; two points of tolerance
    avoid treating small font-metric differences as confirmed clipping.
    """
    line_widths=[]
    for paragraph in text['text'].split('\n'):
        count=1 if text.get('wrap') is False else estimate_lines(paragraph,text['w'],size,font)
        width=sum(1 if ord(c)>255 else .55 for c in paragraph)*size
        # Wrapped lines can occupy the available width. Do not infer where a
        # renderer has broken Korean words from the original string alone.
        line_widths.extend([text['w']]*count if count>1 else [min(text['w'],width)
                           if text.get('wrap') is not False else width])
    line_height=size*text.get('lineSpacing',1.15)
    height=len(line_widths)*line_height
    spare=max(0,text['h']-height)
    y=text['y']+(spare/2 if text.get('verticalAlign')=='middle' else
                 spare if text.get('verticalAlign')=='bottom' else 0)
    cx,cy=shape['x']+shape['w']/2,shape['y']+shape['h']/2
    for width in line_widths:
        left=text['x']+(max(0,text['w']-width)/2 if text.get('align')=='center' else
                        max(0,text['w']-width) if text.get('align')=='right' else 0)
        if width:
            # The diamond's narrowest extent over this line determines the
            # usable horizontal interval. This catches top-aligned labels too.
            dy=max(abs(y-cy),abs(y+line_height-cy))
            half=shape['w']/2*(1-dy/(shape['h']/2))
            if left<cx-half-2 or left+width>cx+half+2:
                return True
        y+=line_height
    return False


def inspect_plan(plan):
    issues=[]
    checked_pairs=0
    arrow_checks=0
    diamond_checks=0
    truncated=False
    for page_number,page in enumerate(plan['pages'],1):
        # Only inspect explicit arrowed connectors. Decorative lines have no
        # implied relationship. A bounding-box proximity test is advisory, not a
        # claim that Office has actually bound an endpoint to a connection site.
        shapes=[e for e in page['elements'] if e['kind']=='shape' and e['w']>8 and e['h']>8]
        for index,e in enumerate(page['elements']):
            if e['kind']!='line' or not any(e.get(k) not in (None, 'none') for k in ('startArrow','endArrow')):
                continue
            points=e.get('points',[])
            if len(points)<2 or not shapes:
                continue
            missing=[]
            for name,point in (('start',points[0]),('end',points[-1])):
                x,y=e['x']+point[0],e['y']+point[1]
                matched=False
                for shape in shapes:
                    arrow_checks+=1
                    if arrow_checks>5000:
                        truncated=True
                        break
                    left,top,right,bottom=shape['x'],shape['y'],shape['x']+shape['w'],shape['y']+shape['h']
                    if left-6<=x<=right+6 and top-6<=y<=bottom+6:
                        distance=min(abs(x-left),abs(x-right),abs(y-top),abs(y-bottom))
                        if distance<=6:
                            matched=True
                            break
                if truncated:break
                if not matched:missing.append(name)
            if truncated:break
            if missing:
                issues.append({'slide':page_number,'element':index,'code':'possible_unconnected_arrow',
                               'ends':missing,'message':'화살표 끝이 도형 경계와 떨어져 있을 수 있습니다. 실제 초안에서 연결 관계를 확인해 주세요.'})
            if len(issues)>=20:
                return {'status':'advisories','issues':issues[:20],'truncated':True,
                        'visualReview':'not_performed','automaticTextShrinking':False}
        if truncated:break
        # A centered text box can extend into the notch of a chevron even when
        # its rectangular bounding box fits. Estimate the ink interval rather
        # than treating all box padding as glyphs; visual review still decides.
        chevrons={e.get('group'):e for e in page['elements']
                  if e['kind']=='shape' and e.get('shape')=='chevron' and e.get('group')}
        diamonds={}
        for shape_index,shape in enumerate(page['elements']):
            if shape['kind']=='shape' and shape.get('shape')=='diamond' and shape.get('group'):
                diamonds.setdefault(shape['group'],[]).append((shape_index,shape))
        small_text=[]
        texts=[]
        for index,e in enumerate(page['elements']):
            if e['kind']!='text' or not e.get('text','').strip():
                continue
            size=max([r['size'] for r in e.get('runs',[])] or [e['size']])
            if size < 11 and len(e['text'].strip()) >= 8:
                small_text.append(index)
            font=e.get('font') or plan['font']
            # Browser-imported text is already split into measured lines and is
            # emitted without wrapping. Estimating extra wraps here produces
            # false warnings on nearly every Korean title.
            lines = len(e['text'].split('\n')) if e.get('wrap') is False else estimate_lines(e['text'],e['w'],size,font)
            height=lines*size*e.get('lineSpacing',1.15)
            if height>e['h']*1.3+3:
                issues.append({'slide':page_number,'element':index,'code':'estimated_text_overflow',
                               'message':'글자량과 배치 공간을 확인해 주세요. 자동 축소나 내용 생략은 하지 않았습니다.'})
            if len(issues)>=20:
                return {'status':'advisories','issues':issues[:20],'truncated':True,
                        'visualReview':'not_performed','automaticTextShrinking':False}
            # Compare actual approximate ink, not large mostly empty text boxes.
            width=min(e['w'],max((sum(1 if ord(c)>255 else .55 for c in line)*size for line in e['text'].split('\n')),default=0))
            shape=chevrons.get(e.get('group'))
            if shape:
                left=e['x'] + (max(0,e['w']-width)/2 if e.get('align')=='center' else
                               max(0,e['w']-width) if e.get('align')=='right' else 0)
                center_y=e['y']+e['h']/2
                ratio=max(0,min(1,(center_y-shape['y'])/shape['h']))
                inset=.28*shape['w']*(1-abs(2*ratio-1))
                safe_left=shape['x']+inset
                safe_right=shape['x']+.72*shape['w']+inset
                if left < safe_left-2 or left+width > safe_right+2:
                    issues.append({'slide':page_number,'element':index,'code':'possible_chevron_text_clipping',
                                   'message':'화살표 도형의 오목한 부분이나 끝에 글자가 걸칠 수 있습니다. 실제 초안에서 글자와 배경을 확인해 주세요.'})
            # A group can contain more than one node. Inspect only a unique
            # diamond containing this label's centre, never an external edge
            # label or the last arbitrary shape stored under the group name.
            candidates=[]
            if not e.get('allowOverlap'):
                for shape_index,shape in diamonds.get(e.get('group'),[]):
                    diamond_checks+=1
                    if diamond_checks>5000:
                        truncated=True
                        break
                    cx,cy=e['x']+e['w']/2,e['y']+e['h']/2
                    if shape['x']<=cx<=shape['x']+shape['w'] and shape['y']<=cy<=shape['y']+shape['h']:
                        candidates.append((shape_index,shape))
            if truncated:break
            if len(candidates)==1:
                shape_index,shape=candidates[0]
                if _diamond_label_crosses(shape,e,size,font):
                    issues.append({'slide':page_number,'element':index,'shapeElement':shape_index,
                                   'code':'possible_diamond_text_clipping',
                                   'message':'판단 도형의 사선에 글자가 걸칠 수 있습니다. 글자를 도형 중앙에 두고 의미 단위 줄바꿈이나 도형 크기를 조정한 뒤 해당 장을 확인해 주세요.'})
            if not e.get('allowOverlap'):
                texts.append((index,e['x'],e['y'],width,min(e['h'],height)))
            if len(issues)>=20:
                return {'status':'advisories','issues':issues[:20],'truncated':True,'visualReview':'not_performed','automaticTextShrinking':False}
        if truncated:break
        if small_text:
            issues.append({'slide':page_number,'elements':small_text[:8],'code':'small_annotation_text',
                           'message':'11pt보다 작은 설명 또는 주석이 있습니다. 화면에서 읽기 쉬운지 확인해 주세요.'})
        if len(issues)>=20:
            return {'status':'advisories','issues':issues[:20],'truncated':True,'visualReview':'not_performed','automaticTextShrinking':False}
        for position,a in enumerate(texts):
            for b in texts[position+1:]:
                checked_pairs+=1
                if checked_pairs>5000:
                    truncated=True
                    break
                dx=max(0,min(a[1]+a[3],b[1]+b[3])-max(a[1],b[1]))
                dy=max(0,min(a[2]+a[4],b[2]+b[4])-max(a[2],b[2]))
                if dx*dy>max(4,min(a[3]*a[4],b[3]*b[4])*.2):
                    issues.append({'slide':page_number,'elements':[a[0],b[0]],'code':'possible_text_overlap',
                                   'message':'서로 다른 글자 영역이 겹칠 수 있습니다. 의도한 배치인지 초안에서 확인해 주세요.'})
                if len(issues)>=20:
                    return {'status':'advisories','issues':issues[:20],'truncated':True,'visualReview':'not_performed','automaticTextShrinking':False}
            if truncated:break
        if truncated:break
    return {'status':'advisories' if issues else 'partial' if truncated else 'checked','issues':issues[:20],
            'truncated':truncated,'visualReview':'not_performed','automaticTextShrinking':False}


def template_summary(coverage):
    """The complete preview stays in HTML; the model receives a small receipt."""
    import json
    result={'sourcePages':len(coverage),'slides':[],'omittedSlides':0,
            'fullCoverageInPreview':True,'visualReview':'not_performed'}
    for page in coverage:
        row={key:page[key] for key in ('slide','totalObjects','projectedObjects','groups','completeObjectProjection','fidelity') if key in page}
        for field in ('unsupported','approximations'):
            reasons=list(dict.fromkeys(item.get('reason','미확인') for item in page.get(field,[])))
            row[field+'Reasons']=reasons[:8]
            if len(reasons)>8:row[field+'ReasonsOmitted']=len(reasons)-8
        if len(result['slides'])>=12 or len(json.dumps(result,ensure_ascii=False))+len(json.dumps(row,ensure_ascii=False))>6000:
            result['omittedSlides']+=1
        else:result['slides'].append(row)
    return result
