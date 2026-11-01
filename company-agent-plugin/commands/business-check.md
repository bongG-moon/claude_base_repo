---
description: 파일이나 설정을 바꾸지 않고 업무 기능의 사용 조건을 확인합니다.
---

# Business pilot check

Default to Korean for all questions, choices and result explanations unless the user explicitly requests another language. Preserve exact identifiers and explain English tool results in Korean.

Use the exact `company_agent_runtime.cliCommand` prefix and active stateRoot.
Run `business doctor --state-root "<stateRoot>"`. Translate each result into
사용 가능 / 추가 확인 필요 / 사용 불가, not a claim of live Office or DRM validation.
Do not request credentials, change model settings, register/replace MCPs, launch
Office, scan a mailbox, or download packages as part of this basic check.

For a real document test, use the requested sample and available integrations.
Office capability and ordinary file readability are not proof of live integration success.
Report unsupported actions honestly; do not fabricate tool results.
