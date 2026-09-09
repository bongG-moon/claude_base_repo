---
name: presentation
description: Produce an editable PowerPoint with Python, optional existing company template and installed PowerPoint rendering. Preserve original files and distinguish editable objects from image assets and DRM restrictions.
---

# Editable presentation

Read `../company-agent/references/business-protection.md` first. Ask only missing
purpose/audience, slide count and template choice. Do not require company templates
to start; use a native-object draft when no template is provided. Retain original
files, never replace output without a new explicit action.

Use `business doctor` for runtime hints and `business ppt-inspect --template
"<source.pptx>"` for allowed template structure. Inspection failure may mean DRM
or an unsupported/corrupt format: do not assert a cause without evidence. Never
decrypt, use OCR/capture, enable macros or bypass Protected View to keep going.

Prepare permitted content as JSON:
`{title, subtitle?, style:"minimal", slides:[{title,body?,bullets?,
table?:{headers:[],rows:[]},chart?:{type:"column"|"bar"|"line"|"pie",
categories:[],series:[{name:"...",values:[]}]},image?:{path:"...",alt:"..."}}]}`.
Show the outline and representative design for substantial work. Existing image
assets may be inserted, but text/tables/charts must remain native editable objects
where supported. Creating a full-slide screenshot does not meet editable-PPT goals.

Run `business ppt --spec "<job.json>" --output "<new.pptx>" [--template
"<source.pptx>"] --state-root "<stateRoot>"` using the installed cliCommand.
Python dispatches to an already available library or the packaged PowerPoint COM
helper. Do not pip-install dependencies, execute model-written Python/VBA, start
an unrelated Office instance, close user presentations, or bypass the CLI safety.
If rendering is unavailable or prohibited, say that visual validation was not
performed. Ordinary static checks do not prove perfect template reproduction.

Inspect editability/validation/warnings, handle partial outputs, then deliver a
new file with precise limitations. SmartArt, animations, masters and arbitrary
complex source layouts are not universally reconstructible by this pilot.

If image generation is needed, discover a genuinely connected approved MCP and
read its schema. Use it only for artwork/backgrounds, not precise chart numbers
or slide text. No available image tool or ordinary timeout may fall back to
native shapes/charts with notice. Never switch tools/models to bypass a DRM denial.
Do not claim a generic image provider has been configured by installing this Skill.

Finish bounded verification and learning. Store reusable abstract design choices
only when allowed, never protected slide content or a complete source deck.
