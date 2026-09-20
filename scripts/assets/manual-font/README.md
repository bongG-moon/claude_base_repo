# Noto Sans KR — offline guide subset

The guide embeds this WOFF directly. Opening one HTML file does not contact
Google Fonts or depend on an employee's installed fonts. `OFL.txt` is the upstream
license, also retained in the WOFF name table and each generated HTML header.
`manifest.json` records the source hash/version and included characters.

No font is installed in Windows. The subset preserves weights 400–700 and the
guide's characters; it is not a general-purpose Korean font package. The manual
builder rejects newly added characters that are missing from it.

To refresh, use an approved Noto Sans KR TTF on the build PC:

```powershell
python -X utf8 scripts/build-manual-font.py --font "<approved Noto Sans KR TTF>"
node scripts/build-manuals.mjs --modules "<approved node_modules>"
python -X utf8 scripts/build-first-work.py
```

The full source font stays on the build PC. Employees receive the embedded subset
and its license, with no new dependencies, downloads, or model calls.
