"""Explicit normal PowerPoint reference rendering; never a protection bypass."""
import json
from pathlib import Path
import subprocess
import tempfile

from .business_artifacts import _failure, _source, _reject_reparse, _windows_powershell, ArtifactError
from .business_safety import safe_path
from .ppt_reference import _selection


_SCRIPT = r'''
param([string]$RequestPath)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$app=$null; $deck=$null; $security=$null
$answer=@{ok=$false;status='unknown';code='office_reference_failed';message='PowerPoint 열기 또는 이미지 내보내기를 완료하지 못했습니다. 보호 설정은 변경하지 않았습니다.'}
try {
  $r=Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($null -eq [Type]::GetTypeFromProgID('PowerPoint.Application')) { throw 'powerpoint_unavailable' }
  $app=New-Object -ComObject PowerPoint.Application
  foreach ($open in $app.Presentations) {
    if ([string]$open.FullName -ieq [string]$r.file) { throw 'source_already_open' }
  }
  $security=$app.AutomationSecurity
  $app.AutomationSecurity=3
  $deck=$app.Presentations.Open([string]$r.file,-1,0,0)
  if ($deck.Permission.Enabled) { throw 'reference_permission_restricted' }
  $numbers=@($r.slides)
  if ($numbers.Count -eq 0) {
    if ($deck.Slides.Count -gt 60) { throw 'reference_range_required' }
    $numbers=@(1..$deck.Slides.Count)
  }
  if ($deck.Slides.Count -lt 1 -or @($numbers | Where-Object {$_ -lt 1 -or $_ -gt $deck.Slides.Count}).Count) { throw 'invalid_slide_selection' }
  $height=[int][Math]::Round(1600*$deck.PageSetup.SlideHeight/$deck.PageSetup.SlideWidth)
  foreach($n in $numbers) {
    $dest=Join-Path ([string]$r.output) ('slide-{0:D3}.png' -f [int]$n)
    $deck.Slides.Item([int]$n).Export($dest,'PNG',1600,$height)
    if (-not (Test-Path -LiteralPath $dest -PathType Leaf)) { throw 'reference_export_incomplete' }
  }
  $answer=@{ok=$true;status='rendered';slides=@($numbers);slideCount=$deck.Slides.Count}
} catch {
  $code=$_.Exception.Message
  if ($code -in @('powerpoint_unavailable','source_already_open','reference_permission_restricted','reference_range_required','invalid_slide_selection','reference_export_incomplete')) { $answer.code=$code }
} finally {
  if ($null -ne $deck) { try {$deck.Saved=-1; $deck.Close()} catch {}; [void][Runtime.InteropServices.Marshal]::ReleaseComObject($deck) }
  if ($null -ne $app) {
    if ($null -ne $security) {try {$app.AutomationSecurity=$security} catch {}}
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)
  }
}
$answer | ConvertTo-Json -Depth 5 -Compress
'''


