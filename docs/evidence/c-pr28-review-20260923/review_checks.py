import sys,json,subprocess,types,time,threading
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path.cwd()))
from sqlalchemy import create_engine,select,text
from sqlalchemy.orm import Session
from backend.app.core.config import Settings
from backend.app.core.errors import DatabaseOperationError
from backend.app.db.migrations import apply_migrations
from backend.app.models.stock_basic import StockBasic
from backend.app.schemas.stock import StockBasicSchema
from backend.app.services.stock_catalog_service import StockCatalogRepository
from backend.app.data.providers.akshare_provider import AKShareStockProvider
out=Path(__file__).parent
base='83bcbd118126db4fa99003e1809865637e621e5b'
source=subprocess.check_output(['git','show',base+':backend/app/services/stock_catalog_service.py'],text=True,encoding='utf-8')
old=types.ModuleType('c_pr28_base_catalog');sys.modules[old.__name__]=old;exec(compile(source,'<base stock_catalog_service>','exec'),old.__dict__)
result={}
def exercise(engine):
 apply_migrations(engine)
 with Session(engine) as db:
  repo=StockCatalogRepository(db)
  initial=[StockBasicSchema(stock_code='000002',stock_name='万科A'),StockBasicSchema(stock_code='000001',stock_name='平安银行')]
  repo.upsert_many(initial)
  assert old.StockCatalogRepository(db).upsert_many(initial)==2
  items=[StockBasicSchema(stock_code='000002',stock_name='万 科Ａ'),StockBasicSchema(stock_code='000001',stock_name='平安银行'),StockBasicSchema(stock_code='600519',stock_name='贵州茅台')]
  failed=False
  try:old.StockCatalogRepository(db).upsert_many(items)
  except DatabaseOperationError:failed=True
  assert failed
  assert dict(db.execute(select(StockBasic.stock_code,StockBasic.stock_name)).all())=={'000002':'万科A','000001':'平安银行'}
  assert repo.upsert_many(items)==3
  assert repo.upsert_many(items)==3
 with Session(engine) as fresh:
  actual=dict(fresh.execute(select(StockBasic.stock_code,StockBasic.stock_name)).all())
  assert actual=={'000002':'万 科Ａ','000001':'平安银行','600519':'贵州茅台'}
  assert StockCatalogRepository(fresh).search('万 科Ａ')[0].stock_code=='000002'
 return {'unchanged_refresh_base_passed':True,'base_rename_failed':True,'base_failure_rolled_back_new_insert':True,'head_mixed_insert_rename_unchanged_passed':True,'head_repeat_idempotent':True,'fresh_connection_names_match':True}
e=create_engine('sqlite://');result['sqlite']=exercise(e);e.dispose()
s=Settings(_env_file=Path.cwd().parent/'ai-quant-platform-c-v1-regression/.env');assert s.mysql_host in ('localhost','127.0.0.1')
name='ai_quant_c_pr28_review_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
server=create_engine(s.database_url.rsplit('/',1)[0]+'/?charset=utf8mb4')
with server.begin() as c:c.execute(text('CREATE DATABASE `'+name+'` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
server.dispose();s.mysql_database=name
e=create_engine(s.database_url);result['mysql']={'database':name,**exercise(e)};e.dispose()
p=AKShareStockProvider();release=threading.Event();events=[]
try:
 for i in range(p.max_background_workers+1):
  try:p._call_with_timeout(lambda:release.wait(3),0.03)
  except TimeoutError as exc:events.append({'serial_call':i+1,'error':str(exc)})
 assert 'too many in-flight' in events[-1]['error']
 result['serial_timeout_reproduction']={'sequential_caller':True,'calls':events,'independent_test_process':True}
finally:
 release.set()
 limit=time.monotonic()+2
 while AKShareStockProvider._active_workers and time.monotonic()<limit:time.sleep(.01)
 assert AKShareStockProvider._active_workers==0
(out/'review-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=True))
