---
name: platform-mcp-builder
description: 이전 명시 호출을 위한 호환 이름입니다. 스킬·도구 제작은 asset-factory로 통합되었습니다.
disable-model-invocation: true
---

# 이전 이름 호환

새 작업의 자동 선택 대상은 아닙니다. 이전 이름으로 명시 호출되면 `../asset-factory/SKILL.md`를 읽고 같은 요청을 통합 제작 절차로 이어갑니다. 이미 받은 요구사항·저장 범위를 다시 묻지 않습니다.

기존 개발 폴더와 자산은 이동·변환하지 않습니다. `scripts/create_project.py`와 `references/platform-contract.md`는 전사 제출용 독립 HTTP 프로젝트의 호환 지원 파일로 유지합니다.
