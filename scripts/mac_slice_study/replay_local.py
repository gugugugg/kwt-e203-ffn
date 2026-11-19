"""Verify both standalone slices on the causal twelve-case cold schedule."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import subprocess
from prepare import ROOT,OUT,REPORT

def one(v,layer):
    path=REPORT/'replay'/('%s-%02d.log'%(v,layer));path.parent.mkdir(exist_ok=True)
    with path.open('w') as log:
        p=subprocess.run(['vvp',str(OUT/('replay_%s.vvp'%v)),
            '+STIMULUS='+str(OUT/'stimuli'/('case%02d.txt'%layer)),'+LAYER=%d'%layer],
            cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT)
    text=path.read_text()
    return dict(variant=v,layer=layer,passed=p.returncode==0 and 'SLICE_REPLAY_PASS' in text,outputs=25344,cycles=148271,log=str(path.relative_to(ROOT)))

def main():
    for v in ['REF','SHARE4']:
        with (REPORT/('replay-compile-%s.log'%v)).open('w') as log:
            subprocess.run(['iverilog','-g2012','-DVERILATOR','-s','slice_replay_tb','-o',str(OUT/('replay_%s.vvp'%v)),
                str(OUT/v/'mac_slice.sv'),str(OUT/'top.sv'),str(OUT/'kwt_ffn_clock_gate.sv'),str(OUT/'kwt_ffn_requantize.sv'),
                str(ROOT/'scripts/mac_slice_study/replay_tb.sv')],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    result=dict(cases=[],scope='Native case1 causal schedule, other layers modeled on that schedule; no new CPU observations')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(one,v,layer) for v in ['REF','SHARE4'] for layer in range(12)]
        for future in as_completed(futures):
            r=future.result();result['cases'].append(r)
            (REPORT/'replay-local.json').write_text(json.dumps(result,indent=2))
            print('SLICE_LOCAL_REPLAY',r['variant'],r['layer'],r['passed'],flush=True)
    result['passed']=all(r['passed'] for r in result['cases']) and len(result['cases'])==24
    (REPORT/'replay-local.json').write_text(json.dumps(result,indent=2))
    assert result['passed']

if __name__=='__main__':main()
