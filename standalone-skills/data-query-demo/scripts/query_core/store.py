"""개인 연결과 저장 쿼리 관리. 배포 폴더 밖의 지정한 저장소만 사용합니다."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
import uuid
from contextlib import contextmanager


ENGINES = {'oracle', 'datalake', 'ehub'}


def safe_path(path):
    path = Path(os.path.abspath(path))
    for p in (path, *path.parents):
        if os.path.lexists(p) and (p.is_symlink() or getattr(p.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('링크로 연결된 저장 경로는 사용할 수 없습니다.')
    return path


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def atomic_json(path, value):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.writing-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, limit=100_000):
    path = safe_path(path)
    with path.open('rb') as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('입력 파일이 너무 큽니다. 필요한 설정이나 조건만 넣어 주세요.')
    value = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError('입력 파일은 JSON 객체 형식이어야 합니다.')
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', value):
        raise ValueError('연결 ID는 영문 소문자로 시작하는 40자 이내 이름이어야 합니다.')
    return value


def label(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80 or any(ord(c) < 32 for c in value):
        raise ValueError('표시 이름은 줄바꿈 없이 1~80자로 입력해 주세요.')
    return value.strip()


class Store:
    def __init__(self, root, *, demo=False):
        self.root = safe_path(root)
        self.demo = demo
        self.root.mkdir(parents=True, exist_ok=True)
        marker = self.root / 'mode.json'
        if marker.exists():
            if read_json(marker).get('mode') != ('demo' if demo else 'live'):
                raise ValueError('실습과 실제 연결은 같은 저장소를 사용할 수 없습니다.')
        else:
            atomic_json(marker, {'mode': 'demo' if demo else 'live'})
        self.db = safe_path(self.root / 'catalog.sqlite3')
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS queries(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL, profile TEXT NOT NULL, body TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, body TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0);
            ''')
        ignore = self.root / '.gitignore'
        if not ignore.exists():
            ignore.write_text('*\n', encoding='utf-8')

    @contextmanager
    def connect(self):
        safe_path(self.db)
        conn = sqlite3.connect(self.db, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def save_profile(self, profile, secrets=None, *, replace=False):
        allowed = {'id','name','engine','api_base','cluster','allow_http','allow_cluster_start',
                   'tls_ca','connect_timeout','mode','client_lib_dir','demo_database'}
        if not isinstance(profile, dict) or set(profile) - allowed:
            raise ValueError('지원하는 연결 설정만 입력해 주세요.')
        profile = dict(profile)
        identifier(profile.get('id'))
        profile['name'] = label(profile.get('name'))
        if profile.get('engine') not in ENGINES:
            raise ValueError('Oracle, Datalake 또는 E-HUB 연결을 선택해 주세요.')
        if not self.demo and 'demo_database' in profile:
            raise ValueError('실습 데이터는 실제 연결에 등록할 수 없습니다.')
        for key in ('allow_http', 'allow_cluster_start'):
            if key in profile and type(profile[key]) is not bool:
                raise ValueError('연결 동의 항목의 형식을 확인해 주세요.')
        with self.connect() as conn:
            existing = conn.execute('SELECT id FROM profiles WHERE id=?', (profile['id'],)).fetchone()
            if existing and not replace:
                raise ValueError('이미 있는 연결입니다. 수정할 연결을 명시해 주세요.')
            for row in conn.execute('SELECT body FROM profiles WHERE id<>?', (profile['id'],)):
                other = json.loads(row['body'])
                if other['engine'] == profile['engine'] and other['name'] == profile['name']:
                    raise ValueError('이 조회 스킬에 같은 DB 이름이 있습니다. 구분할 수 있는 이름을 입력해 주세요.')
            if secrets is not None:
                self.write_secrets(profile['id'], secrets)
            conn.execute('INSERT OR REPLACE INTO profiles VALUES (?,?)', (profile['id'], json.dumps(profile, ensure_ascii=False)))
        return {'id': profile['id'], 'name': profile['name'], 'engine': profile['engine']}

    def write_secrets(self, profile_id, secrets):
        if self.demo:
            if secrets:
                raise ValueError('실습에는 인증정보를 저장하지 않습니다.')
            return
        if not isinstance(secrets, dict) or set(secrets) - {'user','password','dsn','user_id','token'}:
            raise ValueError('지원하는 인증 설정만 입력해 주세요.')
        if any(not isinstance(v, str) or len(v) > 16000 for v in secrets.values()):
            raise ValueError('인증 설정의 형식을 확인해 주세요.')
        target = safe_path(self.root / 'connections' / (identifier(profile_id) + '.env'))
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=target.parent, prefix='.secret-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as out:
                out.write('# 개인 설정입니다. 채팅, Git, 배포 ZIP에 넣지 마세요.\n')
                for k, v in secrets.items():
                    out.write(k.upper() + '=' + json.dumps(v, ensure_ascii=False) + '\n')
            os.chmod(temp, 0o600)
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def secrets(self, profile_id):
        if self.demo:
            return {}
        target = safe_path(self.root / 'connections' / (identifier(profile_id) + '.env'))
        if not target.is_file():
            raise ValueError('연결 설정이 없습니다. 연결 설정창에서 먼저 저장해 주세요.')
        if target.stat().st_size > 100_000:
            raise ValueError('연결 설정 파일이 너무 큽니다.')
        result = {}
        for line in target.read_text(encoding='utf-8-sig').splitlines():
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            key, sep, value = line.partition('=')
            key = key.strip().lower()
            if not sep or key not in {'user','password','dsn','user_id','token'}:
                raise ValueError('연결 설정 파일의 항목을 확인해 주세요.')
            value = value.strip()
            result[key] = json.loads(value) if value.startswith('"') else value
            if not isinstance(result[key], str):
                raise ValueError('인증 설정은 문자열이어야 합니다.')
        for key in ('user','password','dsn','user_id','token'):
            override = os.environ.get('DATAQUERY_' + profile_id.upper().replace('-', '_') + '_' + key.upper())
            if override is not None:
                result[key] = override
        return result

    def profile(self, profile_id):
        with self.connect() as conn:
            row = conn.execute('SELECT body FROM profiles WHERE id=?', (identifier(profile_id),)).fetchone()
        if row is None:
            raise ValueError('선택한 연결이 없습니다. 다른 DB로 자동 변경하지 않았습니다.')
        return json.loads(row['body'])

    def profiles(self, engine):
        with self.connect() as conn:
            bodies = [json.loads(r['body']) for r in conn.execute('SELECT body FROM profiles ORDER BY rowid')]
        return [{'id': p['id'], 'name': p['name'], 'engine': p['engine']} for p in bodies if engine == 'demo' or p['engine'] == engine]

    def query(self, query_id, engine):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM queries WHERE id=?', (int(query_id),)).fetchone()
        if row is None:
            raise ValueError('저장된 조회 번호가 없습니다.')
        body = json.loads(row['body'])
        profile = self.profile(body['profile'])
        if engine != 'demo' and profile['engine'] != engine:
            raise ValueError('다른 조회 스킬에 저장된 쿼리입니다. 해당 스킬로 실행해 주세요.')
        return dict(body, id=row['id'], updated=row['updated'])

    def queries(self, engine):
        result = []
        with self.connect() as conn:
            rows = list(conn.execute('SELECT id,name,profile FROM queries ORDER BY id'))
        for row in rows:
            p = self.profile(row['profile'])
            if engine == 'demo' or p['engine'] == engine:
                result.append({'id':row['id'], 'name':row['name'], 'sourceName':p['name'],
                               'display':f"{row['id']}. {row['name']} — {p['name']}"})
        return result

    def save_query(self, spec, engine, *, query_id=None):
        from .sql import validate_sql, parameter_names, _definitions
        if not isinstance(spec, dict) or set(spec) - {'name','profile','sql','parameters','description'}:
            raise ValueError('조회 이름, 연결, SQL, 조건 정의만 등록해 주세요.')
        spec = dict(spec)
        spec['name'] = label(spec.get('name'))
        profile = self.profile(spec.get('profile'))
        if engine != 'demo' and profile['engine'] != engine:
            raise ValueError('이 스킬에 맞는 연결을 선택해 주세요.')
        spec['sql'] = validate_sql(spec.get('sql'), profile['engine'])
        definitions = spec.get('parameters', {})
        if not isinstance(definitions, dict) or set(definitions) != set(parameter_names(spec['sql'], profile['engine'])):
            raise ValueError('SQL의 변수와 조건 정의가 일치해야 합니다. 바뀌는 조건을 확인해 주세요.')
        spec['parameters'] = definitions
        _definitions(definitions)
        with self.connect() as conn:
            if conn.execute('SELECT 1 FROM queries WHERE name=? AND profile=? AND id<>?',
                            (spec['name'], spec['profile'], query_id or -1)).fetchone():
                raise ValueError('같은 연결에 같은 이름의 쿼리가 있습니다. 수정할 번호를 지정해 주세요.')
            if query_id is None:
                query_id = conn.execute('INSERT INTO queries(name,profile,body,updated) VALUES (?,?,?,?)',
                    (spec['name'],spec['profile'],json.dumps(spec,ensure_ascii=False),time.time())).lastrowid
            else:
                self.query(query_id, engine)
                conn.execute('UPDATE queries SET name=?,profile=?,body=?,updated=? WHERE id=?',
                    (spec['name'],spec['profile'],json.dumps(spec,ensure_ascii=False),time.time(),int(query_id)))
        return {'id':query_id, 'name':spec['name'], 'sourceName':profile['name'], 'parameters':definitions, 'executed':False}

    def save_plan(self, body):
        plan_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute('INSERT INTO plans(id,body) VALUES (?,?)', (plan_id,json.dumps(body, ensure_ascii=False)))
        return plan_id

    def get_plan(self, plan_id):
        if not isinstance(plan_id, str) or not re.fullmatch(r'[a-f0-9]{32}', plan_id):
            raise ValueError('조회 준비 번호가 올바르지 않습니다.')
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM plans WHERE id=?',(plan_id,)).fetchone()
        if row is None or row['used']:
            raise ValueError('조회 준비가 없거나 이미 사용했습니다. 새 조건으로 준비해 주세요.')
        return json.loads(row['body'])

    def claim_plan(self, plan_id):
        with self.connect() as conn:
            if conn.execute('UPDATE plans SET used=1 WHERE id=? AND used=0',(plan_id,)).rowcount != 1:
                raise ValueError('이미 실행한 조회 준비입니다. 중복 실행하지 않았습니다.')
