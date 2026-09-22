import requests,json,concurrent.futures,time,sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
out=Path(__file__).parent

def probe(code):
    symbol=('sh' if code.startswith('6') else 'sz')+code
    r=requests.get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',params={'param':f'{symbol},day,2026-09-21,2026-09-22,10,qfq'},timeout=12)
    r.raise_for_status()
    node=json.loads(r.content.decode('gbk')).get('data',{}).get(symbol,{})
    qt=node.get('qt',{}).get(symbol,[])
    return {'code':code,'node_keys':list(node),'quote_prefix':qt[:4],'name':qt[1] if len(qt)>2 else None,'returned_code':qt[2] if len(qt)>2 else None}
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    futures={pool.submit(probe,c):c for c in ['600519','000001','300750']}
    for f in concurrent.futures.as_completed(futures):
        try:results.append(f.result())
        except Exception as e:results.append({'code':futures[f],'error':str(e)[:250]})
(out/'candidate-info-source.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(results,ensure_ascii=False))
