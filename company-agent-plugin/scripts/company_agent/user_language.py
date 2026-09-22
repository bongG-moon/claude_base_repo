"""Korean defaults and bounded question repair; preserve executable identifiers."""

import re


KOREAN_DEFAULT_RULE = (
    "기본 사용자 안내는 한국어입니다. 질문 제목·선택지·설명·추천 이유·승인 요청·중간 피드백·검토 질문·진행 안내·최종 결과·문서 본문을 쉬운 한국어로 작성하세요. "
    "AskUserQuestion의 question·header·label·description은 짧은 항목도 한국어로 쓰고 '(Recommended)'는 '(추천)'으로 표시하세요. "
    "영어 입력자료·스킬·도구 출력은 언어 변경 요청이 아닙니다. 사용자가 명시한 다른 언어는 요청한 범위에만 적용하고 모든 작업자에게 전달하세요. "
    "파일명·경로·명령어·API/JSON 키·코드·모델명·원문 인용은 보존하고 설명만 번역하세요. 내부 상태를 나열하지 말고 실제 실패·제한은 한국어로 알리세요. "
)


# These are whole display phrases, not a word-by-word translator. In particular,
# never translate tokens inside a command, skill name, filename, or free prose.
_DISPLAY_PHRASES = {
    'yes': '예', 'no': '아니요', 'approve': '승인', 'reject': '거절',
    'cancel': '취소', 'continue': '계속', 'proceed': '진행', 'skip': '건너뛰기',
    'retry': '다시 시도', 'other': '기타', 'recommended': '추천',
    'yes, proceed': '예, 진행', 'yes, continue': '예, 계속', 'no, cancel': '아니요, 취소',
    'apply': '적용', 'save': '저장', 'edit': '수정', 'review': '검토',
    'later': '나중에', 'not now': '지금은 안 함', 'go back': '돌아가기',
    'allow once': '이번만 허용', 'always allow': '항상 허용', 'deny': '거부',
    'custom': '직접 지정', 'default': '기본값', 'automatic': '자동', 'auto': '자동',
    'manual': '수동', 'manual setup': '수동 설정', 'automatic setup': '자동 설정',
    'use existing': '기존 항목 사용', 'create new': '새로 만들기',
    'new project': '새 프로젝트', 'existing project': '기존 프로젝트',
    'full': '전체', 'summary': '요약', 'detailed': '자세히', 'concise': '간결하게',
    'brief': '간략하게', 'short': '짧게', 'long': '길게',
    'feedback': '피드백', 'scope': '범위', 'approach': '접근 방식',
    'format': '형식', 'output': '결과물', 'output format': '출력 형식', 'language': '언어',
    'style': '스타일', 'design': '디자인', 'priority': '우선순위',
    'plan': '계획', 'choice': '선택', 'options': '선택지', 'mode': '방식',
    'confirmation': '확인', 'permission': '권한', 'permissions': '권한',
    'next step': '다음 단계',
    'personal': '개인', 'project': '프로젝트', 'this project': '이 프로젝트',
    'all projects': '모든 프로젝트', 'personal only': '개인 전용',
    'personal memory': '개인 기억', 'team memory': '팀 기억',
    'company': '회사', 'team': '팀', 'shared': '공용', 'company shared': '회사 공통',
    'global': '전역', 'local': '로컬', 'user': '사용자', 'workspace': '작업 공간',
    'user scope': '사용자 범위', 'project scope': '프로젝트 범위',
    'accept': '수락', 'decline': '거절', 'confirm': '확인',
    'back': '이전', 'next': '다음', 'done': '완료', 'finish': '완료',
    'keep': '유지', 'replace': '교체', 'overwrite': '덮어쓰기',
    'delete': '삭제', 'remove': '제거', 'delete permanently': '영구 삭제',
    'move to trash': '휴지통으로 이동',
    'continue with this approach': '이 방식으로 계속 진행',
    'use the default settings': '기본 설정 사용',
    'keep the current settings': '현재 설정 유지',
}
_TOOL_NAMES = frozenset({
    'Read', 'Write', 'Edit', 'Bash', 'PowerShell', 'Glob', 'Grep', 'Skill',
    'Agent', 'Task', 'AskUserQuestion', 'WebFetch', 'WebSearch', 'NotebookEdit',
})
_KNOWN_NAMES = re.compile(
    r'\b(?:Claude Code|Visual Studio Code|Visual Studio|Microsoft Word|Microsoft Excel|'
    r'Microsoft PowerPoint|Google Docs|Google Sheets|Google Slides|OpenAI API|Noto Sans KR|'
    r'Python|React|Claude|Codex|ChatGPT|OpenAI|Anthropic|Sonnet|Opus|Haiku)\b')
