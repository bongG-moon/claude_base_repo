# 참고한 설계와 적용 범위

확인일: 2026-10-28. 아래 원본의 방법을 비교해 이 저장소의 업무 환경에 맞는 한국어 지침을 새로 작성했습니다.
외부 코드, 원문 본문, 설치 스크립트를 복사하거나 포함하지 않았습니다. 외부 도구의 품질 주장은 이 스킬의 검증 결과가 아닙니다.

| 원본 | 확인한 자료 | 참고한 부분 | 가져오지 않은 부분 |
| --- | --- | --- | --- |
| [boyang-hu/website-rebuild-skill](https://github.com/boyang-hu/website-rebuild-skill) | `skills/website-rebuild/SKILL.md`, README, LICENSE | 원본 관찰 근거와 결과를 비교하고 의도적인 차이를 남기는 방식 | 전체 사이트 미러, 압축 JS 전체 역분석, 버그 그대로 이식, 다단계 강제 승인 |
| [braxtonROSE4/clone-any-website](https://github.com/braxtonROSE4/clone-any-website) | `SKILL.md`, README | 실제 글꼴과 크기, 요소 상태와 동작을 확인하는 방식 | ego-browser 전용 런타임, 자동 설치, 모든 정적 파일 수집, 고정 점수 보장 |
| [santowilem/skills](https://github.com/santowilem/skills) | `skills/clone-ui/SKILL.md`, README | URL 관찰과 이미지 추정의 구분, 기존 프로젝트에 구현하는 방식 | 스크린샷만 첨부해도 무조건 실행하는 범위, 상시 학습 로그, 다중 작업자 반복 검증 |
| [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | README, LICENSE | 정보 위계, 목적 있는 전환, 과한 카드 사용 억제, 반응형과 상태 점검 | CLI, 브라우저 확장, 자동 설치와 후크, 매 작업 PRODUCT.md 생성 |

라이선스 확인: boyang-hu는 [MIT](https://github.com/boyang-hu/website-rebuild-skill/blob/main/LICENSE),
Impeccable은 [Apache-2.0](https://github.com/pbakaus/impeccable/blob/main/LICENSE) 원문을 확인했습니다.
santowilem은 README에서 MIT를 표기하지만 같은 확인 과정에서 LICENSE 파일은 읽지 못했습니다.
braxtonROSE4의 LICENSE 파일도 확인하지 못했습니다. 이 두 저장소의 코드와 본문을 재배포하지 않습니다.
추후 원문이나 코드를 실제로 포함하려면 해당 시점의 라이선스와 고지 조건을 따로 확인해야 합니다.
