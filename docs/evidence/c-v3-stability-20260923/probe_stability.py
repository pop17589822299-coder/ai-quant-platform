import sys,json,time,math,hashlib,statistics
from pathlib import Path
from datetime import date,datetime,timezone
import httpx
sys.path.insert(0,str(Path.cwd()))
from backend.app.data.providers.akshare_provider import AKShareStockProvider
out=Path(__file__).parent
records=[]
def emit(item):
    records.append(item)
    with (out/'observations.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(item,ensure_ascii=False,default=str)+'\n')
    print(json.dumps(item,ensure_ascii=True,default=str),flush=True)
def timed(label,round_no,kind,fn):
    begin=time.monotonic();item={'label':label,'round':round_no,'kind':kind,'at':datetime.now(timezone.utc).isoformat()}
    try:item.update(fn());item['ok']=True
    except Exception as exc:item.update(ok=False,error_type=type(exc).__name__,error=str(exc)[:900])
    item['seconds']=round(time.monotonic()-begin,3);emit(item)
    return item

def provider_call(code,part,round_no):
    p=AKShareStockProvider()
    if part=='info':
        x=p.get_stock_info(code);assert x['stock_code']==code and x['stock_name'].strip()
        return {'name':x['stock_name'],'industry_missing':x.get('industry') is None}
    if part=='news':
        x=p.get_stock_news(code,limit=3);assert all(r['stock_code']==code and r['title'] for r in x)
        return {'rows':len(x),'empty':not x}
    x=p.get_daily_kline(code,date(2026,9,1),date(2026,9,22))
    assert not x.empty
    ds=x['trade_date'].astype(str).tolist();assert ds==sorted(set(ds)) and ds[0]>='2026-09-01' and ds[-1]<='2026-09-22'
    for _,r in x.iterrows():
        assert str(r['stock_code'])==code
        o,h,l,c,v=[float(r[k]) for k in ['open','high','low','close','volume']]
        assert all(math.isfinite(z) for z in [o,h,l,c,v]) and l>0 and h>=max(o,c,l) and l<=min(o,c) and v>=0
    raw=x.to_json(orient='records',date_format='iso',force_ascii=False,double_precision=15)
    (out/f'{code}_round{round_no}_bars.json').write_text(raw,encoding='utf-8')
    return {'rows':len(x),'first_date':ds[0],'last_date':ds[-1],'source':p.last_kline_source,'sha256':hashlib.sha256(raw.encode()).hexdigest()}

with httpx.Client(base_url='http://127.0.0.1:8125/api/v1',timeout=130,trust_env=False) as client:
    def api(path,method='GET',body=None):
        r=client.request(method,path,json=body);b=r.json()
        if r.status_code!=200 or b.get('code')!=0:raise RuntimeError(f'HTTP {r.status_code}; code={b.get("code")}; message={b.get("message")}')
        d=b.get('data');return {'http':r.status_code,'rows':len(d) if isinstance(d,list) else None}
    for round_no in range(1,4):
        for code in ['600519','000001','300750']:
            for part in ['info','kline','news']:
                timed(f'{code}_{part}',round_no,'upstream',lambda c=code,p=part,n=round_no:provider_call(c,p,n))
            for suffix in ['', '/kline?start_date=2026-09-01&end_date=2026-09-22','/score']:
                timed(code+(suffix or '/info'),round_no,'api',lambda c=code,s=suffix:api('/stocks/'+c+s))
            timed(code+'_search',round_no,'api',lambda c=code:api('/stocks/search?keyword='+c))
        for label,path in [('name_search','/stocks/search?keyword=茅台'),('health','/health'),('history','/backtests/12'),('report_history','/ai/reports/2')]:
            timed(label,round_no,'api',lambda p=path:api(p))
        if round_no<3:time.sleep(15)
    def catalog():
        r=client.post('/stocks/catalog/sync',timeout=240);b=r.json()
        (out/'catalog.json').write_text(json.dumps(b,ensure_ascii=False,indent=2),encoding='utf-8')
        if r.status_code!=200 or b.get('code')!=0:raise RuntimeError(f'HTTP {r.status_code}; {b}')
        d=b['data'];assert d['catalog_complete'] and d['row_count']>=1000
        return {'http':200,**d}
    timed('catalog_sync',4,'integration',catalog)
    def ai():
        r=client.post('/ai/analyze',json={'stock_code':'600519'},timeout=130);b=r.json()
        (out/'default-ai.json').write_text(json.dumps(b,ensure_ascii=False,indent=2),encoding='utf-8')
        if r.status_code!=200 or b.get('code')!=0:raise RuntimeError(f'HTTP {r.status_code}; {b}')
        d=b['data'];return {'http':200,'data_keys':list(d),'report_id':d.get('report_id') or d.get('id'),'model':d.get('model_name')}
    timed('default_ai',4,'integration',ai)
    for code in ['600519','000001','300750']:
        (out/f'{code}_status.json').write_text(json.dumps(client.get('/stocks/'+code+'/data-status').json(),ensure_ascii=False,indent=2),encoding='utf-8')
summary={}
for kind in ['upstream','api','integration']:
    rows=[r for r in records if r['kind']==kind];times=sorted(r['seconds'] for r in rows)
    summary[kind]={'passed':sum(r['ok'] for r in rows),'total':len(rows),'median_seconds':statistics.median(times),'p95_seconds':times[math.ceil(.95*len(times))-1],'max_seconds':max(times),'over_10_seconds':sum(t>10 for t in times)}
summary['bar_hash_stable']={c:len({r['sha256'] for r in records if r['label']==c+'_kline' and r['kind']=='upstream' and r['ok']})==1 and sum(r['label']==c+'_kline' and r['kind']=='upstream' and r['ok'] for r in records)==3 for c in ['600519','000001','300750']}
summary['failures']=[r for r in records if not r['ok']]
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print('SUMMARY '+json.dumps(summary,ensure_ascii=True),flush=True)
