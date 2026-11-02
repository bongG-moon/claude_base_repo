"""Shared HTML/native geometry; no Office or external service is started."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import sys
import tempfile
import unittest
from xml.etree import ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'company-agent-plugin/scripts'))
from company_agent import ppt_primitives as geometry, ppt_scene
from company_agent.business_artifacts import ArtifactError


class SvgReader(HTMLParser):
    def __init__(self):
        super().__init__();self.paths=[];self.forbidden=[];self.ids=[]

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='path':self.paths.append(attrs.get('d'))
        if attrs.get('id'):self.ids.append(attrs['id'])
        if tag in ('script','image','foreignobject') or any(k.startswith('on') for k in attrs):
            self.forbidden.append(tag)


class ComplexPrimitiveTests(unittest.TestCase):
    def setUp(self):
        parent=ROOT/'.smoke/ppt-enhance/temp';parent.mkdir(parents=True,exist_ok=True)
        self.temporary=tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.path=Path(self.temporary.name)/'native.pptx'
        self.palette={'background':'FFFFFF','text':'333333','accent':'087F8C'}

    def normalize(self,**values):
        return geometry.normalize_primitive({'kind':'shape','x':40,'y':60,'w':200,'h':120,'fill':'accent',**values},960,540,self.palette)

    def native(self,items):
        from pptx import Presentation
        from pptx.util import Pt
        deck=Presentation();deck.slide_width=Pt(960);deck.slide_height=Pt(540)
        slide=deck.slides.add_slide(deck.slide_layouts[6])
        for e in items:
            geometry.add_primitive(slide,e,tuple(Pt(e[k]) for k in ('x','y','w','h')))
        deck.save(self.path)
        return Presentation(self.path)

    def test_named_contours_keep_shared_points_and_are_native_editable_shapes(self):
        from pptx.enum.shapes import MSO_SHAPE_TYPE
        items=[self.normalize(shape=name) for name in geometry.SHAPES]
        deck=self.native(items)
        self.assertEqual(len(items),len(deck.slides[0].shapes))
        for e,shape in zip(items,deck.slides[0].shapes):
            with self.subTest(name=e['shape']):
                self.assertAlmostEqual(shape.left.pt,e['x'])
                self.assertAlmostEqual(shape.top.pt,e['y'])
                self.assertAlmostEqual(shape.width.pt,e['w'])
                self.assertAlmostEqual(shape.height.pt,e['h'])
                self.assertNotEqual(MSO_SHAPE_TYPE.PICTURE,shape.shape_type)
                reader=SvgReader();reader.feed(geometry.render_primitive_html(e,{}))
                self.assertFalse(reader.forbidden)
                if e['shape'] in ('rect','roundRect','ellipse'):
                    self.assertEqual('native-preset',e['representation'])
                    self.assertEqual(MSO_SHAPE_TYPE.AUTO_SHAPE,shape.shape_type)
                else:
                    self.assertEqual('native-freeform',e['representation'])
                    self.assertEqual(MSO_SHAPE_TYPE.FREEFORM,shape.shape_type)
                    path=shape._element.xpath('.//a:custGeom/a:pathLst/a:path')[0]
                    self.assertEqual(str(round(e['w']*1000)),path.get('w'))
                    self.assertEqual(str(round(e['h']*1000)),path.get('h'))
                    native_points=[(int(p.get('x'))/1000,int(p.get('y'))/1000) for p in path.xpath('.//a:pt')]
                    source_points=[(c[1],c[2]) for c in e['commands'] if c[0] in ('M','L')]
                    self.assertEqual(len(source_points),len(native_points))
                    for expected,actual in zip(source_points,native_points):
                        self.assertAlmostEqual(expected[0],actual[0],places=3)
                        self.assertAlmostEqual(expected[1],actual[1],places=3)
                    self.assertEqual([geometry._path_d(e['commands'])],reader.paths)

    def test_legacy_round_rect_radius_shadow_and_alpha_are_unchanged(self):
        e=self.normalize(shape='roundRect',radius=16,opacity=.4,border='123456',borderWidth=1.5,
                         shadow={'color':'111111','opacity':.2,'blur':7,'x':-2,'y':3})
        shape=self.native([e]).slides[0].shapes[0]
        self.assertAlmostEqual(16/120,shape.adjustments[0],places=4)
        self.assertEqual('40000',shape._element.xpath('.//a:solidFill/a:srgbClr/a:alpha')[0].get('val'))
        self.assertTrue(shape._element.xpath('.//a:outerShdw'))
        html=geometry.render_primitive_html(e,{})
        self.assertIn('rx="16"',html)
        self.assertIn('drop-shadow',html)
        self.assertIn('fill-opacity="0.4"',html)

    def test_line_is_a_real_native_connector_with_direction_and_dash(self):
        e=self.normalize(kind='line',points=[[0,120],[200,0]],fill=None,border='accent',borderWidth=2,
                         startArrow='triangle',endArrow='triangle',dash='dash')
        shape=self.native([e]).slides[0].shapes[0]
        self.assertTrue(shape._element.tag.endswith('}cxnSp'))
        self.assertEqual(2,len(shape._element.xpath('.//a:headEnd[@type="triangle"] | .//a:tailEnd[@type="triangle"]')))
        self.assertEqual('dash',shape._element.xpath('.//a:prstDash')[0].get('val'))
        fragment=geometry.render_primitive_html(e,{})
        self.assertEqual(2,fragment.count('<polygon '))
        self.assertIn('stroke-dasharray="8 4"',fragment)

    def test_bent_line_and_curves_keep_editable_native_path_segments(self):
        line=self.normalize(kind='line',points=[[0,0],[100,0],[100,120],[200,120]],fill=None,border='accent',borderWidth=2)
        path=self.normalize(kind='path',commands=[['M',0,0],['C',20,120,180,0,200,120],['Q',100,30,0,0],['Z']],
                            fill='accent',border='text',borderWidth=1)
        deck=self.native([line,path]);shapes=deck.slides[0].shapes
        self.assertTrue(shapes[0]._element.xpath('.//a:custGeom/a:pathLst/a:path/a:lnTo'))
        self.assertTrue(shapes[1]._element.xpath('.//a:cubicBezTo'))
        self.assertTrue(shapes[1]._element.xpath('.//a:quadBezTo'))
        self.assertTrue(shapes[1]._element.xpath('.//a:close'))
        reader=SvgReader();reader.feed(geometry.render_primitive_html(path,{}))
        self.assertEqual([geometry._path_d(path['commands'])],reader.paths)
        self.assertFalse(reader.forbidden)

    def test_polyline_points_can_make_a_closed_custom_contour(self):
        e=self.normalize(kind='path',points=[[0,0],[170,10],[200,90],[50,120]],closed=True)
        self.assertTrue(e['closed'])
        self.assertEqual('Z',e['commands'][-1][0])
        self.assertTrue(self.native([e]).slides[0].shapes[0]._element.xpath('.//a:custGeom'))

    def test_grouping_keeps_contours_and_lines_as_separate_editable_children(self):
        items=[self.normalize(shape='chevron',group='처리단계'),
               self.normalize(kind='line',points=[[0,0],[200,120]],group='처리단계',fill=None,border='accent')]
        from pptx import Presentation
        from pptx.util import Pt
        deck=Presentation();slide=deck.slides.add_slide(deck.slide_layouts[6])
        for e in items:
            geometry.add_primitive(slide,e,tuple(Pt(e[k]) for k in ('x','y','w','h')))
        self.assertEqual(1,ppt_scene.group_shapes(slide,items))
        deck.save(self.path)
        group=Presentation(self.path).slides[0].shapes[0]
        self.assertEqual('처리단계',group.name)
        self.assertEqual(2,len(group.shapes))
        self.assertFalse(group._element.xpath('.//a:grpSpLocks[@noUngrp="1"]'))

    def test_paths_reject_unbounded_or_executable_input_before_rendering(self):
        cases=[{'kind':'path','commands':[['M',0,0],['X',1,1]]},
               {'kind':'path','commands':[['M',0,0],['L',float('nan'),1]]},
               {'kind':'path','commands':[['M',0,0],['L',500,1]]},
               {'kind':'path','commands':[['M',0,0],['L',2,3]],'fill':'accent','closed':False},
               {'kind':'path','commands':[['M',0,0],['L',2,3],['Z']],'closed':False},
               {'kind':'path','commands':[['M',0,0],['L',2,3]],'points':[[0,0],[1,1]]},
               {'kind':'path','commands':[['M',0,0]]},
               {'kind':'path','commands':[[[],0,0],['L',2,3]]},
               {'kind':'path','commands':'<svg onload="alert(1)">'},
               {'kind':'path','points':[[0,0],[True,1]]},
               {'kind':'path','points':[[0,0],[1,1]],'closed':'true'},
               {'kind':'path','points':[[0,0],[1,1]]*200}]
        for change in cases:
            with self.subTest(change=change),self.assertRaises(ArtifactError):
                self.normalize(**change)
        self.assertFalse(self.path.exists())

    def test_unknown_shapes_line_markers_and_css_colors_are_not_silently_changed(self):
        cases=[{'shape':'star'}, {'fill':'red;display:none'}, {'opacity':float('inf')},
               {'dash':'unsafe'}, {'kind':'line','points':[[0,0],[0,0]]},
               {'kind':'line','startArrow':'anything'}, {'kind':'line','borderWidth':0},
               {'kind':'line','points':[[0,0],[1,1]],'group':'bad/group'},
               {'shadow':{'color':'url(http://example.com)'}}]
        for change in cases:
            with self.subTest(change=change),self.assertRaises(ArtifactError):
                self.normalize(**change)

    def test_named_arrows_have_correct_direction_and_distinct_geometry(self):
        names=('rightArrow','leftArrow','upArrow','downArrow','chevron','diamond')
        values={name:geometry._path_d(self.normalize(shape=name)['commands']) for name in names}
        self.assertEqual(len(names),len(set(values.values())))
        right=self.normalize(shape='rightArrow')['commands']
        left=self.normalize(shape='leftArrow')['commands']
        self.assertEqual([200-c[1] for c in right if len(c)>1],[c[1] for c in left if len(c)>1])


if __name__=='__main__':
    unittest.main()
