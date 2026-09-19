"""Korean defaults and bounded question repair; preserve executable identifiers."""

KOREAN_DEFAULT_RULE = (
    "기본 사용자 안내는 한국어입니다. 질문 제목·선택지·설명·추천 이유·승인 요청·중간 피드백·검토 질문·진행 안내·최종 결과·문서 본문을 쉬운 한국어로 작성하세요. "
    "영어 입력자료·스킬·도구 출력은 언어 변경 요청이 아닙니다. 사용자가 명시한 다른 언어는 요청한 범위에만 적용하고 모든 작업자에게 전달하세요. "
    "파일명·경로·명령어·API/JSON 키·코드·모델명·원문 인용은 보존하고 설명만 번역하세요. 내부 상태를 나열하지 말고 실제 실패·제한은 한국어로 알리세요. "
)


def prepare_questions(root, payload):
    """Remember only a scoped language choice, never the user's prompt."""
    import re
    from .state import _locked_session
    from .paths import atomic_write_json
    session = payload.get('session_id')
    if not session:
        return
    text = str(payload.get('prompt', payload.get('user_prompt', '')))[:12000]
    # An English source/deliverable alone does not switch the conversation UI.
    other = bool(re.search(r'(?:질문|대화|답변|안내|피드백).{0,12}(?:영어|일본어|중국어|독일어|프랑스어|스페인어)로|(?:영어|일본어|중국어|독일어|프랑스어|스페인어)로.{0,12}(?:질문|대화|답변|안내|피드백)|\b(?:respond|reply|ask|converse)\b.{0,25}\bin (?:English|Japanese|Chinese|German|French|Spanish)\b', text, re.I))
    korean = bool(re.search(r'(?:질문|대화|답변|안내|피드백).{0,12}(?:한국어|한글)로|(?:한국어|한글)로.{0,12}(?:질문|대화|답변|안내|피드백)|\b(?:respond|reply|ask|converse)\b.{0,25}\bin Korean\b', text, re.I))
    with _locked_session(session, root) as (state, path):
        turn = state.get('turnId')
        previous = state.get('questionLanguage')
        if turn and isinstance(previous, dict) and previous.get('turn') == turn:
            return  # A duplicate native prompt must not replenish the repair.
        state['questionLanguage'] = {'turn': turn, 'otherRequested': other and not korean, 'repairUsed': False}
        atomic_write_json(path, state)


def question_preflight(root, payload):
    """Repair a clearly English question once per turn, without a translation API.

    Leave identifiers/code and explicit language choices intact. This controls
    model-authored AskUserQuestion only, not Claude's own native UI/surveys.
    """
    import re
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
    strings = []
    for item in questions[:4]:
        if not isinstance(item, dict):
            continue
        strings.extend([item.get('question'), item.get('header')])
        options = item.get('options')
        for option in (options[:10] if isinstance(options, list) else []):
            if isinstance(option, dict):
                strings.extend([option.get('label'), option.get('description')])
    def english(value):
        if not isinstance(value, str) or re.search('[가-힣ぁ-んァ-ン一-龥]', value):
            return False
        value = re.sub(r'`[^`]*`|https?://\S+|[A-Za-z]:[\\/][^\n]*', '', value[:4000])
        return len(re.findall(r'\b[A-Za-z]{2,}\b', value)) >= 4 or value.strip().casefold() in {
            'approve', 'cancel', 'continue', 'feedback', 'recommended', 'yes', 'no'}
    if not any(english(value) for value in strings):
        return {}
    with _locked_session(payload['session_id'], root) as (state, path):
        language = state.get('questionLanguage', {})
        if not isinstance(language, dict) or language.get('otherRequested') or language.get('repairUsed'):
            return {}
        language['repairUsed'] = True
        state['questionLanguage'] = language
        atomic_write_json(path, state)
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
            'permissionDecisionReason': '질문·선택지·설명만 한국어로 바꿔 다시 질문하세요. 파일명·코드·고유 이름과 선택 의미는 유지하세요. 승인 거절이 아닌 표시 언어 보정입니다.'}}
