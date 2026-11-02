"""Semantic full-template previews retain fixed objects without editing sources."""
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'company-agent-plugin/scripts'))
from company_agent import ppt_template_scene as scene


class TemplateSceneTests(unittest.TestCase):
    def setUp(self):
        from pptx import Presentation
        from pptx.util import Pt
        parent = ROOT/'.smoke/ppt-enhance/temp'
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.deck = Presentation()
        self.deck.slide_width, self.deck.slide_height = Pt(960), Pt(540)
        self.slide = self.deck.slides.add_slide(self.deck.slide_layouts[6])
        self.palette = {'text':'333333','background':'FFFFFF'}

    def text(self, value, x=30, y=30, w=600, h=80, *, shapes=None):
        from pptx.util import Pt
        shape = (shapes if shapes is not None else self.slide.shapes).add_textbox(Pt(x),Pt(y),Pt(w),Pt(h))
        shape.text = value
        for paragraph in shape.text_frame.paragraphs:
            paragraph.font.name = '맑은 고딕'
            paragraph.font.size = Pt(18)
        return shape

    def preview(self):
        return scene.preview_slide(self.slide, self.deck, self.palette, '맑은 고딕')

    def test_fixed_content_and_nested_group_are_projected_without_source_mutation(self):
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.util import Pt
        self.text('새 제목')
        background = self.slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,Pt(25),Pt(120),Pt(850),Pt(300))
        background.fill.solid()
        group = self.slide.shapes.add_group_shape()
        self.text('기존 양식의 고정 영역',70,150,600,40,shapes=group.shapes)
        nested = group.shapes.add_group_shape()
        self.text('하위 업무 절차',80,210,500,40,shapes=nested.shapes)
        before = self.slide._element.xml
        page = self.preview()
        visible = '\n'.join(e.get('text','') for e in page['elements'])
        self.assertIn('새 제목',visible)
        self.assertIn('기존 양식의 고정 영역',visible)
        self.assertIn('하위 업무 절차',visible)
        self.assertEqual(2,page['coverage']['groups'])
        self.assertTrue(page['coverage']['completeObjectProjection'])
        self.assertEqual(before,self.slide._element.xml)

    def test_scaled_nested_group_coordinates_become_absolute(self):
        from pptx.util import Pt
        group = self.slide.shapes.add_group_shape()
        child = self.text('위치 확인',100,100,200,50,shapes=group.shapes)
        original = (child.left.pt,child.top.pt,child.width.pt,child.height.pt)
        group.width *= 2
        group.height *= 2
        group.left,group.top = Pt(300),Pt(200)
        page = self.preview()
        element = next(e for e in page['elements'] if e.get('text') == '위치 확인')
        self.assertAlmostEqual(314.4,element['x'])  # 7.2pt inset scaled twice.
        self.assertAlmostEqual(207.2,element['y'])
        self.assertAlmostEqual(original[2]*2-28.8,element['w'])
        self.assertAlmostEqual(original[3]*2-14.4,element['h'])

    def test_partial_korean_run_styles_and_soft_breaks_survive(self):
        from pptx.util import Pt
        from pptx.dml.color import RGBColor
        shape = self.text('')
        paragraph = shape.text_frame.paragraphs[0]
        paragraph.text = ''
        run = paragraph.add_run(); run.text='신청 '
        emphasized = paragraph.add_run(); emphasized.text='40명'
        emphasized.font.bold = True
        emphasized.font.color.rgb = RGBColor.from_string('C00000')
        paragraph.add_line_break()
        paragraph.add_run().text='추가 확인'
        shape.text_frame.add_paragraph().text='다음 절차'
        before = self.slide._element.xml
        page = self.preview()
        e = next(e for e in page['elements'] if e.get('kind')=='text')
        self.assertEqual('신청 40명\n추가 확인\n다음 절차',e['text'])
        self.assertEqual(e['text'],''.join(r['text'] for r in e['runs']))
        mark = next(r for r in e['runs'] if r['text']=='40명')
        self.assertTrue(mark['bold'])
        self.assertEqual('C00000',mark['color'])
        self.assertEqual(before,self.slide._element.xml)

    def test_merged_table_header_is_shown_once_with_merged_geometry(self):
        from pptx.util import Pt
        table = self.slide.shapes.add_table(3,2,Pt(40),Pt(130),Pt(800),Pt(240)).table
        table.cell(0,0).merge(table.cell(0,1))
        table.cell(0,0).text='합쳐진 제목'
        table.cell(1,0).text='생산'
        table.cell(1,1).text='12명'
        table.cell(2,0).text='품질'
        table.cell(2,1).text='8명'
        before = self.slide._element.xml
        page = self.preview()
        headers = [e for e in page['elements'] if e.get('text')=='합쳐진 제목']
        self.assertEqual(1,len(headers))
        self.assertGreater(headers[0]['w'],700)
        self.assertIn('생산',' '.join(e.get('text','') for e in page['elements']))
        self.assertTrue(page['coverage']['completeObjectProjection'])
        self.assertTrue(page['coverage']['approximations'])
        self.assertEqual(before,self.slide._element.xml)

    def test_embedded_picture_is_local_data_and_source_is_unchanged(self):
        from pptx.util import Pt
        raw = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMycAAAAASUVORK5CYII=')
        self.slide.shapes.add_picture(BytesIO(raw),Pt(40),Pt(80),width=Pt(120),height=Pt(120))
        before=self.slide._element.xml
        page=self.preview()
        image=next(e for e in page['elements'] if e['kind']=='image')['image']
        self.assertEqual(raw,base64.b64decode(image['data']))
        self.assertEqual('image/png',image['mime'])
        self.assertNotIn('path',image)
        self.assertEqual(before,self.slide._element.xml)

    def test_unsupported_shape_and_rotation_are_reported(self):
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.util import Pt
        self.slide.shapes.add_shape(MSO_SHAPE.CLOUD,Pt(40),Pt(100),Pt(200),Pt(100))
        rotated=self.text('회전한 원본',300,100,300,60)
        rotated.rotation=20
        page=self.preview()
        reasons={r['reason'] for r in page['coverage']['unsupported']}
        self.assertIn('unsupported_preset',reasons)
        self.assertIn('rotated_object',reasons)
        self.assertFalse(page['coverage']['completeObjectProjection'])
        self.assertTrue(page['warnings'])
        self.assertEqual('not_performed',page['coverage']['visualReview'])

    def test_master_fixed_art_is_included_but_master_placeholders_are_not_duplicated(self):
        from copy import deepcopy
        label = self.text('고정 브랜드 문구',20,490,600,30)
        self.deck.slide_master.shapes._spTree.append(deepcopy(label._element))
        self.slide.shapes._spTree.remove(label._element)
        self.text('현재 슬라이드 본문')
        page=self.preview()
        text='\n'.join(e.get('text','') for e in page['elements'])
        self.assertIn('고정 브랜드 문구',text)
        self.assertIn('현재 슬라이드 본문',text)
        self.assertEqual(2,len([e for e in page['elements'] if e['kind']=='text']))

    def test_projection_limit_stops_without_unbounded_output(self):
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.dml.color import RGBColor
        from pptx.util import Pt
        for _ in range(1205):
            shape=self.slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,Pt(20),Pt(20),Pt(100),Pt(100))
            shape.fill.solid()
            shape.fill.fore_color.rgb=RGBColor.from_string('EEEEEE')
        page=self.preview()
        self.assertLessEqual(len(page['elements']),1200)
        self.assertFalse(page['coverage']['completeObjectProjection'])
        self.assertTrue(any('1,200' in w for w in page['warnings']))

    def test_native_straight_connector_has_endpoints_and_arrow_in_preview(self):
        from pptx.enum.shapes import MSO_CONNECTOR
        from pptx.util import Pt
        from pptx.oxml.xmlchemy import OxmlElement
        line=self.slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,Pt(50),Pt(150),Pt(350),Pt(150))
        end=OxmlElement('a:tailEnd'); end.set('type','triangle')
        line._element.spPr.get_or_add_ln().append(end)
        before=self.slide._element.xml
        page=self.preview()
        element=next(e for e in page['elements'] if e['kind']=='line')
        self.assertEqual([[0,0],[300.0,0.0]],element['points'])
        self.assertEqual('triangle',element['endArrow'])
        self.assertEqual(before,self.slide._element.xml)

    def test_default_theme_fill_is_projected_with_approximation_notice(self):
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.util import Pt
        self.slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,Pt(40),Pt(100),Pt(300),Pt(100))
        before=self.slide._element.xml
        page=self.preview()
        element=next(e for e in page['elements'] if e['kind']=='shape')
        self.assertTrue(element['fill'])
        self.assertEqual('FFFFFF',page['background'])
        self.assertTrue(any(r['reason']=='theme_fill_inheritance' for r in page['coverage']['approximations']))
        self.assertEqual(before,self.slide._element.xml)


if __name__=='__main__':
    unittest.main()