_PROTECTED = re.compile(
    r'`[^`]*`|https?://\S+|[A-Za-z]:[\\/][^\n]*|'
    r'(?<!\w)(?:[./~\\][\w./~\\-]+|[\w-]+(?:[-./\\_:][\w.-]+)+)'
    r'(?:\s+\((?:project|personal|company|user|plugin|team|global|local)\))?|'
    r'\b[A-Z][a-z]+(?:[A-Z][A-Za-z0-9]*)+\b|\b[A-Z][A-Z0-9]+\b')
_UI_WORDS = frozenset(_DISPLAY_PHRASES) | frozenset({
    'choose', 'select', 'which', 'what', 'how', 'would', 'should', 'prefer',
    'please', 'setup', 'settings', 'advanced', 'customize', 'option', 'proceed',
    'use', 'keep', 'create', 'build', 'change', 'faster', 'slower', 'smaller',
    'larger', 'safer', 'safest', 'balanced', 'minimal', 'conservative',
})
_RECOMMENDED_SUFFIX = re.compile(r'^(.*?)\s*\(recommended\)\s*$', re.I | re.S)
_LITERAL_PATH = re.compile(r'^(?:[A-Za-z]:[\\/]|[/\\]|\.{1,2}[\\/]|~[\\/])')


def _display_translation(value):
    if not isinstance(value, str):
        return value
    core = value.strip()
    if _LITERAL_PATH.match(core):
        return value  # Parentheses may be part of a real path, not an annotation.
    suffix = _RECOMMENDED_SUFFIX.fullmatch(core)
    if suffix and suffix[1].strip():
        return _display_translation(suffix[1].rstrip()) + ' (추천)'
    if core in _TOOL_NAMES:
        return value
    translated = _DISPLAY_PHRASES.get(core.casefold())
    return value.replace(core, translated, 1) if translated else value


def _english_prose(value):
    """Detect short UI prose too, while being conservative about identifiers."""
    if not isinstance(value, str):
        return False
    if _LITERAL_PATH.match(value.strip()):
        return False
    remainder = _PROTECTED.sub(' ', _KNOWN_NAMES.sub(' ', value[:4000]))
    words = [word for word in re.findall(r'[A-Za-z]{2,}', remainder)
             if word not in _TOOL_NAMES]
    return len(words) >= 2 or any(word.casefold() in _UI_WORDS for word in words)


def _requested_ui_language(text):
    # A language before "report/email" must not extend to a later UI clause.
    ui_ko = r'(?:질문|선택지|옵션|대화|답변|안내|피드백|메뉴|UI)'
    languages_ko = r'(?:한국어|한글|영어|일본어|중국어|독일어|프랑스어|스페인어)'
    ui_en = r'(?:questions?|choices?|options?|conversation|chat|responses?|replies|feedback|menus?|UI)'
    languages_en = r'(?:Korean|English|Japanese|Chinese|German|French|Spanish)'
    patterns = (
        rf'{ui_ko}(?:[은는을를와과도·,\s]|{ui_ko}|모두|항상|계속|전부|반드시|기본적으로|만){{0,30}}(?P<lang>{languages_ko})(?:으?로)',
        rf'(?P<lang>{languages_ko})(?:으?로)\s*(?:(?:모든|모두|항상|계속|만)\s*)?{ui_ko}',
        rf'\b(?:respond|reply|ask|converse|speak)\b(?:\s+(?:me|us|all|the|your|questions))*\s+(?:in\s+)?(?P<lang>{languages_en})\b',
        rf'\b{ui_en}(?:\s+(?:and|all|only|always|the|your|should|must|be|are)|\s+{ui_en})*\s+in\s+(?P<lang>{languages_en})\b',
        rf'\b(?:use|speak)\s+(?P<lang>{languages_en})\s+(?:for|in)\s+(?:(?:all|the|your)\s+)*{ui_en}\b',
    )
    choices = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            korean = match['lang'].casefold() in {'한국어', '한글', 'korean'}
            negated = (re.match(r'\s*(?:하지\s*마|하지\s*말|쓰지\s*마)', text[match.end():])
                       or re.search(r"\b(?:don't|do not|never)\s*$", text[:match.start()], re.I))
            if negated:
                # Not-English is not an opt-out; explicitly not-Korean is.
                # Do not invent its replacement language or force Korean UI.
                if korean:
                    choices.append((match.start(), True))
                continue
            choices.append((match.start(), not korean))
    return max(choices)[1] if choices else None


