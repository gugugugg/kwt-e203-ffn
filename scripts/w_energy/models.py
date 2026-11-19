"""Add only C-on-W predictions; retain the already accepted W baseline model results."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import json,sys,types
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'scripts/c16_efficiency'),str(ROOT/'scripts/column_parallel')]
import models as previous
REPORT=ROOT/'reports/optimization/ffn_w_energy/models'

def worker(layer):
    prefix,commands=previous.parent_timing.observed_program()
    run=types.FunctionType(previous.run.__code__,dict(previous.run.__globals__,REPORT=REPORT))
    path=REPORT/('timing-C-response_relative-%02d.json'%layer)
    return json.loads(path.read_text()) if path.exists() else run(previous.ControlCore,'response_relative',layer,prefix,commands,previous.WriteWrapper,'C')

def main():
    REPORT.mkdir(parents=True,exist_ok=True)
    base=[]
    for layer in range(12):base.append(json.loads((ROOT/'reports/optimization/ffn_c16_efficiency/models'/('timing-W-response_relative-%02d.json'%layer)).read_text()))
    expected=dict(cold_cycles=99016,final_physical_commit=99015,final_ack=99017,first_mac=29895,last_emit=98987)
    actual={k:base[0][k] for k in expected}
    if actual!=expected:raise RuntimeError('Saved W anchors differ')
    (REPORT/'baseline-anchor-check.json').write_text(json.dumps(dict(passed=True,actual=actual,expected=expected,baseline_rerun=False),indent=2))
    with ProcessPoolExecutor(max_workers=4) as pool:results=list(pool.map(worker,range(12)))
    totals=dict(W=sum(x['cold_cycles'] for x in base),C=sum(x['cold_cycles'] for x in results))
    result=dict(passed=True,total_cycles=totals,C_eligible=totals['C']<totals['W'],candidates=['C','SL'] if totals['C']<totals['W'] else ['SL'],
        baseline=base,results=results,ordered_outputs_checked=12*25344,baseline_hardware_rerun=False,internal_ready_replayed=False,measured_hardware=False)
    (REPORT/'selection.json').write_text(json.dumps(result,indent=2));print('W_ENERGY_MODEL_SELECTION',json.dumps({k:result[k] for k in ['total_cycles','C_eligible','candidates']}),flush=True)

if __name__=='__main__':main()
