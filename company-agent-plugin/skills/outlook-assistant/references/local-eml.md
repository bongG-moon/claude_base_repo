# Selected local mail files

Use runtime `metadataCommand` with `business eml-read --file "<absolute-file.eml>"`.
This stateless reader does not connect Outlook, import messages, extract files or
follow URLs. Use selected filenames directly; discover missing paths with Glob.
Do not use shell variables, command chains, discovery scripts or a new parser.

MIME 헤더와 문자 인코딩은 이 도우미가 처리합니다. 고정 줄 번호나 임의 Base64
해독 코드로 본문을 추출하지 않으며 반환된 범위와 잘림 정보를 사용합니다.

It returns bounded plain-text bodies and bounded TXT attachments; HTML, embedded
mail, unsupported and recognizably protected parts are excluded. Inspect
`body_read`, each attachment status, warnings and partial reasons. Unsupported
does not mean DRM-blocked. Use only approved AI-processing sources; output can
remain in Claude's conversation. Never replace a protected rejection with another
app/parser. Describe the result as local mail-file reading, not mailbox search.
