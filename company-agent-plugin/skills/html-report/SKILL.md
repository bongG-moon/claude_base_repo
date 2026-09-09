---
name: html-report
description: Create an offline HTML business report with user-selected visual style, length and scroll or slide navigation. Ask only missing preferences and verify output without external assets.
---

# HTML report

Read `../company-agent/references/business-protection.md`. Reuse explicit user
preferences and approved inputs; ask only missing choices in at most three simple
options per question. Recommend minimal for business reading, editorial for a
narrative, bento for several metrics. Offer the other styles on request with a
plain-language explanation, never require knowledge of design terminology.

Ask: style, 분량(핵심/보통/상세), 방식(스크롤/페이지/둘 다). Supported style IDs:
`minimal`, `editorial`, `bento`, `glassmorphism`, `brutalism`, `neumorphism`,
`gradient-mesh`, `freeform`. Length is content planning, not a token count.
The freeform preset is a starting style, not arbitrary user-supplied JavaScript.

Write a bounded JSON job from permitted material only:
`{title, subtitle?, style, mode:"scroll"|"slides"|"both",
length:"short"|"standard"|"detailed", sections:[{title, body?, bullets?,
table?:{headers:[],rows:[]}, chart?:{type:"column",categories:[],
series:[{name:"...",values:[]}]}, image?:{path:"<local approved image>",alt:"..."}}]}`.
Do not fabricate numbers; include sources in section text. For large work show
an outline or representative page before creating all sections.

Use `business html --spec "<job.json>" --output "<new output.html>" --state-root
"<stateRoot>"` via the exact runtime cliCommand. It uses shipped local HTML/CSS/JS,
does not install packages or download fonts, and never overwrites an existing
output. Evaluate returned validation/warnings; inspect the actual result when an
approved browser/rendering path is available. Do not claim visual QA without it.

Use approved connected image MCPs only if images are needed and actually available.
Do not replace SMALL/MEDIUM/LARGE aliases with an image endpoint. If no tool exists
or an ordinary service failure occurs, use native charts/shapes or approved images
and explain the fallback. A DRM/permission refusal is not a fallback opportunity.
Image input understanding and image generation are separate capabilities.

Deliver the output path, chosen format, any excluded input and honest validation.
When unrestricted, feed only abstract style/length preferences and verified fixes
to the existing learning flow, not source content or complete reports.
