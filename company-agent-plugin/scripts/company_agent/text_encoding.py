"""Windows text contract; never mutate source encodings or global settings."""

WINDOWS_TEXT_RULE = (
    '한글 입출력은 UTF-8입니다. 등록된 cliCommand를 그대로 쓰세요. '
    '별도 Python이 꼭 필요하면 -X utf8로 시작하고 텍스트 파일 encoding을 명시하세요. '
    'PowerShell 텍스트 읽기는 -Encoding UTF8, 새 UTF-8 파일은 BOM 없는 UTF8Encoding(false)를 쓰세요. '
    '기존 CP949/UTF-16 파일은 확인된 원래 인코딩으로 읽고 원본을 덮어쓰거나 errors=ignore/replace로 손실시키지 마세요. '
    '콘솔 깨짐과 원본 손상을 구분하세요. 표시 오류만으로 원래 업무를 재실행하지 말고 기존 결과를 올바른 인코딩으로 확인하세요. '
    '특히 메일 발송·파일 이동·산출물 생성은 실행 결과를 먼저 확인해 중복 실행을 막으세요.'
)
