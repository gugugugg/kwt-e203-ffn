"""One causal O1 queue model, retaining calibrated C CPU response-relative pacing."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import importlib.util,inspect,json,sys,types
ROOT=Path(__file__).resolve().parents[2];REPORT=ROOT/'reports/optimization/ffn_c_final_energy/models'
sys.path[:0]=[str(ROOT/'scripts/c16_efficiency'),str(ROOT/'scripts/column_parallel')]
spec=importlib.util.spec_from_file_location('cfe_prior',ROOT/'scripts/c16_efficiency/models.py');prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
from model import OutputQueue

source=inspect.getsource(OutputQueue).replace('class OutputQueue:','class BypassQueue:')
source=source.replace('        self.retired = 0','        self.retired = 0\n        self.bypasses = self.stash_reads = self.stash_writes = self.row1_reads = self.row1_writes = self.fifo_words = 0')
source=source.replace("        drain0 = bool(self.fifo_count and self.row0_count < 128 and not read0)","        bypass = bool(self.fifo_count and space > 0 and next_item < 25344 and not next_row1 and self.row0_count == capture0)\n        drain0 = bool(self.fifo_count and self.row0_count < 128 and not read0 and not bypass)")
source=source.replace('16 + int(drain0)','16 + int(drain0 or bypass)')
source=source.replace('read1=read1, read1_pair=read1_pair, issue=issue, drain0=drain0,','read1=read1, read1_pair=read1_pair, issue=issue, drain0=drain0, bypass=bypass,')
source=source.replace("        next_held = self.held[c['pop_count']:] + self.pending","        next_held = self.held[c['pop_count']:] + self.pending\n        head = self.fifo[self.fifo_read]\n        if c['bypass']: next_held.append(head)")
source=source.replace("            self.fifo_read = (self.fifo_read + 1) & 15", "        if c['drain0'] or c['bypass']: self.fifo_read = (self.fifo_read + 1) & 15")
source=source.replace("- int(c['drain0'])","- int(c['drain0'] or c['bypass'])")
source=source.replace('        return popped',"        self.bypasses += int(c['bypass'])\n        self.stash_reads += c['issue']\n        self.stash_writes += int(c['drain0']) + 2*int(c['row1_push'])\n        self.row1_reads += c['issue'] if c['read1'] else 0\n        self.row1_writes += 2*int(c['row1_push'])\n        self.fifo_words += 2*int(c['row0_push'])\n        if len(self.held)+len(self.pending)>2 or not 0<=self.fifo_count<=16: raise RuntimeError('O1 queue physical capacity differs')\n        self.peak['held']=max(self.peak.get('held',0),len(self.held))\n        self.peak['pending']=max(self.peak.get('pending',0),len(self.pending))\n        return popped")
namespace={};exec(compile(source,str(Path(__file__)), 'exec'),namespace);BypassQueue=namespace['BypassQueue']

class BypassCore(prior.ControlCore):
    last_instance=None
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.queue=BypassQueue();BypassCore.last_instance=self

def worker(layer):
    path=REPORT/('timing-O1-response_relative-%02d.json'%layer)
    if path.exists():return json.loads(path.read_text())
    observe=types.FunctionType(prior.parent_timing.observed_program.__code__,dict(prior.parent_timing.observed_program.__globals__,REPORT=REPORT))
    prefix,commands=observe();run=types.FunctionType(prior.run.__code__,dict(prior.run.__globals__,REPORT=REPORT))
    row=run(BypassCore,'response_relative',layer,prefix,commands,prior.WriteWrapper,'O1');q=BypassCore.last_instance.queue
    row['output_queue_counts']={k:getattr(q,k) for k in ['bypasses','stash_reads','stash_writes','row1_reads','row1_writes','fifo_words']}
    if q.stash_reads!=25344-q.bypasses or q.stash_writes!=25344-q.bypasses or q.row1_reads!=12544 or q.row1_writes!=12544 or q.fifo_words!=12800:raise RuntimeError('O1 physical macro/FIFO totals differ')
    path.write_text(json.dumps(row,indent=2));return row

def main():
    REPORT.mkdir(parents=True,exist_ok=True)
    base=[json.loads((ROOT/'reports/optimization/ffn_w_energy/models'/('timing-C-response_relative-%02d.json'%i)).read_text()) for i in range(12)]
    expected=dict(cold_cycles=98783,first_mac=29895,last_emit=98754,final_physical_commit=98782,final_ack=98784)
    if any(not r['passed'] or any(r[k]!=v for k,v in expected.items()) for r in base):raise RuntimeError('Read frozen C calibration anchors')
    (REPORT/'O1-queue-model-source.py').write_text(source)
    with ProcessPoolExecutor(max_workers=4) as pool:rows=list(pool.map(worker,range(12)))
    totals=dict(C=sum(r['cold_cycles'] for r in base),O1=sum(r['cold_cycles'] for r in rows));N=sum(r['output_queue_counts']['bypasses'] for r in rows);T=12*150000000/totals['O1']
    eligible=all(r['passed'] for r in rows) and T>=1000 and (N>0 or totals['O1']<totals['C'])
    value=dict(passed=True,candidates=['SS','O1'] if eligible else ['SS'],O1_eligible=eligible,total_cycles=totals,total_bypasses=N,model_throughput=T,baseline_anchor_check=expected,baseline=base,results=rows,internal_ready_replayed=False,baseline_CPU_or_model_rerun=False,measured_hardware=False,CPU_pacing='Frozen response-relative CPU gaps; fresh CPU12 determines hardware cycles',selection_rule='Own12 correctness/ports/T>=1000 and N>0 or aggregate final commit improvement; no minimum N or percent gain')
    (REPORT/'selection.json').write_text(json.dumps(value,indent=2));print('C_FINAL_ENERGY_MODEL_SELECTION',json.dumps({k:value[k] for k in ['candidates','total_cycles','total_bypasses','model_throughput']}),flush=True)

if __name__=='__main__':main()
