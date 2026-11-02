"""ai-square.json v1 contract; shared with the downloadable Skill, no execution."""
import json
import re
from pathlib import PurePosixPath

MANIFEST_NAME = 'ai-square.json'
FIELDS = {'schemaVersion','packageId','name','desc','platform','type','workTags',
          'environment','changes','entryPoint','guideFile','requiredFiles','requirements','workflow'}


def fail(message):
    raise ValueError('배포 정보: '+message)


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: fail(f'중복 항목 {key}를 제거하세요.')
        result[key]=value
    return result


def field(raw,key,limit,required=True):
    value=raw.get(key,'')
    if not isinstance(value,str) or len(value)>limit or (required and not value.strip()):
        fail(f'{key}는 {limit}자 이내의 '+('필수 ' if required else '')+'문자열이어야 합니다.')
    return value.strip()


def relative_file(value):
    if (not isinstance(value,str) or not value or len(value)>240 or '\\' in value
        or ':' in value or value.startswith('/') or any(ord(c)<32 for c in value)
        or any(p in {'','.','..'} for p in value.split('/'))):
        fail('파일 경로는 ZIP 기준 상대 경로로 적으세요. 예: scripts/main.py')
    return value


def normalize_workflow(value):
    """A small ordered text diagram, never executable markup or inferred code."""
    if value is None:
        return None
    if not isinstance(value,dict) or set(value)!={'steps'}:
        fail('workflow는 steps 목록만 가진 객체여야 합니다.')
    steps=value['steps']
    if not isinstance(steps,list) or not 1<=len(steps)<=8:
        fail('workflow.steps는 1~8개 단계입니다.')
    normalized=[]
    for step in steps:
        if not isinstance(step,dict) or set(step)-{'title','description'}:
            fail('동작 단계에는 title과 description만 사용할 수 있습니다.')
        title=field(step,'title',60)
        description=field(step,'description',240,False)
        if any(ord(c)<32 and c not in '\n\t' for c in title+description):
            fail('동작 단계에 제어 문자를 넣을 수 없습니다.')
        normalized.append({'title':title,'description':description})
    return {'steps':normalized}


def read_package(archive):
    """Return None for a legacy ZIP, or a validated declaration with guide text."""
    entries=archive.infolist()
    named=[e for e in entries if PurePosixPath(e.filename).name.casefold()==MANIFEST_NAME]
    if not named: return None
    if len(named)!=1 or named[0].filename!=MANIFEST_NAME:
        fail('ai-square.json을 ZIP 최상위에 하나만 넣으세요. 폴더째 압축하지 마세요.')
    if named[0].file_size>65536: fail('ai-square.json은 64KB 이하여야 합니다.')
    paths={};seen=set()
    for e in entries:
        name=e.filename.rstrip('/') if e.is_dir() else e.filename
        relative_file(name)
        if name.casefold() in seen: fail('ZIP에 이름이 중복된 파일·폴더가 있습니다.')
        seen.add(name.casefold())
        if not e.is_dir(): paths[name]=e
    try: raw=json.loads(archive.read(named[0]).decode('utf-8-sig'),object_pairs_hook=unique_object)
    except (UnicodeError,json.JSONDecodeError,RecursionError): fail('ai-square.json의 UTF-8 JSON 문법을 확인하세요.')
    if not isinstance(raw,dict): fail('JSON 최상위는 객체여야 합니다.')
    if set(raw)-FIELDS: fail('지원하지 않는 항목: '+', '.join(sorted(set(raw)-FIELDS)))
    if type(raw.get('schemaVersion')) is not int or raw['schemaVersion']!=1: fail('schemaVersion은 숫자 1이어야 합니다.')
    result={'schemaVersion':1}
    for key,limit in {'packageId':80,'name':50,'desc':200,'platform':20,'type':20,'environment':200,'changes':2000}.items():
        result[key]=field(raw,key,limit,key not in {'environment','changes'})
    if not re.fullmatch(r'[a-z][a-z0-9.-]{2,79}',result['packageId']): fail('packageId는 영문 소문자로 시작하는 3~80자의 소문자·숫자·점·하이픈입니다.')
    if result['platform'] not in {'Claude','ChatGPT','기타'}: fail('platform은 Claude / ChatGPT / 기타 중 선택하세요.')
    if result['type'] not in {'MCP/Tool','Skill','플러그인/하네스'}: fail('type은 MCP/Tool / Skill / 플러그인/하네스 중 선택하세요.')
    result['workflow']=normalize_workflow(raw.get('workflow'))
    for key,count,limit in [('workTags',8,30),('requirements',20,200),('requiredFiles',100,240)]:
        values=raw.get(key,[])
        if not isinstance(values,list) or len(values)>count or any(not isinstance(x,str) or not x.strip() or len(x)>limit for x in values):
            fail(f'{key}는 최대 {count}개, 각 {limit}자 이내의 문자열 목록입니다.')
        result[key]=list(dict.fromkeys(x.strip() for x in values))
    for key in ['entryPoint','guideFile']: result[key]=relative_file(field(raw,key,240))
    for path in [result['entryPoint'],result['guideFile'],*result['requiredFiles']]:
        relative_file(path)
        if path not in paths: fail(f'필수 파일이 없습니다: {path}')
        if paths[path].file_size==0: fail(f'필수 파일이 비어 있습니다: {path}')
    guide=paths[result['guideFile']]
    if guide.file_size>40000: fail('설치 안내 파일은 40KB 이하여야 합니다.')
    try: result['guide']=archive.read(guide).decode('utf-8-sig').strip()
    except UnicodeError: fail('설치 안내 파일은 UTF-8 텍스트로 저장하세요.')
    if not result['guide'] or len(result['guide'])>10000: fail('설치 안내는 1~10000자여야 합니다.')
    return result


def registration_fields(package):
    return {**{k:package[k] for k in ['name','desc','platform','type','workTags','environment','changes','guide']},
            'workflow':package.get('workflow')}
