import sys,json,hashlib,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import httpx
from sqlalchemy import create_engine,select,func
from sqlalchemy.orm import Session
from backend.app.core.config import Settings
from backend.app.models.ai_analysis import AIAnalysis
out=Path(__file__).parent
state=json.loads((out/'runtime.json').read_text())
s=Settings(_env_file=Path.cwd().parent/'ai-quant-platform-c-v1-regression/.env');s.mysql_database=state['database']
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
begin=time.monotonic()
with httpx.Client(base_url='http://127.0.0.1:8125/api/v1',trust_env=False,timeout=15) as client:
    first=client.get('/ai/reports/1').json()
    second=client.get('/ai/reports/1').json()
assert first==second and first['code']==0
data=first['data']
engine=create_engine(s.database_url,pool_pre_ping=True)
with Session(engine) as db:
    row=db.get(AIAnalysis,1)
    assert row.model_name==data['model_name']=='deepseek-flash'
    assert row.analysis_mode==data['analysis_mode']=='custom_backtest'
    assert row.backtest_id==data['backtest_id']==3
    assert canonical(row.context_snapshot)==canonical(data['context_snapshot'])
    for key in ('summary','technical_analysis','quant_analysis','news_analysis','advantages','risks','conclusion','context_hash'):
        assert canonical(getattr(row,key))==canonical(data[key]),key
    count=db.scalar(select(func.count()).select_from(AIAnalysis))
engine.dispose()
(out/'real-ai-report.json').write_text(json.dumps(first,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
result={'status':'passed','report_id':1,'backtest_id':3,'model':data['model_name'],'analysis_mode':data['analysis_mode'],'two_gets_equal':True,'new_mysql_connection_readback_equal':True,'saved_report_count':count,'context_hash':data['context_hash'],'report_sha256':hashlib.sha256(canonical(first).encode()).hexdigest(),'seconds':round(time.monotonic()-begin,3),'source_mode':data['source_mode']}
(out/'report-readback.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result))
