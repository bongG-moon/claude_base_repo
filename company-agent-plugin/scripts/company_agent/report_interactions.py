"""Optional offline explanations: compare complete scenarios and reveal details."""
from __future__ import annotations

from html import escape


def _text(value, name: str, limit: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f'{name}은 문자열이어야 합니다.')
    value = value.strip()
    if (required and not value) or len(value) > limit:
        raise ValueError(f'{name}은 {"1" if required else "0"}~{limit}자여야 합니다.')
    if any(ord(char) < 32 and char not in '\n\r\t' for char in value):
        raise ValueError(f'{name}에 표시할 수 없는 제어 문자가 있습니다.')
    return value


def _object(value, name: str, fields: set[str]) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f'{name}은 객체여야 합니다.')
    if set(value) - fields:
        raise ValueError(f'{name}에 지원하지 않는 항목이 있습니다.')
    return value


def _texts(value, name: str, *, minimum: int, maximum: int, limit: int) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f'{name}은 {minimum}~{maximum}개의 문자열 목록이어야 합니다.')
    return [_text(item, f'{name}[{i + 1}]', limit) for i, item in enumerate(value)]


def validate(section: dict) -> None:
    """길이 초과를 숨기거나 내용을 자르지 않고, 선택한 설명 블록만 검증한다."""
    if not isinstance(section, dict):
        raise ValueError('설명 섹션은 객체여야 합니다.')
    normalized = {}
    if 'scenarios' in section:
        source = _object(section['scenarios'], 'scenarios', {'title', 'items'})
        items = source.get('items')
        if not isinstance(items, list) or not 2 <= len(items) <= 8:
            raise ValueError('scenarios.items는 2~8개의 사례 목록이어야 합니다.')
        scenario = {'items': []}
        if 'title' in source:
            scenario['title'] = _text(source['title'], 'scenarios.title', 180)
        labels = set()
        for i, raw in enumerate(items, 1):
            name = f'scenarios.items[{i}]'
            item = _object(raw, name, {'label', 'input', 'steps', 'output'})
            label = _text(item.get('label'), name + '.label', 80)
            if label in labels:
                raise ValueError('사례 이름은 서로 구분할 수 있도록 다르게 입력해 주세요.')
            labels.add(label)
            scenario['items'].append({
                'label': label,
                'input': _text(item.get('input'), name + '.input', 2400),
                'steps': _texts(item.get('steps'), name + '.steps', minimum=1, maximum=10, limit=800),
                'output': _text(item.get('output'), name + '.output', 2400),
            })
        normalized['scenarios'] = scenario
    if 'details' in section:
        items = section['details']
        if not isinstance(items, list) or len(items) > 12:
            raise ValueError('details는 최대 12개의 상세 설명 목록이어야 합니다.')
        details = []
        for i, raw in enumerate(items, 1):
            name = f'details[{i}]'
            item = _object(raw, name, {'title', 'body', 'bullets'})
            detail = {'title': _text(item.get('title'), name + '.title', 180)}
            if 'body' in item:
                detail['body'] = _text(item['body'], name + '.body', 6000, required=False)
            if 'bullets' in item:
                detail['bullets'] = _texts(item['bullets'], name + '.bullets', minimum=0, maximum=20, limit=1000)
            if not detail.get('body') and not detail.get('bullets'):
                raise ValueError(f'{name}에는 본문 또는 글머리표 설명이 필요합니다.')
            details.append(detail)
        normalized['details'] = details
    # 실패한 경우 기존 섹션을 반쯤 수정하지 않는다.
    section.update(normalized)


