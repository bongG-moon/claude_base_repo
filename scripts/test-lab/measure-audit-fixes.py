"""Synthetic local cost checks. No real profiles, CLI/model calls or network."""
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'company-agent-plugin/scripts')]
from company_agent.workspace_api import WorkspaceService
from company_agent.frontmatter import dump_frontmatter
from local_app.history import HistoryStore, KEYS

with tempfile.TemporaryDirectory(prefix='audit-cost-') as temporary:
    root=Path(temporary)
    project,config,state=[root/name for name in ('project','config','state')]
    project.mkdir();config.mkdir()
    folder=state/'knowledge/entries';folder.mkdir(parents=True)
    for i in range(60):
        (folder/f'personal.term.{i:03}.md').write_text(dump_frontmatter(
            {'id':f'personal.term.{i:03}','kind':'term','title':f'한글 지식 {i}','status':'active'},'가'*12000),encoding='utf-8')
    service=WorkspaceService({'scope':'User','userStateRoot':str(state),'claudeConfigRoot':str(config)},project,ROOT/'company-agent-plugin')
    with patch.object(service,'detail',wraps=service.detail) as reads:
        page=service.snapshot('knowledge')
    measurements={'knowledgePageFilesRead':reads.call_count,
                  'knowledgePageResponseBytes':len(json.dumps(page,ensure_ascii=True).encode()),
                  'knowledgeFullBodyListBytes':len(json.dumps(service.knowledge(),ensure_ascii=True).encode())}
    items=[{'id':str(uuid.uuid4()),'title':'시험','workspace':str(project),'created':1,'sessionId':None,
            'messages':[{'role':'assistant','text':'가'*100000} for _ in range(5)]} for _ in range(40)]
    measurements['legacyFullHistoryBytes']=len(json.dumps([{key:item.get(key) for key in (*KEYS,'messages')} for item in items],ensure_ascii=False).encode())
    store=HistoryStore(root/'history');store.save(items)
    durations=[]
    for i in range(5):
        started=time.perf_counter()
        with patch.object(store,'_write',wraps=store._write) as writes:
            store.save(items,items[-1]['id'])
        durations.append((time.perf_counter()-started)*1000)
    measurements.update(historyFilesWrittenPerEvent=writes.call_count,
                        historyBytesWrittenPerEvent=sum(len(call.args[1]) for call in writes.call_args_list),
                        historySaveMedianMs=round(statistics.median(durations),2),modelRequests=0)
    print(json.dumps(measurements,ensure_ascii=False,indent=2))
