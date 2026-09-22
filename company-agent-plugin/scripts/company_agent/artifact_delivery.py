"""One requested deliverable; drafts and checks stay in a local work area.

This is file lifecycle management, not an approval or permission override.
Existing user files are never replaced or deleted. No model/service calls.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import uuid

from .business_artifacts import ArtifactError, _failure, _publish, _source, _target
from .business_safety import safe_path, blocked_input
from .paths import atomic_write_json
from .state import _interprocess_lock, _thread_lock_for
from . import artifact_cleanup


def _hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def start(root, output):
    try:
        output = safe_path(output)
        if output.suffix.lower() not in ('.html', '.pptx'):
            raise ArtifactError('output_format', '최종 결과는 HTML 또는 PPTX 파일로 지정해 주세요.')
        _target(output, output.suffix.lower())
        base = safe_path(Path(root) / 'tmp' / 'artifact-work')
        folder = safe_path(base / uuid.uuid4().hex)
        folder.mkdir(parents=True, exist_ok=False)
        work = folder / 'work.json'
        atomic_write_json(work, {'schema':2, 'output':str(output), 'draft':None,
                                 'candidate':None, 'published':None, 'ownedFiles':[]})
        return {'ok':True, 'status':'workspace_ready', 'workFile':str(work),
                'jobPath':str(folder/'job.json'), 'workingDirectory':str(folder),
                'finalOutputPath':str(output), 'finalCreated':False,
                'message':'이 작업의 초안·수정·검사는 같은 workFile을 사용합니다. 확인 후 artifact-publish로 최종 파일 한 개만 전달하세요.'}
    except Exception as exc:
        return _failure(exc)


@contextmanager
def _locked(root, work_file):
    work = safe_path(work_file, exists=True)
    base = safe_path(Path(root)/'tmp'/'artifact-work')
    if (work.name != 'work.json' or work.parent.parent != base
            or not re.fullmatch('[a-f0-9]{32}',work.parent.name) or not work.is_file()):
        raise ArtifactError('invalid_artifact_work', '이번 작업에서 반환된 workFile을 그대로 사용해 주세요.')
    lock = safe_path(work.parent/'work.lock')
    with _thread_lock_for(lock), _interprocess_lock(lock):
        safe_path(work, exists=True)
        if work.stat().st_size > 128*1024:
            raise ArtifactError('invalid_artifact_work', '작업 기록의 크기를 확인해 주세요.')
        try:
            data = json.loads(work.read_text(encoding='utf-8'))
        except (ValueError, UnicodeError):
            raise ArtifactError('invalid_artifact_work', '작업 기록의 형식을 확인해 주세요.') from None
        if (not isinstance(data,dict) or type(data.get('schema')) is not int or data['schema'] not in (1,2)
                or not isinstance(data.get('output'),str) or not Path(data['output']).is_absolute()
                or Path(data['output']).suffix.lower() not in ('.html','.pptx')):
            raise ArtifactError('invalid_artifact_work', '작업 기록의 형식을 확인해 주세요.')
        safe_path(data['output'])
        for name in ('draft','candidate','published'):
            record = data.get(name)
            if record is None:
                continue
            if (not isinstance(record,dict) or not isinstance(record.get('sha256'),str)
                    or not re.fullmatch('[a-f0-9]{64}',record['sha256'])
                    or not isinstance(record.get('status'),str)
                    or not isinstance(record.get('warnings',[]),list)
                    or any(not isinstance(value,str) for value in record.get('warnings',[]))
                    or (name != 'published' and (not isinstance(record.get('path'),str)
                        or not Path(record['path']).is_absolute()))):
                raise ArtifactError('invalid_artifact_work', '작업 기록의 형식을 확인해 주세요.')
        yield work, data


def _completed(data, work=None):
    output = _source(Path(data['output']), ('.html','.pptx'))
    record = data['published']
    if _hash(output) != record['sha256']:
        raise ArtifactError('delivered_file_changed', '전달한 결과 파일이 이후 변경되었습니다. 덮어쓰거나 새 사본을 만들지 않았습니다.')
    result = {'ok':True, 'status':record['status'], 'outputPath':str(output),
            'alreadyDelivered':True, 'deliveryStatus':'published', 'deliverables':[str(output)],
            'message':'이미 전달한 결과입니다. 새 내용으로 바꾸는 다음 요청은 새 작업으로 시작하세요.',
            'warnings':record.get('warnings',[])}
    if work is not None:
        result['cleanup'] = artifact_cleanup.after_publish(work, data)
    return result


def build(root, work_file, operation, spec=None, template=None, *, spec_path=None):
    """Every attempt is internal. Only the newest successful candidate can publish."""
    try:
        with _locked(root, work_file) as (work, data):
            if data.get('published'):
                return _completed(data, work)
            suffix = Path(data['output']).suffix.lower()
            allowed = {'ppt','ppt-design-preview','ppt-fit-images'} if suffix == '.pptx' else {'html','ppt-template'}
            # A failed revision must not accidentally deliver the prior candidate.
            data['candidate'] = None
            if operation == 'ppt-design-preview':
                data['draft'] = None
            atomic_write_json(work,data)
            if operation not in allowed:
                raise ArtifactError('artifact_kind_mismatch', '이번 작업에서 정한 최종 파일 형식과 제작 명령이 다릅니다.')
            if spec_path is not None:
                from .business import _spec
                spec = _spec(spec_path)
            if not isinstance(spec,dict):
                raise ArtifactError('invalid_spec', '제작할 내용의 형식을 확인해 주세요.')
            if (blocked := blocked_input(spec)) is not None:
                return blocked
            if operation == 'ppt':
                review = spec.get('designReview')
                if not data.get('draft') or not isinstance(review,dict) or review.get('previewPath') != data['draft']['path']:
                    raise ArtifactError('artifact_preview_required', '같은 작업의 최신 HTML 초안을 확인한 뒤 PPT를 제작해 주세요.')
            attempt = safe_path(work.parent/'attempts'/uuid.uuid4().hex)
            attempt.mkdir(parents=True,exist_ok=False)
            from .business_artifacts import create_html, create_ppt
            from .ppt_html import create_draft, save_template
            output = attempt/('draft.html' if operation == 'ppt-design-preview' else 'result'+suffix)
            if operation == 'html':
                result = create_html(spec,output,require_choices=True)
            elif operation == 'ppt-design-preview':
                result = create_draft(spec,output,template)
            elif operation == 'ppt-template':
                result = save_template(spec,output,template)
            elif operation == 'ppt-fit-images':
                from .ppt_image_edit import resize
                result = resize(spec,output,preview_directory=attempt/'review')
            else:
                result = create_ppt(spec,output,template,require_choices=True,preview_directory=attempt/'review')
            if result.get('ok') and output.is_file():
                record = {'path':str(output), 'sha256':_hash(output), 'status':result['status'],
                          'warnings':result.get('warnings',[]), 'operation':operation}
                data['draft' if operation == 'ppt-design-preview' else 'candidate'] = record
                artifact_cleanup.register(work, data, attempt, output, result)
                atomic_write_json(work,data)
                result.update(deliveryStatus='internal', finalOutputPath=data['output'], workFile=str(work),
                              deliverables=[], nextAction='confirm-draft' if operation == 'ppt-design-preview' else 'inspect-then-artifact-publish')
            return result
    except Exception as exc:
        return _failure(exc)


def publish(root, work_file):
    """Publish once, idempotently; do not regenerate, rename, or overwrite on retry."""
    try:
        with _locked(root,work_file) as (work,data):
            if data.get('published'):
                return _completed(data, work)
            record = data.get('candidate')
            if not isinstance(record,dict):
                raise ArtifactError('artifact_not_ready', '최종 후보가 아직 없습니다. 초안 또는 실패한 수정 결과는 전달하지 않습니다.')
            source = safe_path(record['path'],exists=True)
            expected = work.parent/'attempts'
            output = safe_path(data['output'])
            if (source.parent.parent != expected or not re.fullmatch('[a-f0-9]{32}',source.parent.name)
                    or source.name != 'result'+output.suffix.lower()):
                raise ArtifactError('invalid_artifact_work', '이번 작업에서 생성한 최종 후보만 전달할 수 있습니다.')
            source = _source(source,('.html','.pptx'))
            if _hash(source) != record['sha256']:
                raise ArtifactError('artifact_candidate_changed', '검사 대상 파일이 생성 후 변경되었습니다. 다시 제작·확인해 주세요.')
            if output.exists():
                # Recover a lost receipt only for identical bytes; no mutation.
                if not output.is_file() or _hash(output) != record['sha256']:
                    raise ArtifactError('output_exists', '최종 위치에 다른 파일이 있습니다. 기존 파일을 보존했으며 새 버전도 임의 생성하지 않았습니다.')
            else:
                _target(output, output.suffix.lower())
                _publish(source,output)
            if _hash(output) != record['sha256']:
                raise ArtifactError('delivered_file_changed', '최종 파일 확인 중 변경이 발견되어 임시 파일을 보존했습니다.')
            data['published'] = {k:record[k] for k in ('sha256','status','warnings')}
            atomic_write_json(work,data)
            return {'ok':True,'status':record['status'],'outputPath':str(output),
                    'deliverables':[str(output)],'deliveryStatus':'published',
                    'warnings':record['warnings'],
                    'cleanup':artifact_cleanup.after_publish(work, data)}
    except Exception as exc:
        return _failure(exc)


def cleanup(root, work_file):
    """Retry only registered-file cleanup; unpublished work is never removed."""
    try:
        with _locked(root, work_file) as (work, data):
            if not data.get('published'):
                raise ArtifactError('artifact_not_published', '최종 파일을 전달한 뒤 임시 파일을 정리할 수 있습니다. 진행 중인 초안과 후보를 보존했습니다.')
            completed = _completed(data)  # Verify receipt and final bytes first.
            result = artifact_cleanup.after_publish(work, data)
            return {'ok':True, 'status':'cleanup_checked', 'workFile':str(work),
                    'outputPath':completed['outputPath'], 'deliveryStatus':'published',
                    'cleanup':result, 'message':result['message']}
    except Exception as exc:
        return _failure(exc)
