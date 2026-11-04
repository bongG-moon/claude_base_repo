"""Regressions for editable workflow geometry, not model-written demo repairs."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'company-agent-plugin/scripts'))
from company_agent import ppt_layouts

PALETTE={'title':'45342B','text':'41382F','muted':'65584B','accent':'80452C',
         'background':'FAF7F0','tint':'EEE7DC'}


def intersects_segment(a,b,box):
    """Strict interior: touching a node's input/output border is intentional."""
    left,top,right,bottom=box['x'],box['y'],box['x']+box['w'],box['y']+box['h']
    eps=.001
    if abs(a[0]-b[0])<eps:
        return left+eps<a[0]<right-eps and max(min(a[1],b[1]),top)<min(max(a[1],b[1]),bottom)-eps
    if abs(a[1]-b[1])<eps:
        return top+eps<a[1]<bottom-eps and max(min(a[0],b[0]),left)<min(max(a[0],b[0]),right)-eps
    raise AssertionError('Workflow connections must have orthogonal segments')


def overlap(a,b):
    return (max(a['x'],b['x'])<min(a['x']+a['w'],b['x']+b['w'])-.001 and
            max(a['y'],b['y'])<min(a['y']+a['h'],b['y']+b['h'])-.001)


class WorkflowRoutingTests(unittest.TestCase):
    def page(self,row,width=960,height=540):
        before=copy.deepcopy(row)
        result=ppt_layouts.compose(row,1,width,height,PALETTE,'Malgun Gothic',ppt_layouts.profile({},width,height))
        self.assertEqual(before,row,'Do not repair geometry by changing the requested workflow')
        return result['elements']

    def assert_clear(self,row,elements):
        boxes=[e for e in elements if e['kind']=='shape']
        lines=[e for e in elements if e['kind']=='line']
        expected=[e.get('label') for e in row['workflow']['edges'] if e.get('label')]
        labels=[e for e in elements if e['kind']=='text' and e.get('text') in expected]
        self.assertCountEqual(expected,[e['text'] for e in labels])
        self.assertEqual(len(row['workflow']['edges']),len(lines))
        self.assertEqual(len(row['workflow']['nodes']),len(boxes))
        for edge,line in zip(row['workflow']['edges'],lines):
            self.assertEqual('triangle',line['endArrow'])
            points=[(line['x']+x,line['y']+y) for x,y in line['points']]
            ids=[n['id'] for n in row['workflow']['nodes']]
            source,target=boxes[ids.index(edge['from'])],boxes[ids.index(edge['to'])]
            self.assertAlmostEqual(source['x']+source['w'],points[0][0])
            self.assertAlmostEqual(target['x'],points[-1][0])
            self.assertAlmostEqual(target['y']+target['h']/2,points[-1][1])
            for a,b in zip(points,points[1:]):
                for box in boxes+labels:
                    self.assertFalse(intersects_segment(a,b,box),(edge,box.get('text',box.get('group')),a,b))
        for i,label in enumerate(labels):
            for box in boxes+labels[i+1:]:
                self.assertFalse(overlap(label,box),(label,box))

    def warm_case(self):
        # Original Claude-generated failing slide: keep the long body/title,
        # skip edge and all labels; don't replace it with a handmade scene.
        return {'pageRole':'workflow',
                'title':'이상이 있으면 사람이 안전·생산 영향을 판단한 뒤 담당자에게 인계합니다',
                'body':"예외: 즉시 위험은 기존 비상 절차로 자동 진행 중지 · ID 누락·중복은 목록 확인 대상으로 분리 · 담당자 부재는 같은 조 대체 담당자 · 근거 없으면 '근거 보완'(완료 아님) · 알림 발송만으로 완료 처리하지 않음.",
                'workflow':{'nodes':[
                    {'id':'reg','title':'계획·설비 ID 확인 후 결과 등록','shape':'roundRect'},
                    {'id':'dec','title':'이상 유무 판단','shape':'diamond'},
                    {'id':'hand','title':'담당자 인계(기한·확인자 기록)','shape':'roundRect'},
                    {'id':'close','title':'근거 확인 후 종료·주간 집계','shape':'hexagon'}],
                    'edges':[{'from':'reg','to':'dec'},
                             {'from':'dec','to':'close','label':'이상 없음'},
                             {'from':'dec','to':'hand','label':'이상 있음'},
                             {'from':'hand','to':'close'}]}}

    def test_real_warm_slide_bypasses_middle_node_and_keeps_both_conditions_visible(self):
        row=self.warm_case();elements=self.page(row)
        self.assert_clear(row,elements)
        bypass=[e for e in elements if e['kind']=='line'][1]
        self.assertGreater(len(bypass['points']),2)
        self.assertLess(bypass['y'],min(e['y'] for e in elements if e['kind']=='shape'))
        for e in elements:
            self.assertGreaterEqual(min(e['x'],e['y']),0)
            self.assertLessEqual(e['x']+e['w'],960)
            self.assertLessEqual(e['y']+e['h'],540)

    def test_decision_label_corners_are_inside_the_diamond_with_clearance(self):
        elements=self.page(self.warm_case())
        diamond=next(e for e in elements if e.get('shape')=='diamond')
        label=next(e for e in elements if e.get('group')==diamond['group'] and e['kind']=='text')
        self.assertEqual('middle',label['verticalAlign'])
        for x in (label['x'],label['x']+label['w']):
            for y in (label['y'],label['y']+label['h']):
                distance=abs(x-diamond['x']-diamond['w']/2)/(diamond['w']/2)+abs(y-diamond['y']-diamond['h']/2)/(diamond['h']/2)
                self.assertLessEqual(distance,.951)

    def test_only_labelled_gutter_grows_so_korean_node_text_keeps_its_width(self):
        elements=self.page(self.warm_case())
        boxes=[e for e in elements if e['kind']=='shape']
        gaps=[right['x']-left['x']-left['w'] for left,right in zip(boxes,boxes[1:])]
        default_gap=ppt_layouts.profile({})['gap']
        self.assertAlmostEqual(default_gap,gaps[0])
        self.assertAlmostEqual(default_gap,gaps[2])
        self.assertGreater(gaps[1],default_gap)
        width_with_global_gap=(864-max(gaps)*3)/4
        self.assertGreater(boxes[0]['w'],width_with_global_gap)
        for node in self.warm_case()['workflow']['nodes']:
            label=next(e for e in elements if e.get('text')==node['title'])
            self.assertEqual(18,label['size'],'Keep font size and full text instead of shrinking it')

    def test_fork_merge_labels_do_not_overlap_nodes_or_the_other_branch_lines(self):
        row={'pageRole':'workflow','title':'실제 검토 결과에 따른 분기',
             'workflow':{'nodes':[{'id':'a','title':'요청 확인','shape':'diamond'},
                                  {'id':'b','title':'내용 변경'}, {'id':'c','title':'원본 유지'},
                                  {'id':'d','title':'결과 확인'}],
                         'edges':[{'from':'a','to':'b','label':'수정 필요'},
                                  {'from':'a','to':'c','label':'변경 없음'},
                                  {'from':'b','to':'d'}, {'from':'c','to':'d'}]}}
        self.assert_clear(row,self.page(row))

    def test_two_decisions_and_two_skip_edges_get_distinct_clear_lanes(self):
        row={'pageRole':'workflow','title':'검토와 승인 결과를 구분합니다',
             'workflow':{'nodes':[{'id':'a','title':'요청 확인','shape':'diamond'},
                                  {'id':'b','title':'기준 확인','shape':'diamond'},
                                  {'id':'c','title':'내용 보완'}, {'id':'d','title':'결과 확정'}],
                         'edges':[{'from':'a','to':'b'}, {'from':'b','to':'c'},
                                  {'from':'c','to':'d'}, {'from':'a','to':'c','label':'검토 완료'},
                                  {'from':'b','to':'d','label':'보완 없음'}]}}
        elements=self.page(row);self.assert_clear(row,elements)
        bypass=[e for e in elements if e['kind']=='line' and len(e['points'])>2]
        self.assertEqual(2,len({e['y'] for e in bypass}))

    def test_three_way_fork_and_merge_have_separate_labels_and_clear_routes(self):
        for merge in (False,True):
            row={'pageRole':'workflow','title':'세 가지 결과를 구분합니다',
                 'workflow':{'nodes':[{'id':'s','title':'검토','shape':'diamond'},
                                      *[{'id':key,'title':key} for key in 'abc']],
                             'edges':[{'from':key if merge else 's','to':'s' if merge else key,'label':label}
                                      for key,label in zip('abc',('첫번째','두번째','세번째'))]}}
            for width in (720,960):
                with self.subTest(merge=merge,width=width):
                    self.assert_clear(row,self.page(row,width=width))

    def test_many_to_many_connections_keep_distinct_labels_and_explicit_edges(self):
        row={'pageRole':'workflow','title':'실제 연결만 표시합니다',
             'workflow':{'nodes':[{'id':v,'title':v} for v in 'abcd'],
                         'edges':[{'from':a,'to':b,'label':a+' 조건 '+b}
                                  for a in 'ab' for b in 'cd']}}
        self.assert_clear(row,self.page(row))

    def test_simple_chain_preserves_native_straight_connectors(self):
        row={'pageRole':'workflow','title':'확인 후 처리',
             'workflow':{'nodes':[{'id':v,'title':v} for v in 'abcd'],
                         'edges':[{'from':a,'to':b} for a,b in zip('abc','bcd')]}}
        elements=self.page(row);self.assert_clear(row,elements)
        self.assertTrue(all(len(e['points'])==2 for e in elements if e['kind']=='line'))

    def test_narrow_page_keeps_label_spacing_and_original_font_size(self):
        row={'pageRole':'workflow','title':'검토',
             'workflow':{'nodes':[{'id':'a','title':'자료 확인'},{'id':'b','title':'작업 완료'}],
                         'edges':[{'from':'a','to':'b','label':'조건 일치'}]}}
        elements=self.page(row,width=720);self.assert_clear(row,elements)
        self.assertTrue(all(e['x']+e['w']<=720 for e in elements))
        self.assertEqual(11,next(e['size'] for e in elements if e.get('text')=='조건 일치'))


if __name__=='__main__':
    unittest.main()
