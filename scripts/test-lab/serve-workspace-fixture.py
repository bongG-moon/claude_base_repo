"""Isolated browser-QA server: real local services, synthetic CLI, no account/LLM.

Only a newly created output directory is used for config, registrations and state.
No changes to the user's real Claude installation. Stop via the authenticated UI.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'company-agent-plugin/scripts')]
from local_app.server import LocalApp, Server
from company_agent.workspace_api import WorkspaceService
from company_agent.business_artifacts import create_html
from company_agent.frontmatter import dump_frontmatter
from company_agent.report_styles import picker_html

parser=argparse.ArgumentParser()
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
root=args.output.absolute()
root.mkdir(parents=True,exist_ok=False)
project=root/'업무 연습';project.mkdir()
config=root/'isolated-config';state=root/'personal-state'
os.environ['LOCALAPPDATA']=str(root/'local')
os.environ['CLAUDE_CONFIG_DIR']=str(config)

def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')

record={'schemaVersion':1,'scope':'User','nativeClaudeScope':'user','userStateRoot':str(state),
        'pythonCommand':sys.executable,'coreVersion':'qa-source','claudeConfigRoot':str(config),
        'claudeConfigDirOverride':True,'pluginId':'company-agent@company-agent-local'}
save(root/'local/CompanyAgent/installations/user/company-agent-install.json',record)
save(config/'plugins/installed_plugins.json',{'plugins':{'company-agent@company-agent-local':[{'scope':'user','version':'qa-source','installPath':str(ROOT/'company-agent-plugin')}]}})
save(config/'settings.json',{'enabledPlugins':{'company-agent@company-agent-local':True},'model':'preserve-fixture-model','mcpServers':{'preserve':{'disabled':True}}})
service=WorkspaceService(record,project,ROOT/'company-agent-plugin')
service.apply(service.plan({'kind':'memory','title':'가상 보고서 선호','body':'결론과 확인 범위를 간단히 구분한다.'}))
(state/'knowledge/entries').mkdir(parents=True,exist_ok=True)
for i in range(25):
    (state/'knowledge/entries'/f'personal.term.fixture-{i:02}.md').write_text(dump_frontmatter(
        {'id':f'personal.term.fixture-{i:02}','kind':'term','scope':'personal','title':f'조회 시험 {i:02}','status':'draft'},'열었을 때만 조회하는 한글 본문'),encoding='utf-8')
create_html({'title':'정적 미리보기 시험','style':'glassmorphism','mode':'slides','length':'short',
             'sections':[{'title':'첫 번째 확인','body':'가상 자료입니다.'},{'title':'두 번째 확인','body':'모든 페이지가 표시됩니다.'}]},project/'미리보기.html')
(project/'첨부 원본.html').write_text('<html><body>첨부 원본<script>throw Error("not executable")</script></body></html>',encoding='utf-8')
(project/'디자인 목록.html').write_text(picker_html(),encoding='utf-8')
(project/'격리 시험.html').write_text('''<body data-style="minimalism" onload="parent.document.body.dataset.attacked='yes'">
<style>body{background-image:url(https://blocked.invalid/image)}</style><meta http-equiv="refresh" content="0;url=https://blocked.invalid">
<main class="report-main"><h1>격리 확인</h1></main><img src="https://blocked.invalid/image">
<script>parent.document.body.dataset.attacked='yes';fetch('https://blocked.invalid/api')</script></body>''',encoding='utf-8')
(project/'확인용.md').write_text('# 회귀시험 자료\n목표 300건 / 실적 330건 / 달성률 110%\n가상 자료이며 실제 Office 시험이 아닙니다.',encoding='utf-8')
log=root/'usage-fixture.jsonl'
log.write_text(json.dumps({'type':'assistant','message':{'id':'qa-one','model':'HCP-test-only','usage':{'input_tokens':12,'output_tokens':4},'content':[]}})+'\n',encoding='utf-8')
app=LocalApp(root/'ui',command=[sys.executable,'-X','utf8',str(ROOT/'tests/fixtures/workspace_fake_cli.py')],info={'version':'deterministic-QA-no-LLM'})
server=Server(app)
save(root/'runtime.json',{'url':server.origin+'/#token='+app.token,'port':server.server_port,'workspace':str(project),'usageLog':str(log),'output':str(root)})
print('Isolated QA server ready; no model calls. Port '+str(server.server_port),flush=True)
try:server.serve_forever(poll_interval=.3)
finally:app.close();server.server_close()
