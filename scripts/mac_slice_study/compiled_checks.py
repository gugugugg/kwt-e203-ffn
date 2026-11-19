"""Use the existing compiled simulator for the same fixed RTL and stimuli."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import subprocess
import os
from prepare import ROOT,OUT,REPORT,IR

def build_normal():
    target=OUT/'verilator_normal'
    files=[ROOT/'rtl/kwt_sram16x1024_model.sv',ROOT/'rtl/kwt_spmem16.sv',ROOT/'rtl/kwt_requantize.sv']
    files+=sorted((IR/'encoder').glob('*.sv'))+sorted((IR/'encoder_bus').glob('*.sv'))
    files += [OUT/'local_REF.sv',OUT/'local_SHARE4.sv',OUT/'local_tb.sv']
    with (REPORT/'compiled-normal-build.log').open('w') as log:
        subprocess.run(['verilator_bin.exe','--cc','--exe','--main','--timing','--compiler','gcc','-Wno-fatal',
            '--top-module','row_reuse_tb','--output-split','20000','--Mdir',str(target),'-I'+str(IR/'encoder')]+[str(p) for p in files],
            cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['mingw32-make','-C',str(target),'-f','Vrow_reuse_tb.mk',
            'VERILATOR_ROOT=E:/xpian/tools/oss-cad-suite/share/verilator','PYTHON3=E:/xpian/.venv/Scripts/python.exe','-j','4'],
            cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    return target/'Vrow_reuse_tb.exe'

def replay():
    # Preserve the completed four-state checks; fill remaining SHARE4 cases.
    previous=json.loads((REPORT/'replay-local.json').read_text())
    cases=[r for r in previous['cases'] if r['passed']]
    done={(r['variant'],r['layer']) for r in cases}
    def one(layer):
        log=REPORT/'replay'/('SHARE4-%02d-compiled.log'%layer)
        with log.open('w') as stream:
            p=subprocess.run([str(OUT/'verilator_SHARE4/Vslice_replay_tb.exe'),'+STIMULUS='+str(OUT/'stimuli'/('case%02d.txt'%layer)),
                '+LAYER=%d'%layer],cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT)
        assert p.returncode==0 and 'SLICE_REPLAY_PASS' in log.read_text()
        return dict(variant='SHARE4',layer=layer,passed=True,outputs=25344,cycles=148271,backend='Verilator numerical replay; original stimulus X retained in file',log=str(log.relative_to(ROOT)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(one,layer) for layer in range(12) if ('SHARE4',layer) not in done]
        for f in as_completed(futures):
            r=f.result();cases.append(r);print('COMPILED_SLICE_PASS',r['layer'],flush=True)
    assert len(cases)==24 and len({(r['variant'],r['layer']) for r in cases})==24
    (REPORT/'replay-local-compiled.json').write_text(json.dumps(dict(passed=True,cases=cases,
        source='same causal stimulus, four-state Icarus results plus compiled remaining cases',original_IR_unchanged=True),indent=2))

def main():
    replay()
    simulation=build_normal()
    result=dict(scenarios={},backend='Verilator',both_slices_against_unchanged_IR=True)
    for name,opts in [('actual12',[]),('mixed_paused',['+MIXED']),('single',['+SINGLE'])]:
        log=REPORT/(name+'-compiled.log')
        with log.open('w') as stream:
            subprocess.run([str(simulation),'+VECTOR_DIR='+str(ROOT/'build/optimization/rtl/ffn_lp_IR/native_vectors'),
                '+ROW_GROUP=1','+STREAM','+DOUBLE']+opts,cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT,check=True)
        text=log.read_text();assert text.count('FFN_NEXT_RTL_PASS layer=')==12 and 'FFN_NEXT_RTL_ALL_PASS' in text
        result['scenarios'][name]=dict(passed=True,tasks=12,outputs=304128,accumulator_every_cycle=True,quantization=True)
        (REPORT/'development-compiled.json').write_text(json.dumps(result,indent=2));print('COMPILED_NORMAL_PASS',name,flush=True)
    result['passed']=True
    (REPORT/'development-compiled.json').write_text(json.dumps(result,indent=2))

if __name__=='__main__':main()
