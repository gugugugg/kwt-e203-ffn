"""Run only the approved actual-layer/interface checks on the prepared development variants."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from ffn_loading_dma import candidates,dump,REPORT

def check(name):
 out=ROOT/'reports/optimization/rtl'/name
 for label,options in [('actual12',[]),('mixed_paused',['--mixed-output','--stall-output']),('single',['--single-output'])]:
  record=out/(label+'.json')
  if record.exists() and json.loads(record.read_text()).get('passed'):continue
  cmd=[sys.executable,'scripts/check_ffn_loading_dma_rtl.py',name,'--package','models/kwt_unified_optimized_v1','--vectors','build/optimization/quantization/Q2_training_range','--linear-only','--label',label]+options
  if (out/'actual12.json').exists():cmd+=['--skip-build']
  with (REPORT/(name+'-'+label+'-driver.log')).open('w') as log:subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
 return dict(variant=name,actual12=True,mixed_paused=True,single=True,purpose='implementation_check')
REPORT.mkdir(parents=True,exist_ok=True)
names=[n for n,m in candidates().items() if m['purpose']=='development']
with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(check,names))
dump(REPORT/'implementation-checks.json',dict(passed=True,configurations=rows,scope='local accelerator RTL only; not native CPU/PPA acceptance'))
print('RESIDUAL_DEVELOPMENT_ALL_PASS',len(rows),flush=True)
