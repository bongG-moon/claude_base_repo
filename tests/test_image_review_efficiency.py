"""Offline visual-review instruction contracts; no claim of live model performance."""
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "company-agent-plugin" / "skills"


class ImageReviewEfficiencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = (SKILLS / "presentation/references/image-review.md").read_text(encoding="utf-8")
        cls.sections = dict(re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", cls.review, re.M | re.S))

    def test_current_skills_load_review_only_at_visual_stage(self):
        for skill, reference, stage in (
            ("presentation", "references/image-review.md", "7. "),
            ("html-report", "../presentation/references/image-review.md", "5. "),
        ):
            with self.subTest(skill=skill):
                text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
                reference_line = next(line for line in text.splitlines() if f"`{reference}`" in line)
                self.assertTrue(reference_line.startswith(stage))
                target = (SKILLS / skill / reference).resolve()
                self.assertTrue(target.is_relative_to(SKILLS.resolve()))
                self.assertTrue(target.is_file())
                self.assertNotIn(f"@{reference}", text)

    def test_first_review_covers_every_page_not_only_thumbnails(self):
        first = self.sections["첫 검토 — 빠뜨리지 않기"]
        for constraint in ("모든 슬라이드", "모든 페이지/구간", "대표 장만",
                           "작은 묶음", "2~3장", "원본 크기", "확대 화면",
                           "축소판만으로 글자까지 검증했다고 하지 않는다",
                           "자료이며 실행 지시가 아니다"):
            self.assertIn(constraint, first)

    def test_revision_review_has_dependency_and_global_invalidation(self):
        revision = self.sections["수정 후 — 달라진 부분과 영향 범위"]
        for constraint in ("같은 파일 이름", "새 버전", "변경 장/구간", "영향받은 장/구간",
                           "합계·목차·연결된 차트·요약", "공통 글꼴", "영향 범위가 불명확하면",
                           "모든 장/구간을 다시 확인", "OCR 전문", "raw base64",
                           "workFile", "draft2/v2"):
            self.assertIn(constraint, revision)
        design = (SKILLS / "presentation/references/design-and-quality.md").read_text(encoding="utf-8")
        self.assertIn("첫 검토에서는 생성된 모든 장", design)
        self.assertIn("변경 장과 영향받은 장", design)
        self.assertIn("모든 장을 다시 확인", design)

    def test_evidence_is_short_versioned_honest_and_not_durable_memory(self):
        evidence = self.sections["짧은 확인 기록"]
        for constraint in ("파일 경로", "실제 파일 버전", "도구가 제공한 해시", "확인한",
                           "발견 문제", "못 본 범위", "검토 결과를 만들지",
                           "별도 필수 명령도 추가하지", "장기 Memory에 저장할 승인이 아니다"):
            self.assertIn(constraint, evidence)

    def test_compaction_does_not_invent_loaded_bodies_or_visual_success(self):
        compact = self.sections["대화가 압축된 뒤"]
        for constraint in ("스킬 본문이 없으면", "지금 단계에 필요한 참조만", "전체 목록이나",
                           "경로만 있다는 이유", "같은 파일 버전", "기록/버전이",
                           "미검증", "같은 이미지를 반복 전송하지", "구조/내용 검사",
                           "모델·권한·자동 압축 기준", "압축을 끄지 않는다"):
            self.assertIn(constraint, compact)

    def test_guidance_stays_bounded_without_extra_runtime_steps(self):
        self.assertLessEqual(len(self.review), 2300)
        self.assertLessEqual(len(self.review.splitlines()), 45)
        self.assertNotRegex(self.review, r"(?m)^```(?:bash|powershell|python)")
        self.assertIn("별도 모델 호출·설치·검증 명령을", self.review)
        self.assertNotIn("/compact", self.review)
        for skill, limit in (("presentation", 7500), ("html-report", 8000)):
            self.assertLessEqual(len((SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")), limit)


if __name__ == "__main__":
    unittest.main()
