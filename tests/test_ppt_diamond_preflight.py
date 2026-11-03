"""Regressions from the real Claude Code Korean decision-label trial."""
import copy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'company-agent-plugin/scripts'))
from company_agent import ppt_preflight


class DiamondPreflightTests(unittest.TestCase):
    def plan(self, rows):
        return {'font':'Malgun Gothic','pages':[{'elements':rows}]}

    def diamond(self, **changes):
        return {'kind':'shape','shape':'diamond','x':575,'y':82,'w':160,'h':72,
                'group':'decision',**changes}

    def label(self, **changes):
        return {'kind':'text','text':'④ 이상 유무 판단','x':581,'y':86,'w':148,'h':64,
                'size':12,'align':'center','font':'Malgun Gothic','group':'decision',**changes}

    def warnings(self, rows):
        result=ppt_preflight.inspect_plan(self.plan(rows))
        self.assertEqual('not_performed',result['visualReview'])
        self.assertFalse(result['automaticTextShrinking'])
        return [issue for issue in result['issues'] if issue['code']=='possible_diamond_text_clipping']

    def test_real_top_aligned_korean_label_is_flagged_without_scene_changes(self):
        rows=[self.diamond(),self.label()]
        before=copy.deepcopy(rows)
        warnings=self.warnings(rows)
        self.assertEqual(1,len(warnings))
        self.assertEqual((1,1,0),(warnings[0]['slide'],warnings[0]['element'],warnings[0]['shapeElement']))
        self.assertEqual(before,rows)

    def test_real_centered_repairs_for_one_and_two_lines_are_clear(self):
        first=[self.diamond(),self.label(x=595,y=108,w=120,h=20,verticalAlign='middle')]
        second=[self.diamond(x=560,y=172,w=190,h=84),
                self.label(text='⑤ 안전·생산 영향\n(사람 판단)',x=605,y=194,w=100,h=40,verticalAlign='middle')]
        self.assertEqual([],self.warnings(first))
        self.assertEqual([],self.warnings(second))

    def test_vertical_alignment_is_used_instead_of_the_box_centre(self):
        shape=self.diamond(x=100,y=100,w=200,h=100)
        text=self.label(text='확인',x=100,y=100,w=200,h=100)
        for alignment in ('top','bottom'):
            with self.subTest(alignment=alignment):
                self.assertEqual(1,len(self.warnings([shape,{**text,'verticalAlign':alignment}])))
        self.assertEqual([],self.warnings([shape,{**text,'verticalAlign':'middle'}]))

    def test_horizontal_alignment_and_line_spacing_are_used(self):
        shape=self.diamond(x=100,y=100,w=200,h=100)
        text=self.label(text='확인',x=100,y=140,w=200,h=20,verticalAlign='middle')
        self.assertEqual([],self.warnings([shape,text]))
        for alignment in ('left','right'):
            with self.subTest(alignment=alignment):
                self.assertEqual(1,len(self.warnings([shape,{**text,'align':alignment}])))
        text=self.label(text='예\n원본내용확인',x=160,y=100,w=80,h=100,verticalAlign='middle')
        self.assertEqual([],self.warnings([shape,text]))
        self.assertEqual(1,len(self.warnings([shape,{**text,'lineSpacing':3}])))

    def test_external_label_and_ambiguous_group_do_not_produce_guessed_warnings(self):
        self.assertEqual([],self.warnings([self.diamond(),self.label(x=760,y=80)]))
        self.assertEqual([],self.warnings([self.diamond(),self.label(group='another')]))
        self.assertEqual([],self.warnings([self.diamond(),self.diamond(),self.label()]))
        self.assertEqual([],self.warnings([self.diamond(),self.label(allowOverlap=True)]))

    def test_multiple_diamonds_in_same_group_are_matched_by_location(self):
        rows=[self.diamond(),self.diamond(x=100,y=300),self.label(),
              self.label(x=120,y=326,w=120,h=20,verticalAlign='middle')]
        warnings=self.warnings(rows)
        self.assertEqual([(2,0)],[(row['element'],row['shapeElement']) for row in warnings])

    def test_non_wrapping_long_line_is_not_clamped_to_box_width(self):
        shape=self.diamond(x=100,y=100,w=200,h=100)
        text=self.label(text='가'*20,x=180,y=140,w=40,h=20,wrap=False,verticalAlign='middle')
        self.assertEqual(1,len(self.warnings([shape,text])))

    def test_diamond_pair_budget_stays_bounded(self):
        rows=[self.diamond(x=100,y=100,w=200,h=100) for _ in range(80)]
        rows.extend(self.label(text='가',x=190,y=140,w=20,h=20,size=6,verticalAlign='middle')
                    for _ in range(80))
        result=ppt_preflight.inspect_plan(self.plan(rows))
        self.assertTrue(result['truncated'])
        self.assertLessEqual(len(result['issues']),20)
        self.assertNotIn('possible_diamond_text_clipping',[row['code'] for row in result['issues']])


if __name__=='__main__':unittest.main()