def render(section: dict, index: int) -> str:
    """각 사례의 입력, 처리, 결과를 한 패널로 묶어 선택이 어긋나지 않게 한다."""
    if type(index) is not int or index < 1:
        raise ValueError('설명 섹션 번호는 1 이상의 정수여야 합니다.')
    prepared = {key: section[key] for key in ('scenarios', 'details') if key in section}
    validate(prepared)
    fragments = []
    if 'scenarios' in prepared:
        scenario = prepared['scenarios']
        stem = f'report-scenario-{index}'
        title = scenario.get('title', '같은 기준으로 사례 살펴보기')
        fragments.append(f'<div class="report-scenarios" data-report-scenarios aria-labelledby="{stem}-title">'
                         f'<h3 id="{stem}-title">{escape(title)}</h3>'
                         '<div class="scenario-choices" role="group" aria-label="사례 선택">')
        for i, item in enumerate(scenario['items'], 1):
            fragments.append(f'<button type="button" data-scenario-choice="{i}" '
                             f'aria-controls="{stem}-{i}" aria-pressed="{"true" if i == 1 else "false"}">'
                             f'{escape(item["label"])}</button>')
        fragments.append('</div><div class="scenario-panels">')
        for i, item in enumerate(scenario['items'], 1):
            active = ' is-active' if i == 1 else ''
            fragments.append(f'<div class="scenario-panel{active}" id="{stem}-{i}" '
                             f'role="region" aria-labelledby="{stem}-{i}-label">'
                             f'<h4 id="{stem}-{i}-label">{escape(item["label"])}</h4>'
                             '<div class="scenario-flow">'
                             '<div class="scenario-part scenario-input"><h5><span>01</span> 입력</h5>'
                             f'<p>{escape(item["input"])}</p></div>'
                             '<div class="scenario-part scenario-process"><h5><span>02</span> 처리 과정</h5><ol>')
            fragments.extend(f'<li>{escape(step)}</li>' for step in item['steps'])
            fragments.append('</ol></div><div class="scenario-part scenario-output">'
                             f'<h5><span>03</span> 결과</h5><p>{escape(item["output"])}</p></div></div></div>')
        fragments.append('</div></div>')
    if prepared.get('details'):
        fragments.append('<div class="report-explanation-details">')
        for item in prepared['details']:
            fragments.append(f'<details class="report-detail"><summary>{escape(item["title"])}</summary>'
                             '<div class="report-detail-content">')
            if item.get('body'):
                fragments.append(f'<p>{escape(item["body"])}</p>')
            if item.get('bullets'):
                fragments.append('<ul>' + ''.join(f'<li>{escape(value)}</li>' for value in item['bullets']) + '</ul>')
            fragments.append('</div></details>')
        fragments.append('</div>')
    return ''.join(fragments)


