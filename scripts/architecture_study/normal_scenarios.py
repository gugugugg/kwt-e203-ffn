"""Normal user-facing read, pause and reload cases for the changed architecture models."""
import json
import numpy as np
from common import ROOT,REPORT,dump,arrays
from model import vectors
from cores import CoreA,CoreC


def run(route,label):
    name='normal/%s-%s.json'%(route,label)
    path=REPORT/name
    if path.exists():return json.loads(path.read_text(encoding='utf-8'))
    cls=CoreA if route=='A' else CoreC
    core=cls(layer=0,numeric=True)
    layer=0;frames=[];outputs=[];pause=0;paused=False
    expected=arrays(0)[4].reshape(-1)
    for cycle in range(4000000):
        inp=dict(out_ready=False,out_pair_ready=False)
        if core.state==1:inp['start']=True
        elif core.state==2:
            if core.parameter_count<17408:inp.update(load=True,load_kind=1,load_address=core.parameter_count,load_pair=True)
            elif core.shift_count<128:inp.update(load=True,load_kind=5,load_address=core.shift_count,load_pair=False)
            else:inp['layer_start']=True
        elif core.capacity(0) and core.input_count<6336:inp.update(load=True,load_kind=0,load_address=core.input_count,load_pair=False)
        if label=='mixed_paused' and not paused and len(outputs)>=512:paused=True;pause=4096
        if pause:pause-=1
        elif core.queue.held:
            single=label=='single' or core.item%17==0 or core.item==25343
            inp['out_ready']=single
            inp['out_pair_ready']=not single and len(core.queue.held)==2
        c=core.comb(inp)
        for index,value in core.tick(inp,c):
            if index!=len(outputs) or value!=expected[index]:raise RuntimeError('Architecture normal output mismatch: %s %s %d %d'%(route,label,layer,index))
            outputs.append(value)
        if len(outputs)==25344:
            frames.append(dict(layer=layer,outputs=25344,exact=True,ordered=True,queue_peak=dict(core.queue.peak),pause_cycles=4096 if paused else 0))
            if layer==1:break
            layer=1;outputs=[];paused=False
            core.x,core.w,core.bias,core.shifts=vectors(layer)
            expected=arrays(layer)[4].reshape(-1)
            if route=='C':
                w=arrays(layer)[1]
                core.steps=[[1+max(1,max(abs(int(v)).bit_count() for v in w[k,t*8:t*8+8])) for t in range(32)] for k in range(64)]
    else:raise RuntimeError('Normal scenario did not finish: '+route+'/'+label)
    result=dict(route=route,scenario=label,passed=True,cycles=cycle+1,frames=frames,
                scope='Python core/queue model; continuous two-task reload, single/paired/odd reads and real pause. Not RTL or E203 simulation')
    dump(name,result)
    print('ARCHITECTURE_NORMAL_PASS',route,label,cycle+1,flush=True)
    return result


if __name__=='__main__':
    results=[]
    for route in ['A','C']:
        for label in ['single','mixed','mixed_paused']:results.append(run(route,label))
    dump('normal-scenarios.json',dict(passed=True,results=results,
         B_control_unchanged_from_IR=True,
         B_control_evidence='reports/optimization/ffn_taskflow_study/normal-model-scenarios.json',
         B_arithmetic_evidence='numeric-validation.json'))
