"""Offline intent regressions: examples are evidence, not workflow requests.

These fixtures run only during development; no evaluation model or prompt is
added to normal requests. Existing integration tests cover choice receipts.
"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'company-agent-plugin/scripts'))
from company_agent.skill_decision import decide_preparation
from company_agent.skill_task_context import task_candidates, _features


def inventory():
    rows = (
        ('html-report', 'HTML 보고서를 제작합니다.'),
        ('asset-factory', '개인 스킬과 도구를 만들고 수정합니다.'),
        ('image-reader', '이미지를 읽고 분석합니다.'),
        ('skill-installer', '개인 스킬을 설치하고 등록합니다.'),
    )
    return {'complete': True, 'skills': [
        {'id': name, 'name': name, 'invocation': 'company-agent:' + name,
         'source': 'company', 'path': 'C:/skills/' + name + '/SKILL.md',
         'description': description} for name, description in rows]}


class SkillRelevanceCorpusTests(unittest.TestCase):
    def decision(self, prompt):
        data = inventory()
        hints = task_candidates(data, prompt)
        return hints, decide_preparation(hints, data['skills'], [])

    def test_explaining_quoted_requests_does_not_start_described_work(self):
        for prompt in (
            '이 예문을 영어로 번역해줘: "HTML 보고서를 만들어줘"',
            '“이미지를 읽어줘”라는 문장이 무슨 뜻인지 설명해줘',
            '예문: `도구를 만들어줘`. 이 문장만 영어로 번역해줘.',
            '다음 예시의 차이만 설명해줘: “이미지를 읽어줘”와 “HTML 보고서를 만들어줘”',
            '아래 문장의 뜻만 설명해줘.\n```text\nHTML 보고서를 만들어줘\n```',
            '이 예문을 설명해줘.\n> HTML 보고서를 만들어줘',
            'Translate this example: "Create an HTML report"',
        ):
            with self.subTest(prompt=prompt):
                hints, choice = self.decision(prompt)
                self.assertFalse(hints.get('strongIds'), hints)
                self.assertNotIn(choice.mode, {'load', 'choose'}, choice)

    def test_actual_request_survives_reference_examples_and_quoted_titles(self):
        for prompt in (
            '예문 "이미지를 읽어줘"는 설명만 하고 실제로는 HTML 보고서를 만들어줘',
            '"html-report"로 HTML 보고서를 만들어줘',
            '"월간 HTML 보고서"를 만들어줘',
            '"월간 HTML 보고서"를 만들고 지표의 의미도 설명해줘',
            '"HTML 보고서" 만들어줘. 문구는 한국어로 써줘',
            '"월간 HTML 보고서"를 깔끔하게 만들어줘. 내용은 쉬운 설명으로 써줘',
            '다음 자료로 HTML 보고서를 만들어줘.\n```text\n도구를 만들어줘\n```',
            'HTML 보고서를 만들어줘.\n> 이미지 스킬을 설치해줘',
        ):
            with self.subTest(prompt=prompt):
                _, choice = self.decision(prompt)
                self.assertEqual('html-report', choice.candidate_id, choice)
        _, choice = self.decision('"이미지 자료"를 읽고 의미를 설명해줘')
        self.assertEqual('image-reader', choice.candidate_id, choice)

    def test_skill_install_is_distinct_from_image_read_and_existing_tool_use(self):
        cases = (
            ('@image-reader.zip 이미지 읽는 스킬을 설치해줘', 'skill-installer'),
            ('이 이미지 읽어줘', 'image-reader'),
            ('스킬을 사용해서 HTML 보고서를 만들어줘', 'html-report'),
            ('기존 도구로 페이지를 확인해줘. 새 도구를 만들거나 설치하지 마.', None),
        )
        for prompt, expected in cases:
            with self.subTest(prompt=prompt):
                _, choice = self.decision(prompt)
                self.assertEqual(expected, choice.candidate_id, choice)

    def test_ordinary_requests_keep_identical_candidate_context(self):
        # Comparing the actual hint object also guards its serialized prompt
        # size. The new filter must not inject instructions or add questions.
        for prompt in ('HTML 보고서를 만들어줘', '이미지 읽어줘',
                       '스킬을 설치해줘', '회사 asset-factory로 도구를 만들어줘',
                       '도구를 설치하지 말고 현재 제공되는 기능만 확인해줘'):
            with self.subTest(prompt=prompt):
                data = inventory()
                current = task_candidates(data, prompt)
                with patch('company_agent.skill_task_context._retrieval_prompt', side_effect=lambda text: text):
                    original = task_candidates(data, prompt)
                self.assertEqual(original, current)

    def test_explicit_slash_after_hint_window_keeps_existing_choice(self):
        _, choice = self.decision('참고 자료 ' * 500 + '\n/company-agent:html-report')
        self.assertEqual('html-report', choice.candidate_id, choice)

    def test_other_skill_ownership_reference_is_not_a_competing_capability(self):
        data = inventory()
        data['skills'].append({
            'id': 'web-interface', 'name': 'web-interface', 'source': 'company',
            'invocation': 'company-agent:web-interface', 'path': 'C:/skills/web-interface/SKILL.md',
            'description': '웹페이지를 제작합니다. 스킬 제작은 asset-factory 역할입니다.',
        })
        for prompt, expected in (
            ('크롬에서 신청 현황을 정리하는 스킬 만들어줘', 'asset-factory'),
            ('company-agent:web-interface로 스킬 제작 화면을 만들어줘', 'web-interface'),
        ):
            with self.subTest(prompt=prompt):
                hints = task_candidates(data, prompt)
                choice = decide_preparation(hints, data['skills'], [])
                self.assertEqual(expected, choice.candidate_id, choice)
        # The owned capability remains, and ordinary self-description without
        # a different named workflow is not removed.
        domains, actions = _features(data['skills'][-1]['description'], metadata=True,
                                     owner_names=('web-interface', 'company-agent:web-interface'))
        self.assertEqual(({'html'}, {'make'}), (domains, actions))
        self.assertEqual(({'html'}, {'make'}), _features('HTML을 제작하는 역할입니다.', metadata=True))
        data['skills'][0]['description'] = 'HTML 보고서 제작은 html-report 역할입니다.'
        data['skills'] = data['skills'][:1]
        hints = task_candidates(data, 'HTML 보고서를 만들어줘')
        self.assertIn('html-report', hints.get('strongIds', []))
        self.assertEqual('html-report', decide_preparation(hints, data['skills'], []).candidate_id)


if __name__ == '__main__':
    unittest.main()
