"""Windows text contract; never mutate source encodings or global settings."""

SCRIPT_EXECUTION_RULE = (
    'Write 실패는 응답과 정확한 절대경로를 먼저 확인하고 인코딩 탓으로 단정하지 마세요. '
    '별도 코드는 UTF-8 .py/.ps1 파일로 작성·Read 확인 후 Python -X utf8 또는 PowerShell -File로 실행합니다. '
    'Windows PowerShell 5.1의 한글 .ps1은 UTF-8 BOM이 필요합니다. '
    '긴 코드·정규식을 Bash→PowerShell -Command→Python -c로 중첩하거나 이스케이프하지 마세요. '
    're.error/PatternError는 패턴·이스케이프를 확인하고 문자열 검색은 re.escape를 씁니다. '
    '실제 거절은 다른 도구로 재시도하지 않으며 재실행 전 기존 결과를 확인합니다. '
)

WINDOWS_TEXT_RULE = (
    '한글 입출력은 UTF-8입니다. 등록된 cliCommand를 그대로 쓰세요. '
    '별도 Python이 꼭 필요하면 -X utf8로 시작하고 텍스트 파일 encoding을 명시하세요. '
    'PowerShell 텍스트 읽기는 -Encoding UTF8, 새 일반 텍스트는 BOM 없는 UTF8Encoding(false)를 쓰세요(.ps1 예외는 아래). '
    '기존 CP949/UTF-16 파일은 확인된 원래 인코딩으로 읽고 원본을 덮어쓰거나 errors=ignore/replace로 손실시키지 마세요. '
    '콘솔 깨짐과 원본 손상을 구분하세요. 표시 오류만으로 원래 업무를 재실행하지 말고 기존 결과를 올바른 인코딩으로 확인하세요. '
    '특히 메일 발송·파일 이동·산출물 생성은 실행 결과를 먼저 확인해 중복 실행을 막으세요. '
    + SCRIPT_EXECUTION_RULE
)
