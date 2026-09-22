"""External acceptance harness: unchanged main, fixed input, isolated real MySQL."""
import json, re, sys, subprocess
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path.cwd()))
from sqlalchemy import create_engine, text
from backend.app.core.config import Settings

root = Path.cwd()
out = Path(__file__).parent
settings = Settings(_env_file=root.parent/'ai-quant-platform-c-v1-regression/.env')
assert settings.mysql_host in ('localhost', '127.0.0.1'), 'Local MySQL only'
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
expected = 'a6c939351579076ce65b0fec6573bf72cb3cfcd9'
assert head == expected
admin = create_engine(settings.database_url.rsplit('/', 1)[0] + '/?charset=utf8mb4')
receipt = {'tested_sha': head, 'databases': [], 'mode': 'fixed Tencent qfq sample / real isolated MySQL / fixture LLM'}
for kind in ('backtest', 'ai'):
    name = 'ai_quant_c_v3_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + kind
    assert re.fullmatch(r'ai_quant_c_v3_\d{8}_\d{6}_(backtest|ai)', name)
    with admin.begin() as conn:
        conn.execute(text('CREATE DATABASE `' + name + '` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
    receipt['databases'].append(name)
    (out/'mysql-databases.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    settings.mysql_database = name
    source = (root/'docs/evidence/c-v3-d22-approved-20260922'/('probe_' + kind + '.py')).read_text(encoding='utf-8')
    source = re.sub(r"    url\s*=\s*'sqlite:///'[^\n]*", '    url = acceptance_url', source)
    source = re.sub(r"create_engine\(url,\s*connect_args=\{'check_same_thread':\s*False\}\)", 'create_engine(url, pool_pre_ping=True)', source)
    source = source.replace("if '--with-c-overlay' in sys.argv:", 'if True:')
    # Report metadata must describe this execution, not the older probe's origin.
    injection = "\nreport['tested_sha'] = acceptance_head\nreport['scope'] = 'Final merged main; fixed Tencent qfq sample; real isolated MySQL; fixture LLM; no live Provider or real LLM'\nreport['database'] = acceptance_database\n"
    if kind == 'backtest':
        injection += "for old_key in ('b_sha','main_sha','d_pr_head','d_production_sha','b19_sha'): report.pop(old_key, None)\n"
    source = source.replace('Path(sys.argv[1]).write_bytes', injection + 'Path(sys.argv[1]).write_bytes')
    # Store transformed code without secrets; database URL is provided in memory only.
    (out/('probe_' + kind + '_mysql.py')).write_text(source, encoding='utf-8')
    sys.argv = [str(out/('probe_' + kind + '_mysql.py')), str(out/(kind + '-mysql.json'))]
    try:
        exec(compile(source, sys.argv[0], 'exec'), {'__name__': '__main__', 'acceptance_url': settings.database_url, 'acceptance_head': head, 'acceptance_database': name})
    except SystemExit as exc:
        if exc.code not in (None, 0): raise
admin.dispose()
print('PASS: real MySQL probes completed on ' + head)
