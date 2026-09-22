import sys,json,asyncio,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from backend.app.core.config import Settings
from backend.app.ai.client import OpenAICompatibleLLMClient
s=Settings(_env_file=Path.cwd().parent/'ai-quant-platform-c-v1-regression/.env')
async def main():
    start=time.monotonic()
    result={'mode':'real_llm_connectivity_only','model':s.llm_model}
    try:
        client=OpenAICompatibleLLMClient(api_key=s.llm_api_key,base_url=s.llm_base_url,model_name=s.llm_model,timeout_seconds=s.llm_timeout_seconds)
        raw=await client.complete_json([{'role':'user','content':'Connectivity test only. Return exactly JSON {"ok":true}.'}])
        result['passed']=json.loads(raw)=={'ok':True}
    except Exception as exc:
        result.update(passed=False,error_type=type(exc).__name__,error=str(exc) if type(exc).__module__.startswith('backend.') else 'Connectivity probe failed')
    result['seconds']=round(time.monotonic()-start,2)
    Path(__file__).with_name('llm-connectivity.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))
asyncio.run(main())