def render_reference(source, output, slides=None):
    """Read-only normal Office open and native Export, requested explicitly.

    An already-open user document is left untouched. No parser/decryptor is
    tried on a wrapped file. Office's denial ends this path without a fallback.
    """
    try:
        selected = _selection(slides)
        source = _source(Path(source), ('.ppt', '.pptx'))
        output = safe_path(Path(output))
        _reject_reparse(output)
        if output.exists():
            raise FileExistsError(output)
        if not output.parent.is_dir():
            raise ArtifactError('output_folder_missing', '이미지 폴더의 상위 폴더를 먼저 선택해 주세요.')
        shell = _windows_powershell()
        if not shell:
            raise ArtifactError('powerpoint_unavailable', 'Windows PowerPoint 환경이 없습니다. 허용된 사용자 캡처 또는 연결된 화면 도구를 사용해 주세요.', 'unavailable')
        with tempfile.TemporaryDirectory(prefix='ppt-reference-', dir=output.parent, ignore_cleanup_errors=True) as temp:
            work = Path(temp)
            images = work/'images'
            images.mkdir()
            request = work/'request.json'
            request.write_text(json.dumps({'file':str(source), 'output':str(images), 'slides':selected or []}, ensure_ascii=True), encoding='utf-8')
            script = work/'render.ps1'
            script.write_text(_SCRIPT, encoding='utf-8-sig')
            process = subprocess.run([shell, '-NoLogo','-NoProfile','-NonInteractive','-File',str(script),'-RequestPath',str(request)],
                                     capture_output=True, timeout=90, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if process.returncode != 0 or not process.stdout.strip():
                raise ArtifactError('office_runner_unavailable', 'PowerPoint 실행 도우미를 시작하지 못했습니다. Windows 스크립트 실행 정책과 허용된 실행 환경을 확인해 주세요. 설정은 변경하지 않았습니다.', 'unavailable')
            result = json.loads(process.stdout.decode('utf-8-sig'))
            if not result.get('ok'):
                messages = {
                    'source_already_open':'선택한 파일이 이미 PowerPoint에 열려 있습니다. 사용자의 문서는 닫지 않았습니다. 현재 창에서 허용된 화면 캡처를 사용하세요.',
                    'powerpoint_unavailable':'Microsoft PowerPoint가 설치되지 않아 장별 이미지를 만들지 못했습니다.',
                    'reference_permission_restricted':'PowerPoint가 권한 제한을 보고해 중단했습니다. 다른 추출이나 보호 해제를 시도하지 않았습니다.',
                    'reference_range_required':'60장을 초과합니다. --slides로 필요한 실제 장 번호를 나누어 지정하세요.',
                    'invalid_slide_selection':'지정한 장 번호가 원본의 실제 범위를 벗어납니다.',
                }
                code=result.get('code','office_reference_failed')
                status=('blocked' if code=='reference_permission_restricted' else 'input_required'
                        if code in {'source_already_open','reference_range_required'} else 'unavailable'
                        if code=='powerpoint_unavailable' else 'unknown')
                return {'ok':False, 'status':status, 'code':code,
                        'message':messages.get(result.get('code'),'PowerPoint 정상 열기 또는 이미지 내보내기를 완료하지 못했습니다. 보호 설정 변경이나 대체 추출을 하지 않았습니다.'),
                        'rendered':False,'sourcePreserved':True,'retryAllowed':False}
            numbers = result.get('slides')
            if (not isinstance(numbers,list) or not numbers or len(numbers)>60
                    or len(numbers)!=len(set(numbers)) or any(type(n) is not int or not 1<=n<=10000 for n in numbers)
                    or selected is not None and numbers!=selected):
                raise ArtifactError('reference_export_incomplete','PowerPoint가 반환한 장 범위를 확인할 수 없습니다.')
            files = [images/f'slide-{n:03d}.png' for n in numbers]
            if any(not p.is_file() or p.read_bytes()[:8]!=b'\x89PNG\r\n\x1a\n' for p in files):
                raise ArtifactError('reference_export_incomplete','일부 장의 이미지가 없거나 올바른 PNG가 아닙니다.')
            if output.exists():
                raise FileExistsError(output)
            # Rename the completed private directory; never overwrite a folder.
            images.rename(output)
            return {'ok':True,'status':'rendered','rendered':True,'sourcePreserved':True,
                    'sourcePath':str(source),'outputPath':str(output),'slideCount':result.get('slideCount'),
                    'previews':[{'slide':n,'path':str(output/f'slide-{n:03d}.png')} for n in numbers],
                    'visualReview':'not_performed','captured':False,'method':'powerpoint-native-export',
                    'message':'PowerPoint의 정상 내보내기로 장별 이미지를 만들었습니다. 이 이미지를 2~3장씩 읽어 스타일을 확인하세요. 화면 캡처나 실제 내용 검토를 완료했다는 뜻은 아닙니다.'}
    except subprocess.TimeoutExpired:
        return {'ok':False,'status':'unknown','code':'office_reference_timeout','rendered':False,
                'message':'PowerPoint 응답 시간을 초과했습니다. 사용 중인 PowerPoint를 강제 종료하지 않았습니다. 창의 알림을 확인해 주세요.'}
    except Exception as exc:
        return {**_failure(exc),'rendered':False,'sourcePreserved':True}
