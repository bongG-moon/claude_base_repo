"""Create a new blank presentation without opening an installed .pptx template.

This constructs ordinary, unencrypted OOXML for a new document. It never reads,
decrypts, copies, or changes a protected input or an Office security setting.
"""
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
from xml.sax.saxutils import quoteattr

A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def blank_presentation(font='Malgun Gothic'):
    """Build the small package in memory; no site-packages default.pptx is read."""
    from pptx import Presentation
    ns = f'xmlns:a="{A}" xmlns:p="{P}" xmlns:r="{R}"'
    tree = ('<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
            '<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr>'
            '<a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm>'
            '</p:grpSpPr></p:spTree>')
    def rels(items):
        return ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + ''.join(f'<Relationship Id="rId{i}" Type="{R}/{kind}" Target="{target}"/>'
                          for i, (kind, target) in enumerate(items, 1)) + '</Relationships>')
    types = {'ppt/presentation.xml': 'presentation', 'ppt/slideMasters/slideMaster1.xml': 'slideMaster',
             'ppt/slideLayouts/slideLayout1.xml': 'slideLayout'}
    content_types = ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="xml" ContentType="application/xml"/>'
                     + ''.join(f'<Override PartName="/{path}" ContentType="application/vnd.openxmlformats-officedocument.presentationml.{kind}+xml"/>'
                               for path, kind in types.items())
                     + '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/></Types>')
    # The primary presentation content type has the additional .main suffix.
    content_types = content_types.replace('presentationml.presentation+xml', 'presentationml.presentation.main+xml')
    colors = [('dk1','111111'),('lt1','FFFFFF'),('dk2','303030'),('lt2','F5F5F5'),
              ('accent1','555555'),('accent2','777777'),('accent3','999999'),
              ('accent4','BBBBBB'),('accent5','DDDDDD'),('accent6','EEEEEE'),
              ('hlink','444444'),('folHlink','666666')]
    face=quoteattr(font)
    fonts = (f'<a:latin typeface={face}/><a:ea typeface={face}/>'
             f'<a:cs typeface={face}/><a:font script="Hang" typeface={face}/>')
    fill = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    line = '<a:ln w="12700" cap="flat" cmpd="sng" algn="ctr">' + fill + '<a:prstDash val="solid"/></a:ln>'
    theme = (f'<a:theme xmlns:a="{A}" name="Blank Korean presentation"><a:themeElements>'
             '<a:clrScheme name="Neutral">' + ''.join(f'<a:{key}><a:srgbClr val="{value}"/></a:{key}>' for key,value in colors)
             + '</a:clrScheme><a:fontScheme name="Korean"><a:majorFont>' + fonts + '</a:majorFont><a:minorFont>'
             + fonts + '</a:minorFont></a:fontScheme><a:fmtScheme name="Plain"><a:fillStyleLst>' + fill*3
             + '</a:fillStyleLst><a:lnStyleLst>' + line*3 + '</a:lnStyleLst><a:effectStyleLst>'
             + '<a:effectStyle><a:effectLst/></a:effectStyle>'*3 + '</a:effectStyleLst><a:bgFillStyleLst>'
             + fill*3 + '</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>')
    parts = {
        '[Content_Types].xml': content_types,
        '_rels/.rels': rels([('officeDocument','ppt/presentation.xml')]),
        'ppt/presentation.xml': f'<p:presentation {ns}><p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst><p:sldSz cx="12192000" cy="6858000"/><p:notesSz cx="6858000" cy="9144000"/><p:defaultTextStyle/></p:presentation>',
        'ppt/_rels/presentation.xml.rels': rels([('slideMaster','slideMasters/slideMaster1.xml')]),
        'ppt/slideMasters/slideMaster1.xml': f'<p:sldMaster {ns}><p:cSld name="Blank">{tree}</p:cSld><p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/><p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst><p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>',
        'ppt/slideMasters/_rels/slideMaster1.xml.rels': rels([('slideLayout','../slideLayouts/slideLayout1.xml'),('theme','../theme/theme1.xml')]),
        'ppt/slideLayouts/slideLayout1.xml': f'<p:sldLayout {ns} type="blank" preserve="1"><p:cSld name="Blank">{tree}</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>',
        'ppt/slideLayouts/_rels/slideLayout1.xml.rels': rels([('slideMaster','../slideMasters/slideMaster1.xml')]),
        'ppt/theme/theme1.xml': theme,
    }
    stream = BytesIO()
    with ZipFile(stream, 'w', ZIP_DEFLATED) as package:
        for name, xml in parts.items():
            package.writestr(name, '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + xml)
    stream.seek(0)
    return Presentation(stream)
