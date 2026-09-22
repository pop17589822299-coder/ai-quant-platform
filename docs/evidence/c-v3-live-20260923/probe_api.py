import json,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import httpx
out=Path(__file__).parent
base='http://127.0.0.1:8125/api/v1'
jobs=[('catalog_sync','POST','/stocks/catalog/sync',None)]
for code in ('600519','000001','300750'):
    jobs.extend([(code+'_info','GET','/stocks/'+code,None),(code+'_kline','GET','/stocks/'+code+'/kline?start_date=2025-07-04&end_date=2026-09-22',None)])
def run(job):
    label,method,path,body=job
    start=time.monotonic()
    try:
        response=httpx.request(method,base+path,json=body,timeout=100,trust_env=False)
        body=response.json()
        result={'label':label,'http_status':response.status_code,'code':body.get('code'),'seconds':round(time.monotonic()-start,2),'body':body}
    except Exception as exc:
        result={'label':label,'error_type':type(exc).__name__,'seconds':round(time.monotonic()-start,2)}
    (out/(label+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={k:v for k,v in result.items() if k!='body'}
    if isinstance(result.get('body',{}).get('data'),list):
        data=result['body']['data'];summary['rows']=len(data)
        if data:summary['first_date']=data[0].get('trade_date');summary['last_date']=data[-1].get('trade_date')
    elif result.get('body',{}).get('code')!=0: summary['message']=result.get('body',{}).get('message')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return summary
with ThreadPoolExecutor(max_workers=2) as pool:
    results=[f.result() for f in as_completed([pool.submit(run,j) for j in jobs])]
(out/'api-summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
