# 업무 지식 저장 명세

저장할 정의와 범위가 결정됐을 때 사용합니다. 원본 대신 추출한 정의, 조건과 출처만 넣습니다.

```json
{
  "title": "WIP_HISTORY 개인 조회 기준",
  "mode": "extend",
  "extends": "table.mes.wip_history",
  "body": "# 개인 적용 기준\n\n라인 A 분석에서는 TEST 이벤트도 제외한다.",
  "reason": "사용자가 향후 조회 기준으로 명시",
  "source": "explicit_user_feedback"
}
```

예시는 실제 관찰한 업무 정의로 바꿉니다. extend/fork의 extends는 확인한 공통 항목 ID입니다. personal-new에는 공통 연결을 만들지 않습니다. 기존 개인 항목 수정은 그 항목의 id와 원래 범위를 유지합니다. 임의 필드, 대화 원문과 비밀 값은 추가하지 않습니다.

현재 knowledge upsert는 ok, path, knowledgeId를 반환합니다. 반환된 파일을 한 번 읽어 내용과 적용 범위를 확인합니다. Memory의 persisted-content-verified 영수증을 Knowledge에도 있다고 가정하지 않습니다.
