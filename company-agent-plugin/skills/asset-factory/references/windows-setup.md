# Human-only Windows setup steps

Use only for an explicitly requested setup helper. First identify steps that the
Agent can perform within existing permissions; perform those in the parent
workflow instead of handing commands back to the user. A blocked operation is
not permission to execute it by another mechanism.

## Built-in safe questionnaire generator

For ordinary non-sensitive choices or existing local folder paths, use the built-in
`company-agent setup-helper create --spec "<absolute spec.json>" --state-root "<stateRoot>"`
with the canonical runtime CLI prefix. This is separate from arbitrary executable
asset creation: the trusted core emits a fixed questionnaire, never runs input as
code, never installs software, never changes Claude/MCP settings or collects secrets.

Write a compact spec with exactly `name`, `title`, `steps`. Each step has `id`,
`label`, `kind` (`choice`, `text`, `path`) and `required` (boolean). A `choice` also
has `choices` (string array). Example only, replace with the user's real needs:
Write `title`, `label` and `choices` in Korean by default, unless explicitly requested otherwise; preserve `name`, `id` and schema/command tokens. English source text does not change this default.

`{"name":"report-setup","title":"보고서 준비","steps":[{"id":"report-style","label":"보고서 모양","kind":"choice","required":true,"choices":["간단 요약","상세 보고"]}]}`

The returned helper.py and spec.json live together under the active state root's
setup-helpers directory. Validate with the verified Python executable followed by
`"<helper.py>" --check`. Run without `--check` in a user-visible terminal only when
the user wants to answer. Keep the two files together when sharing an approved
helper. Answers are reviewed before saving; cancellation returns non-success and
later runs offer keep/change of saved non-secret answers. Do not automatically
convert collected values into executable commands or apply privileged settings.
For setup actions, invoke an existing approved installer separately in its normal
workflow. Tell the user clearly this helper collects inputs; it does not complete
an installation. Test generated helpers with fictional inputs, not real credentials.

Reuse verified runtimes, no Bash, WSL, public downloads, or elevation by default.
Sensitive-data detection is incomplete; answers are plaintext. If credentials are
needed, use a separate approved hidden-input mechanism, never this questionnaire.
Arbitrary shell/dynamic/destructive code remains rejected by the personal asset factory.
Unsupported capabilities need administrator-owned implementation, not a bypass.
Test cancellation, missing prerequisites and repeat execution in an isolated fixture.
Preserve unrelated settings; never test with real accounts or send mail as a probe.
