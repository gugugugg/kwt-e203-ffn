"""Four-state checks with uninitialized SRAM and the same twelve actual FFN tasks."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import sys,struct,subprocess,json
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from ffn_residual import load,dump,REPORT
from materialize_ffn_residual import prepare

def check(name):
    source=prepare(name);m=load(name);out=ROOT/'build/optimization/rtl'/name;report=ROOT/'reports/optimization/rtl'/name
    out.mkdir(parents=True,exist_ok=True);report.mkdir(parents=True,exist_ok=True)
    vectors=out/'fourstate_vectors';vectors.mkdir(exist_ok=True)
    for layer in range(12):
        files=[ROOT/'build/optimization/quantization/Q2_training_range'/('linear_%02d_%s.bin'%(layer,k)) for k in ['input','expected']]
        files += [ROOT/'models/kwt_unified_optimized_v1/linear'/('layer_%02d_%s.bin'%(layer,k)) for k in ['parameters','shifts']]
        for f in files:(vectors/(f.stem+'.hex')).write_text(''.join('%04x\n'%x[0] for x in struct.iter_unpack('<H',f.read_bytes())))
    files=[ROOT/'rtl/kwt_sram16x1024_model.sv',ROOT/'rtl/kwt_spmem16.sv',ROOT/'rtl/kwt_requantize.sv']
    files+=sorted((source/'encoder').glob('*.sv'))+sorted((source/'encoder_bus').glob('*.sv'))+[ROOT/'tb/ffn_residual/residual_tb.sv']
    with (report/'fourstate-compile.log').open('w') as f:subprocess.run(['iverilog','-g2012','-DVERILATOR','-s','row_reuse_tb','-I'+str(source/'encoder'),'-o',str(out/'fourstate.vvp')]+list(map(str,files)),cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
    cmd=['vvp',str(out/'fourstate.vvp'),'+VECTOR_DIR='+str(vectors),'+MIXED','+ROW_GROUP=%d'%m['effective_changes'].get('row_group',2 if m['effective_changes'].get('row_pair') else 1)]
    if m['effective_changes'].get('stream'):cmd+=['+STREAM']
    if m['effective_changes'].get('double_buffer'):cmd+=['+DOUBLE']
    with (report/'fourstate.log').open('w') as f:subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=True)
    text=(report/'fourstate.log').read_text()
    if 'FFN_NEXT_RTL_ALL_PASS' not in text:raise RuntimeError('Four-state actual input check incomplete')
    result=dict(variant=name,passed=True,linear_tasks=12,uninitialized_sram=True,ordered_trace=True,mixed_access=True)
    dump(report/'fourstate.json',result);print('FOURSTATE12_PASS',name,flush=True);return result

if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(check,sys.argv[1:]))
    dump(REPORT/'fourstate-checks.json',rows)
