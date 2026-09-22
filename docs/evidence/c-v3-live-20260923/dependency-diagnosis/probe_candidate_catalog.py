import concurrent.futures,subprocess,json,sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
script='''import akshare as ak,json,sys
sys.stdout.reconfigure(encoding="utf-8")
name,symbol=sys.argv[1:]
f=getattr(ak,name)
d=f(symbol=symbol) if symbol else f()
print("PROBE_RESULT="+json.dumps({"rows":len(d),"columns":list(d.columns),"examples":d.head(2).astype(str).to_dict("records")},ensure_ascii=False))
'''
specs=[('SSE','stock_info_sh_name_code','主板A股'),('STAR','stock_info_sh_name_code','科创板'),('SZSE','stock_info_sz_name_code','A股列表'),('BSE','stock_info_bj_name_code','')]
def probe(spec):
    label,name,symbol=spec
    try:
        p=subprocess.run([sys.executable,'-c',script,name,symbol],capture_output=True,timeout=25)
        text=p.stdout.decode('utf-8',errors='replace')
        if 'PROBE_RESULT=' in text:return {'market':label,'ok':True,**json.loads(text.split('PROBE_RESULT=')[-1])}
        return {'market':label,'ok':False,'error':p.stderr.decode('utf-8',errors='replace')[-500:]}
    except subprocess.TimeoutExpired:return {'market':label,'ok':False,'error':'25s bounded timeout; child terminated'}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:r=list(pool.map(probe,specs))
Path(__file__).with_name('candidate-catalog-sources.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(r,ensure_ascii=False))
