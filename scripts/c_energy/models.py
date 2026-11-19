"""One new cross-row model on C; read the twelve accepted C baseline results."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import importlib.util,json,sys,types
ROOT=Path(__file__).resolve().parents[2];REPORT=ROOT/'reports/optimization/ffn_c_energy/models'
sys.path[:0]=[str(ROOT/'scripts/c16_efficiency'),str(ROOT/'scripts/column_parallel')]
spec=importlib.util.spec_from_file_location('cen_prior_models',ROOT/'scripts/c16_efficiency/models.py');prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
class CrossRowCore(prior.ControlCore):
    last_instance=None
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);CrossRowCore.last_instance=self
    def reset(self):
        super().reset();self.cross_rows=0;self.direct_tiles=0;self.seed_wait=0;self.a_req_wait=0
    def tick(self,inp,c):
        row=self.row;cross=c['quant'] and c['last_emit'] and self.lane==14 and self.tile==15 and row<98
        direct=c['quant'] and c['last_emit'] and self.lane==14 and self.tile<15
        if not inp.get('reset'):
            self.cross_rows+=int(cross);self.direct_tiles+=int(direct);self.seed_wait+=int(self.state==3 and bool(self.seed_ready));self.a_req_wait+=int(self.state==6 and not self.complete())
        popped=super().tick(inp,c)
        if cross and not inp.get('reset'):
            self.row=row+2;self.tile=self.lane=self.inner=self.chunk=self.emit_row=0;self.state=6;self.seed_ready=0
        return popped
def worker(layer):
    observe=types.FunctionType(prior.parent_timing.observed_program.__code__,dict(prior.parent_timing.observed_program.__globals__,REPORT=REPORT))
    prefix,commands=observe();run=types.FunctionType(prior.run.__code__,dict(prior.run.__globals__,REPORT=REPORT));path=REPORT/('timing-XR-response_relative-%02d.json'%layer)
    if path.exists():return json.loads(path.read_text())
    row=run(CrossRowCore,'response_relative',layer,prefix,commands,prior.WriteWrapper,'XR');core=CrossRowCore.last_instance
    row['cross_row_counts']=dict(cross_rows=core.cross_rows,direct_tiles=core.direct_tiles,seed_wait=core.seed_wait,a_req_input_wait=core.a_req_wait,total_seed_consumes=core.cross_rows+core.direct_tiles+core.seed_wait)
    if (core.cross_rows,core.direct_tiles,core.seed_wait)!=(49,750,0):raise RuntimeError('XR seed/control identity differs')
    if row['counts']['contributions']!=1622016 or row['counts']['mac_clocks']!=51200 or row['outputs']!=25344:raise RuntimeError('XR complete arithmetic work differs')
    path.write_text(json.dumps(row,indent=2));return row
def main():
    REPORT.mkdir(parents=True,exist_ok=True);base=[json.loads((ROOT/'reports/optimization/ffn_w_energy/models'/('timing-C-response_relative-%02d.json'%layer)).read_text()) for layer in range(12)]
    expected=dict(cold_cycles=98783,first_mac=29895,last_emit=98754,final_physical_commit=98782,final_ack=98784)
    if any(not row['passed'] or any(row[k]!=v for k,v in expected.items()) for row in base):raise RuntimeError('Accepted C model anchors differ')
    with ProcessPoolExecutor(max_workers=4) as pool:rows=list(pool.map(worker,range(12)))
    totals=dict(C=sum(row['cold_cycles'] for row in base),XR=sum(row['cold_cycles'] for row in rows));eligible=totals['XR']<totals['C']
    result=dict(passed=True,total_cycles=totals,XR_eligible=eligible,candidates=['SL','XR'] if eligible else ['SL'],baseline_anchor_check=expected,baseline=base,results=rows,ordered_outputs_checked=12*25344,baseline_CPU_or_model_rerun=False,internal_ready_replayed=False,measured_hardware=False,CPU_pacing='Frozen response-relative request gaps; new CPU later determines hardware cycles')
    (REPORT/'selection.json').write_text(json.dumps(result,indent=2));print('C_ENERGY_XR_MODEL_SELECTION',json.dumps({k:result[k] for k in ['total_cycles','XR_eligible','candidates']}),flush=True)
if __name__=='__main__':main()
