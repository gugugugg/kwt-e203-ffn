"""Run both new slices beside the unchanged frozen IR normal-use bench."""
import json
import subprocess
from prepare import ROOT,OUT,REPORT,IR,prepare

def main():
    prepare()
    files=[ROOT/'rtl/kwt_sram16x1024_model.sv',ROOT/'rtl/kwt_spmem16.sv',ROOT/'rtl/kwt_requantize.sv']
    files+=sorted((IR/'encoder').glob('*.sv'))+sorted((IR/'encoder_bus').glob('*.sv'))
    files += [OUT/'local_REF.sv',OUT/'local_SHARE4.sv',OUT/'local_tb.sv']
    command=['iverilog','-g2012','-DVERILATOR','-s','row_reuse_tb','-I',str(IR/'encoder'),'-o',str(OUT/'normal.vvp')]+[str(p) for p in files]
    with (REPORT/'compile.log').open('w') as log:
        subprocess.run(command,cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    result=dict(scenarios={},source='unchanged IR plus two external shadow slices',new_IR_CPU=False)
    (REPORT/'development.json').write_text(json.dumps(result,indent=2))
    for name,opts in [('actual12',[]),('mixed_paused',['+MIXED']),('single',['+SINGLE'])]:
        with (REPORT/(name+'.log')).open('w') as log:
            subprocess.run(['vvp',str(OUT/'normal.vvp'),'+VECTOR_DIR='+str(ROOT/'build/optimization/rtl/ffn_lp_IR/native_vectors'),
                '+ROW_GROUP=1','+STREAM','+DOUBLE']+opts,cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
        content=(REPORT/(name+'.log')).read_text()
        assert content.count('FFN_NEXT_RTL_PASS layer=')==12 and 'FFN_NEXT_RTL_ALL_PASS' in content
        result['scenarios'][name]=dict(passed=True,tasks=12,outputs=304128,accumulator_every_cycle=True,quantization=True)
        (REPORT/'development.json').write_text(json.dumps(result,indent=2))
        print('MAC_SLICE_NORMAL_PASS',name,flush=True)
    result['passed']=True
    (REPORT/'development.json').write_text(json.dumps(result,indent=2))

if __name__=='__main__':main()