CSS = r'''
.report-scenarios,.report-explanation-details{min-width:0;margin-top:28px;grid-column:1/-1}
.report-scenarios>h3{font-size:clamp(20px,2.2vw,26px);line-height:1.4;letter-spacing:-.035em;margin:0 0 18px}
.scenario-choices{display:none;flex-wrap:wrap;gap:8px;margin-bottom:18px}
.report-scenarios.is-ready .scenario-choices{display:flex}
.scenario-choices button{font:inherit;line-height:1.5;min-height:44px;padding:10px 16px;border:1px solid var(--line);border-radius:8px;background:var(--paper);color:var(--ink);cursor:pointer;max-width:100%;overflow-wrap:anywhere;text-align:left}
.scenario-choices button[aria-pressed=true]{background:var(--tint);border-color:var(--accent);box-shadow:inset 0 -2px var(--accent);font-weight:700}
.scenario-choices button:focus-visible,.report-detail>summary:focus-visible{outline:3px solid var(--accent);outline-offset:3px}
.scenario-panel{border-top:2px solid var(--accent);padding-top:20px;margin-top:22px;min-width:0}
.scenario-panel>h4{margin:0 0 18px;font-size:18px;line-height:1.5}
.report-scenarios.is-ready .scenario-panel:not(.is-active){display:none}
.scenario-flow{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr) minmax(0,1fr);gap:0}
.scenario-part{min-width:0;padding:4px 24px 8px;line-height:1.8;word-break:keep-all;overflow-wrap:anywhere}
.scenario-part:first-child{padding-left:0}.scenario-part:last-child{padding-right:0}
.scenario-part+.scenario-part{border-left:1px solid var(--line)}
.scenario-part h5{margin:0 0 12px;font-size:14px;line-height:1.5;color:var(--muted);font-weight:650;letter-spacing:0}
.scenario-part h5 span{font-variant-numeric:tabular-nums;color:var(--accent);margin-right:8px}
.scenario-part p,.report-detail-content p{margin:0;white-space:pre-line}
.scenario-part ol{margin:0;padding-left:22px}.scenario-part li+li{margin-top:10px}
.scenario-output p{font-weight:600}
.report-detail{border-top:1px solid var(--line);margin:0;padding:0}
.report-detail:last-child{border-bottom:1px solid var(--line)}
.report-detail>summary{cursor:pointer;padding:18px 4px;font-weight:650;line-height:1.6;overflow-wrap:anywhere}
.report-detail-content{padding:0 4px 22px;color:var(--muted);line-height:1.85;word-break:keep-all;overflow-wrap:anywhere}
.report-detail-content ul{padding-left:22px;margin:14px 0 0}.report-detail-content li+li{margin-top:8px}
@keyframes report-scenario-enter{from{opacity:.4;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}
body[data-motion=subtle] .report-scenarios.is-ready .scenario-panel.is-active{animation:report-scenario-enter 180ms ease-out}
@media(max-width:760px){.scenario-flow{grid-template-columns:minmax(0,1fr)}.scenario-part,.scenario-part:first-child,.scenario-part:last-child{padding:16px 0}.scenario-part+.scenario-part{border-left:0;border-top:1px solid var(--line)}}
@media(prefers-reduced-motion:reduce){.report-scenarios .scenario-panel{animation:none!important}}
@media print{.report-scenarios .scenario-choices{display:none!important}.report-scenarios.is-ready .scenario-panel{display:block!important;animation:none!important;break-inside:avoid}.report-detail>.report-detail-content{display:block!important}.report-detail::details-content{content-visibility:visible!important;display:block!important}.report-detail>summary{list-style:none}.report-detail{break-inside:avoid}}
'''


JS = r'''
(() => {
  'use strict';
  // 자료는 이미 HTML에 있다. 선택은 네트워크나 저장 없이 표시만 바꾼다.
  document.querySelectorAll('[data-report-scenarios]').forEach(group => {
    if (group.classList.contains('is-ready')) return;
    const choices = Array.from(group.querySelectorAll('[data-scenario-choice]'));
    const panels = Array.from(group.querySelectorAll('.scenario-panel'));
    const select = button => {
      const target = panels.find(panel => panel.id === button.getAttribute('aria-controls'));
      if (!target) return;
      choices.forEach(choice => choice.setAttribute('aria-pressed', String(choice === button)));
      panels.forEach(panel => panel.classList.toggle('is-active', panel === target));
    };
    group.addEventListener('click', event => {
      const button = event.target.closest('[data-scenario-choice]');
      if (choices.includes(button)) select(button);
    });
    if (choices.length && choices.length === panels.length) {
      select(choices[0]);
      group.classList.add('is-ready');
    }
  });
  // 인쇄에는 접혀 있던 근거도 포함하고, 인쇄가 끝나면 사용자 상태를 돌려놓는다.
  let closedBeforePrint = null;
  window.addEventListener('beforeprint', () => {
    if (closedBeforePrint !== null) return;
    closedBeforePrint = Array.from(document.querySelectorAll('.report-detail:not([open])'));
    closedBeforePrint.forEach(detail => { detail.open = true; });
  });
  window.addEventListener('afterprint', () => {
    if (closedBeforePrint === null) return;
    closedBeforePrint.forEach(detail => { detail.open = false; });
    closedBeforePrint = null;
  });
})();
'''
