# 양식 선택과 작업 재개

PPT나 이미지를 이미 첨부했으면 `creationMode:reference`, `referenceMode:style`로 이어갑니다. 명시적인 원본 개체 유지 요청만 preserve로 처리하며 유지 범위를 습관적으로 다시 묻지 않습니다. `referenceImages`에는 PNG/JPEG/WebP 절대경로 최대 60개와 순서를 유지하고 2~3장씩 확인합니다. 실제 관찰은 [reference-style.md](reference-style.md)의 `referenceStyle`로 짧게 합칩니다.

새 제작에 디자인 지정도 참고자료도 없을 때만 아래 선택을 한 번 보여 줍니다. 목적, 대상, 장수도 빠져 있다면 같은 질문에 묶습니다. 첨부 양식, 명시한 스타일, 기존 작업의 선택을 다시 묻지 않습니다. `알아서`, `추천대로`, `질문 없이`는 내용을 보고 적절히 구성하며 다음 필수 확인은 완성된 HTML 초안의 승인입니다.

| 선택 | 보여 줄 설명 | 내부 값 |
|---|---|---|
| 깔끔한 업무 보고형 | 흰 배경과 남색 제목, 청록 강조. 실적과 의사결정 보고 | creationMode:new, designPreset:business |
| 흑백 간결형 | 흑백 대비와 절제된 장식. 숫자, 표와 논리 중심 | creationMode:new, designPreset:monochrome |
| 따뜻한 설명형 | 크림 배경과 차분한 갈색. 교육과 과정 설명 | creationMode:new, designPreset:warm |
| 기존 양식 활용 | PPT, 장표 이미지 또는 HTML을 참고해 익숙한 스타일 유지 | 자료에 따라 reference/saved |
| 내용에 맞게 추천 | 자료 성격과 청중에 맞춰 구성과 강조 방식을 선택 | new + 실제 선택한 designPreset/theme |
| 직접 입력 | 원하는 색, 글꼴, 분위기, 배치를 자유롭게 지정 | designDirection에 요청 보존, 지원하는 theme/font/elements에 반영 |

선택은 번호나 이름으로 답할 수 있게 합니다. 현재 호스트의 선택 도구가 항목 수를 제한하면 간결한 번호 목록으로 제시하며 선택지를 임의로 없애지 않습니다. `추천`은 세 가지 시안을 별도로 만들라는 뜻이 아니며 `직접 입력`에 없는 새 preset 이름을 만들지 않습니다. 사용자가 말한 내용만 현재 job에 반영합니다.

선택 도우미가 필요할 때만 실행합니다. 이미 답을 알면 바로 전체 job을 작성합니다.

```text
python "스킬폴더/scripts/presentation.py" choices
python "스킬폴더/scripts/presentation.py" choices --spec "job.json"
```

시각 비교를 원하거나 이름만으로 고르기 어려우면 `python "스킬폴더/scripts/presentation.py" gallery --output "양식-미리보기.html"`로 예시를 보여 줍니다. 모든 작업에서 여러 벌의 발표자료를 미리 생성하지 않습니다. 갤러리의 가상 자료는 이번 발표의 본문이 아닙니다.

실제 PPTX 또는 저장한 HTML 대표 양식이 있으면 `--template "양식 파일"`을 붙입니다. `input_required`는 오류가 아니라 답을 기다리는 단계입니다. `preview_required`는 선택을 유지해 전체 장수의 내용을 작성하고 HTML 초안을 만들라는 뜻입니다. 도우미 응답의 previewCommand에 따라 이 독립판의 `draft --spec "job.json" --output "draft.html"`을 사용합니다. 사용자에게 선택용 JSON이나 세션 ID를 요구하지 않습니다.

기존 PPT·이미지·HTML을 첨부하면 `reference-inputs.md`로 바로 이어집니다. `이 스타일로`는 보통 style이며, 기존 PPT 개체와 배치를 유지해 내용을 바꾸라고 했을 때만 PPTX preserve를 사용합니다. 자료를 아직 받지 못했다면 파일을 기다리고 임의 기본 양식으로 바꾸지 않습니다.

선택한 양식은 색만 바꾸는 옵션이 아닙니다. 내용의 역할에 맞는 넓은 데이터 장, 비교, 순서도와 결론 장을 같은 시각 규칙으로 구성합니다. 이후 수정은 기존 job과 승인 상태를 재사용하며 실질 내용이나 디자인이 바뀐 경우에만 같은 HTML 초안을 갱신해 확인받습니다.

양식의 색감과 장별 배치는 별개다. 같은 색감 안에서도 pageRole에 따라 표지, 핵심 메시지, 비교, 업무 분기, 날짜 비례 일정, 상세 표와 결론을 다르게 구성한다. 선택용 가상 갤러리는 세 색감과 일곱 장 역할의 21개 예시이며, 사용자가 비교를 원할 때만 만든다. 해당 예시를 실제 업무 내용이나 승인 기록으로 사용하지 않는다.
