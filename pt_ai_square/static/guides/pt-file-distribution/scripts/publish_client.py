"""Prepare/review/publish a package through the employee-bound API. No LLM needed."""
import argparse
import getpass
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
import webbrowser
from urllib.parse import urlencode, urlsplit
from square_client import Client, ClientError, AuthenticationRequired, DEFAULT_CONFIG, open_auth_page


def read_json(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ClientError('JSON 최상위는 객체여야 합니다.')
    return value


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        json.dump(value, f, ensure_ascii=False, indent=2)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def multipart(client, endpoint, artifact, metadata=None):
    boundary = 'square' + uuid.uuid4().hex
    csrf_headers = {}
    if not client.token:
        csrf_headers['X-CSRF-Token'] = client.get('/api/bootstrap')['csrf']
    with tempfile.TemporaryFile() as body:
        if metadata is not None:
            body.write((f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n\r\n'
                        + json.dumps(metadata, ensure_ascii=False) + '\r\n').encode())
        if artifact:
            artifact = Path(artifact)
            filename = artifact.name.replace('"', '_').replace('\r', '_').replace('\n', '_')
            body.write((f'--{boundary}\r\nContent-Disposition: form-data; name="artifact"; filename="{filename}"\r\n'
                        'Content-Type: application/octet-stream\r\n\r\n').encode())
            with artifact.open('rb') as f:
                while chunk := f.read(1024 * 1024):
                    body.write(chunk)
            body.write(b'\r\n')
        body.write(f'--{boundary}--\r\n'.encode())
        length = body.tell()
        body.seek(0)
        with client.open(endpoint, body, {**csrf_headers, 'Content-Type': 'multipart/form-data; boundary='+boundary,
                                         'Content-Length': str(length)}) as response:
            return json.loads(response.read(4 * 1024 * 1024))


def canonical_package_id(tool):
    """Prefer the server identity; older servers expose only release declarations."""
    if 'packageId' in tool:
        return tool['packageId']
    versions = sorted(tool.get('versions', []), key=lambda v: v['n'])
    return next((v['package']['packageId'] for v in versions if v.get('package')), None)


def saved_bindings(state):
    rows = state.get('bindings', []) if state.get('schemaVersion') == 2 else [state]
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def same_source(binding, source_path):
    # A shared output/plan directory or a matching packageId is not proof that
    # two artifacts belong to the same project. This is only a candidate hint.
    old_path = binding.get('sourcePath')
    if not old_path and binding.get('sourceKey', '').startswith('file:'):
        old_path = binding['sourceKey'][5:]  # legacy single-MD binding
    return bool(source_path and isinstance(old_path, str) and old_path
                and os.path.normcase(old_path) == os.path.normcase(source_path))


def remember_binding(path, binding):
    previous = read_json(path) if Path(path).exists() else {}
    rows = [row for row in saved_bindings(previous)
            if not (row.get('baseUrl') == binding['baseUrl'] and row.get('employeeId') == binding['employeeId']
                    and row.get('sourcePath') == binding.get('sourcePath'))]
    # Keep independent artifacts in one working directory independent. The
    # latest top-level fields remain readable by older versions of the client.
    save(path, dict(binding, schemaVersion=2, bindings=[binding] + rows[:99]))


def prepare(client, artifact, metadata, plan_path, tool_id=None, new=False):
    """Inspect server-side; fill package fields. Never silently choose visibility."""
    plan_path = Path(plan_path).resolve()
    state_path = plan_path.parent / '.ai-square-publish-state.json'
    options = client.get('/api/catalog/options')
    package = None
    warning = ''
    fields = {}
    if artifact:
        artifact = Path(artifact).resolve()
        inspected = multipart(client, '/api/packages/inspect', artifact)
        fields = inspected.get('metadata', {})
        package = inspected.get('package')
        warning = inspected.get('warning', '')
    if new and tool_id:
        raise ClientError('--new와 --tool은 함께 사용할 수 없습니다.')
    if tool_id is not None and (type(tool_id) is not int or tool_id < 1):
        raise ClientError('--tool에는 기존 도구의 양의 정수 ID를 넣으세요.')
    state = read_json(state_path) if state_path.exists() else {}
    source_path = str(artifact) if artifact else None
    source_package_id = package.get('packageId') if package else None
    source_key = 'package:' + package['packageId'] if package else 'file:' + str(artifact) if artifact else 'named:' + str(metadata.get('name', ''))
    candidates = []
    binding_warning = ''
    if not new and tool_id is None:
        for binding in saved_bindings(state):
            if (binding.get('baseUrl') != client.url or binding.get('employeeId') != options['employee']['id']
                    or not same_source(binding, source_path) or type(binding.get('toolId')) is not int
                    or binding['toolId'] < 1):
                continue
            try:
                bound = client.details(binding['toolId'])
                if bound.get('ownerId') == options['employee']['id'] and bound.get('canManage'):
                    if not any(row['id'] == bound['id'] for row in candidates):
                        candidates.append(dict(id=bound['id'], name=bound['name'], revision=bound['revision'],
                                               packageId=canonical_package_id(bound), reason='same_source_path'))
                else:
                    binding_warning = '같은 자료 경로의 이전 연결을 현재 계정으로 업데이트할 수 없습니다. 대상을 다시 선택하세요.'
            except AuthenticationRequired:
                raise
            except ClientError:
                binding_warning = '같은 자료 경로의 이전 연결을 확인하지 못했습니다. 기존 도구 또는 별도 신규 등록을 선택하세요.'
        name = str(metadata.get('name') or fields.get('name') or '').strip()
        found = client.get('/api/publish-targets?' + urlencode({'packageId': source_package_id})).get('items', []) if source_package_id else []
        reason = 'package_id'
        if not found and name:
            # A freshly rebuilt ZIP may declare a different ID. Offer a name
            # candidate separately; never turn that source ID into an alias.
            found = client.get('/api/publish-targets?' + urlencode({'q': name})).get('items', [])
            reason = 'name'
        if found:
            seen = {row['id'] for row in candidates}
            for row in found:
                if row['id'] not in seen:
                    candidates.append(dict(row, reason=reason))
                    seen.add(row['id'])
    selection_required = bool(candidates or binding_warning) and not new and tool_id is None
    previous = {}
    revision = None
    if tool_id:
        previous = client.details(tool_id)
        if not previous.get('canManage') or previous.get('ownerId') != options['employee']['id']:
            raise ClientError('본인이 등록한 도구만 새 버전을 게시할 수 있습니다.')
        revision = previous['revision']
    keys = ['name','desc','platform','type','guide','environment','changes','workTags','orgId','categoryId','workflow']
    values = {k: previous[k] for k in keys if k in previous}
    # A manual MD/URL/command update keeps its flow unless explicitly replaced
    # or cleared. Recognized package metadata describes the new release and
    # overrides this fallback, including a package that omits workflow.
    values.update(fields)
    values.update(metadata)
    for key in ('packageId', 'sourcePackageId', 'packageIdentityChanged', 'toolId', 'expectedRevision'):
        values.pop(key, None)  # Server identity is never caller-authored registration metadata.
    if package:
        # Match the server's release contract, even if a draft contains an old
        # workflow. Editing a recognized ZIP's flow requires changing its manifest.
        values['workflow'] = package.get('workflow')
    values.setdefault('owner', options['employee']['name'])
    values['mode'] = 'file' if artifact else values.get('mode')
    values.pop('approval', None)  # Explicit publish --visibility is always required.
    missing = [k for k in ['name','desc','platform','type','guide','orgId','categoryId','mode'] if not values.get(k)]
    package_id = canonical_package_id(previous) or source_package_id
    identity_changed = bool(package_id and source_package_id and package_id != source_package_id)
    plan = dict(schemaVersion=2, baseUrl=client.url, employeeId=options['employee']['id'],
                toolId=tool_id, expectedRevision=revision, artifact=str(artifact) if artifact else None,
                artifactSha256=sha(artifact) if artifact else None, metadata=values,
                clientRequestId=str(uuid.uuid4()), statePath=str(state_path),
                packageId=package_id, sourcePackageId=source_package_id, packageIdentityChanged=identity_changed,
                sourcePath=source_path, sourceKey=source_key, requiresTargetSelection=selection_required)
    save(plan_path, plan)
    return dict(plan=str(plan_path), action='choose_target' if selection_required else 'new_version' if tool_id else 'new_tool', toolId=tool_id,
                metadata=values, missing=missing, requiredChoice='공개(public) 또는 조회 승인 필요(approval)',
                currentApproval=previous.get('approval') if previous else None, options=options, packageWarning=warning,
                packageId=package_id, sourcePackageId=source_package_id, packageIdentityChanged=identity_changed,
                candidates=candidates, requiresTargetSelection=selection_required, bindingWarning=binding_warning,
                notice='기존 도구의 새 버전이면 --tool ID, 별도 신규 등록이면 --new로 다시 준비하세요.' if selection_required else
                       '플랫폼의 고정 packageId를 유지하며 새 파일의 원본 선언과 바이트는 바꾸지 않습니다.' if identity_changed else '')


def publish(client, plan_path, visibility):
    if visibility not in {'public','approval'}:
        raise ClientError('공개 또는 조회 승인 필요 여부를 먼저 확인하세요.')
    plan = read_json(plan_path)
    if plan.get('requiresTargetSelection'):
        raise ClientError('기존 도구 또는 신규 등록을 먼저 선택하세요. prepare --tool ID 또는 --new로 다시 준비하세요.')
    identity = client.get('/api/catalog/options')['employee']
    if plan['baseUrl'] != client.url or plan['employeeId'] != identity['id']:
        raise ClientError('준비안의 서버 또는 사번이 다릅니다. 다시 준비하세요.')
    if plan.get('artifact') and sha(plan['artifact']) != plan['artifactSha256']:
        raise ClientError('준비 이후 파일이 변경되었습니다. prepare를 다시 실행하세요.')
    metadata = dict(plan['metadata'], approval=visibility=='approval',
                    clientRequestId=plan['clientRequestId'])
    target = plan.get('toolId')
    if target:
        metadata['expectedRevision'] = plan['expectedRevision']
    # The server, not this editable client, requires a signed-in web review.
    if target:
        metadata['toolId'] = target
    binding = hashlib.sha256(json.dumps(dict(metadata=metadata, artifactSha256=plan.get('artifactSha256')),
                                       sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if plan.get('draftId') and plan.get('draftBinding') == binding:
        draft = client.get('/api/publish-drafts/' + plan['draftId'])
    else:
        # A changed review needs a different request ID. Same bytes/metadata
        # retain the ID so an uncertain create response can be retried safely.
        if plan.get('draftBinding') and plan['draftBinding'] != binding:
            plan['clientRequestId'] = str(uuid.uuid4())
            metadata['clientRequestId'] = plan['clientRequestId']
            binding = hashlib.sha256(json.dumps(dict(metadata=metadata, artifactSha256=plan.get('artifactSha256')),
                                               sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        plan['draftBinding'] = binding
        save(plan_path, plan)
        draft = multipart(client, '/api/publish-drafts', plan.get('artifact'), metadata)
        plan['draftId'] = draft['id']
        save(plan_path, plan)
    if draft['status'] == 'pending':
        review_url = client.url + '/publish-review/' + draft['id']
        try:
            opened = bool(webbrowser.open(review_url))
        except Exception:
            opened = False
        return dict(status='approval_required', draftId=draft['id'], reviewUrl=review_url,
                    packageId=draft.get('packageId', plan.get('packageId')),
                    sourcePackageId=draft.get('sourcePackageId', plan.get('sourcePackageId')),
                    packageIdentityChanged=draft.get('packageIdentityChanged', plan.get('packageIdentityChanged', False)),
                    browserOpened=opened, notice='웹에서 파일·내용·공개 범위를 확인하고 승인한 뒤 같은 publish 명령을 다시 실행하세요. 아직 게시되지 않았습니다.')
    if draft['status'] not in {'approved', 'committing', 'committed'}:
        raise ClientError('등록 초안이 만료되었거나 사용할 수 없습니다. prepare부터 다시 진행하세요.')
    headers = {'Content-Type': 'application/json'}
    if not client.token:
        headers['X-CSRF-Token'] = client.get('/api/bootstrap')['csrf']
    with client.open('/api/publish-drafts/' + draft['id'] + '/commit', b'{}', headers) as response:
        result = json.loads(response.read(4 * 1024 * 1024))
    package_id = result.get('packageId', plan.get('packageId'))
    source_package_id = result.get('sourcePackageId', plan.get('sourcePackageId'))
    identity_changed = bool(package_id and source_package_id and package_id != source_package_id)
    remember_binding(plan['statePath'], dict(baseUrl=client.url, employeeId=identity['id'],
                                           toolId=result['id'], release=result['version'], packageId=package_id,
                                           sourcePackageId=source_package_id, sourcePath=plan.get('sourcePath'),
                                           sourceKey=plan['sourceKey']))
    return dict(result, packageId=package_id, sourcePackageId=source_package_id, packageIdentityChanged=identity_changed,
                approval=draft['metadata']['approval'], notice='게시 완료. 설치·자동 실행은 하지 않았습니다.')


def main(argv=None):
    p = argparse.ArgumentParser(description='배포 파일 자동 입력·게시 (공개 여부 명시 필수)')
    p.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    p.add_argument('--authenticate', action='store_true')
    s = p.add_subparsers(dest='command', required=True)
    s.add_parser('auth')
    a = s.add_parser('prepare')
    a.add_argument('--artifact', type=Path)
    a.add_argument('--metadata', type=Path, help='MD/URL/명령어 또는 추가 설명 JSON')
    a.add_argument('--plan', type=Path, required=True)
    a.add_argument('--org-id')
    a.add_argument('--category-id')
    a.add_argument('--tool', type=int)
    a.add_argument('--new', action='store_true')
    b = s.add_parser('publish')
    b.add_argument('--plan', type=Path, required=True)
    b.add_argument('--visibility', required=True, choices=['public','approval'])
    args = p.parse_args(argv)
    url = None
    try:
        config = read_json(args.config)
        url = config['baseUrl']
        allowed = config.get('allowHttpOrigin')
        client = Client(url, os.environ.get('PTAI_API_TOKEN', os.environ.get('PTAI_READ_TOKEN','')).strip(), timeout=120, allow_http_origin=allowed)
        if args.command == 'auth':
            print(json.dumps(open_auth_page(url, allowed), ensure_ascii=False))
            return 0
        if args.authenticate or (not client.token and urlsplit(client.url).hostname not in {'localhost','127.0.0.1','::1'}):
            info = open_auth_page(client.url, allowed) if not client.token else {'authUrl':client.url+'/local-access'}
            if not sys.stdin.isatty():
                raise ClientError('인증키 발급 화면: '+info['authUrl']+' · 업로드 포함 키를 사용자 터미널 또는 PTAI_API_TOKEN으로 입력하세요.')
            client = Client(url, getpass.getpass('업로드 포함 인증키: ').strip(), timeout=120, allow_http_origin=allowed)
        if args.command == 'prepare':
            fields = read_json(args.metadata) if args.metadata else {}
            if args.org_id: fields['orgId'] = args.org_id
            if args.category_id: fields['categoryId'] = args.category_id
            result = prepare(client, args.artifact, fields, args.plan, args.tool, args.new)
        else:
            result = publish(client, args.plan, args.visibility)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except AuthenticationRequired as error:
        print(json.dumps(dict(error=str(error), **open_auth_page(url, allowed)), ensure_ascii=False), file=sys.stderr)
    except (ClientError, OSError, ValueError, KeyError, HTTPException) as error:
        message = str(error) if isinstance(error, ClientError) else '설정·파일·응답을 확인하세요. 실패 시 같은 준비안으로 재시도할 수 있습니다.'
        print(json.dumps(dict(error=message), ensure_ascii=False), file=sys.stderr)
    return 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
