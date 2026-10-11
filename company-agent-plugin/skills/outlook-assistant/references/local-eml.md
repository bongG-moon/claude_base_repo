# Selected local mail files

Use runtime `metadataCommand` with `business eml-read --file "<absolute-file.eml>"`.
This stateless reader does not connect Outlook, import messages, extract files or
follow URLs. Use selected filenames directly; discover missing paths with Glob.
Do not use shell variables, command chains, discovery scripts or a new parser.

It returns bounded plain-text bodies and bounded TXT attachments; HTML, embedded
mail, unsupported and recognizably protected parts are excluded. Inspect
`body_read`, each attachment status, warnings and partial reasons. Unsupported
does not mean DRM-blocked. Use only approved AI-processing sources; output can
remain in Claude's conversation. Never replace a protected rejection with another
app/parser. Describe the result as local mail-file reading, not mailbox search.