def prepare_questions(root, payload):
    """Remember only a scoped language choice, never the user's prompt."""
    from .state import _locked_session
    from .paths import atomic_write_json
    session = payload.get('session_id')
    if not session:
        return
    text = str(payload.get('prompt', payload.get('user_prompt', '')))[:12000]
    other = _requested_ui_language(text)
    with _locked_session(session, root) as (state, path):
        turn = state.get('turnId')
        previous = state.get('questionLanguage')
        if turn and isinstance(previous, dict) and previous.get('turn') == turn:
            return  # A duplicate native prompt must not replenish the repair.
        state['questionLanguage'] = {'turn': turn, 'otherRequested': bool(other), 'repairUsed': False}
        atomic_write_json(path, state)


def question_preflight(root, payload):
    """Translate fixed UI phrases; request free-prose repair at most once per turn.

    Leave identifiers/code and explicit language choices intact. This controls
    model-authored AskUserQuestion only, not Claude's own native UI/surveys.
    """
    from .state import _locked_session
    from .paths import atomic_write_json
    if payload.get('tool_name') != 'AskUserQuestion' or not payload.get('session_id'):
        return {}
    inputs = payload.get('tool_input')
    if not isinstance(inputs, dict) or inputs.get('answers'):
        return {}
    questions = inputs.get('questions')
    if not isinstance(questions, list):
        return {}
    changed = False
    needs_repair = False
    updated_questions = []
    for item in questions:
        if not isinstance(item, dict):
            updated_questions.append(item)
            continue
        updated = dict(item)
        # The question remains the native answer-map key. Let the model repair
        # its free prose; translate only known display fields before any answer.
        needs_repair |= _english_prose(item.get('question'))
        if 'header' in item:
            updated['header'] = _display_translation(item['header'])
            needs_repair |= _english_prose(updated['header'])
        options = item.get('options')
        if isinstance(options, list):
            updated_options = []
            for option in options:
                if not isinstance(option, dict):
                    updated_options.append(option)
                    continue
                translated = dict(option)
                for key in ('label', 'description'):
                    if key in option:
                        translated[key] = _display_translation(option[key])
                        needs_repair |= _english_prose(translated[key])
                updated_options.append(translated)
            labels = [option.get('label') for option in updated_options
                      if isinstance(option, dict) and isinstance(option.get('label'), str)]
            # Collapsing distinct labels would make the answer ambiguous. Keep
            # the complete option group untouched and request model correction.
            if len(labels) != len(set(labels)) and updated_options != options:
                needs_repair = True
            else:
                updated['options'] = updated_options
        changed |= updated != item
        updated_questions.append(updated)
    if not changed and not needs_repair:
        return {}
    with _locked_session(payload['session_id'], root) as (state, path):
        language = state.get('questionLanguage', {})
        if not isinstance(language, dict) or language.get('otherRequested'):
            return {}
        if needs_repair and not language.get('repairUsed'):
            language['repairUsed'] = True
            state['questionLanguage'] = language
            atomic_write_json(path, state)
            return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                    'permissionDecisionReason': '질문·짧은 제목·선택지·설명을 한국어로 바꿔 다시 질문하세요. (Recommended)는 (추천)으로 쓰세요. 파일명·경로·도구명·코드·고유 이름과 선택 의미를 보존하고 서로 다른 선택지 이름을 구별하세요. 승인 거절이 아닌 표시 언어 보정이며 이 요청은 이번 턴에 한 번만 합니다.'}}
    if changed:
        return {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                'updatedInput': {**inputs, 'questions': updated_questions}}}
    return {}
