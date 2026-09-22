import sys,json,time,hashlib
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import httpx,pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.core.config import Settings
from backend.app.quant import run_backtest_request
from backend.app.models.backtest_result import BacktestResult
out=Path(__file__).parent
state=json.loads((out/'runtime.json').read_text())
s=Settings(_env_file=Path.cwd().parent/'ai-quant-platform-c-v1-regression/.env');s.mysql_database=state['database']
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
summary=[]
with httpx.Client(base_url='http://127.0.0.1:8125/api/v1',timeout=100,trust_env=False) as client:
    for code in ('600519','000001','300750'):
        for strategy in ('ma_cross','macd'):
            payload={'stock_code':code,'strategy':strategy,'parameters':{},'start_date':'2025-07-04','end_date':'2026-09-22'}
            begin=time.monotonic();response=client.post('/backtests',json=payload);body=response.json()
            (out/(code+'_'+strategy+'_post.json')).write_text(json.dumps(body,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            item={'stock_code':code,'strategy':strategy,'http_status':response.status_code,'code':body.get('code'),'seconds':round(time.monotonic()-begin,2)}
            if response.status_code==200 and body.get('code')==0:
                posted=body['data'];bid=posted['backtest_id']
                detail=client.get('/backtests/'+str(bid),params={'include_c_result':'true','include_input_snapshot':'true'}).json()['data']
                direct=run_backtest_request(pd.DataFrame(detail['c_result']['input_snapshot']['rows']),strategy=strategy,parameters={},start_date=payload['start_date'],end_date=payload['end_date'])
                assert canonical(direct)==canonical(detail['c_result'])
                # MA's public envelope intentionally exposes five configurable
                # parameters; the complete C configuration stays in c_result.
                # MACD's public and C effective_parameters are both six fields.
                comparable={k:v for k,v in direct.items() if strategy!='ma_cross' or k!='effective_parameters'}
                assert all(canonical(posted[k])==canonical(v) for k,v in comparable.items())
                keys=('ma_short_period','ma_long_period','initial_cash','transaction_cost','slippage') if strategy=='ma_cross' else tuple(direct['effective_parameters'])
                expected_parameters={k:direct['effective_parameters'][k] for k in keys}
                assert canonical(posted['effective_parameters'])==canonical(expected_parameters)
                assert canonical(detail['effective_parameters'])==canonical(expected_parameters)
                engine=create_engine(s.database_url,pool_pre_ping=True)
                with Session(engine) as db:
                    saved=db.get(BacktestResult,bid)
                    assert canonical(json.loads(saved.c_result_text))==canonical(direct)
                engine.dispose()
                item.update(backtest_id=bid,full_direct_post_get_mysql_equal=True,curve_points=len(direct['equity_curve']),order_count=direct['order_count'],trade_count=direct['trade_count'],total_return=direct['total_return'],start_date=direct['start_date'],end_date=direct['end_date'],data_hash=direct['data_hash'],complete_result_sha256=hashlib.sha256(canonical(direct).encode()).hexdigest())
            summary.append(item)
            (out/'backtest-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(item,ensure_ascii=False),flush=True)
        status=client.get('/stocks/'+code+'/data-status').json()
        (out/(code+'_data-status.json')).write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
