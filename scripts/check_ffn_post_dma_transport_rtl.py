"""Actual FFN fixtures with the isolated DPIPE/DHAND development source copy."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
    out=ROOT/'build/optimization/ffn_post_dma/development'/('transport-rtl-'+stamp)
    report=ROOT/'reports/optimization/ffn_post_dma/development'/('transport-rtl-'+stamp)
    source=out/'source';obj=out/'obj';native=out/'native'
    for p in [out,report,native]:p.mkdir(parents=True,exist_ok=True)
    shutil.copytree(ROOT/'build/optimization/rtl_sources/ffn_ld_dev_DMAO',source)
    for name in ['kwt_ld_engine.sv','kwt_ld_icb_arbiter.sv']:
        shutil.copy2(ROOT/'rtl/post_dma'/name,source/'encoder'/name)
    def run(label,command):
        with (report/(label+'.log')).open('w') as stream:
            subprocess.run([str(x) for x in command],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
        return (report/(label+'.log')).read_text()
    files=[ROOT/'rtl/kwt_sram16x1024_model.sv',ROOT/'rtl/kwt_spmem16.sv',ROOT/'rtl/kwt_requantize.sv']
    files+=sorted((source/'encoder').glob('*.sv'))+sorted((source/'encoder_bus').glob('*.sv'))
    run('verilator',['verilator_bin','--cc','--Wno-fatal','--top-module','kwt_icb_encoder',
        '-I'+str(source/'encoder'),'--Mdir',obj]+files)
    include=ROOT/'tools/oss-cad-suite/share/verilator/include'
    flags=['-std=c++20','-O2','-pthread','-DVL_TIME_CONTEXT','-DVM_COVERAGE=0','-DVM_TRACE=0','-DVM_TIMING=0',
           '-I'+str(include),'-I'+str(include/'vltstd'),'-I'+str(obj)]
    def compile_one(path):
        target=native/(path.stem+'.o')
        run('compile-'+path.stem,['g++']+flags+['-c',path,'-o',target]);return target
    files=sorted(obj.glob('Vkwt_icb_encoder*.cpp'))+[include/'verilated.cpp',include/'verilated_threads.cpp']
    with ThreadPoolExecutor(max_workers=4) as pool:objects=list(pool.map(compile_one,files))
    results=[]
    for output in [0,1]:
        label='input_output_dma' if output else 'input_dma'
        harness=native/(label+'.o')
        run(label+'-compile',['g++']+flags+['-DRESIDUAL_ROW_GROUP=1','-DRESIDUAL_STREAM=1',
            '-DRESIDUAL_DOUBLE_BUFFER=1','-DLOADING_DMA_ENABLED=1','-DLOADING_DMA_OUTPUT='+str(output),
            '-DLOADING_DMA_TILE=0','-DLOADING_DMA_LANES=16','-c',ROOT/'tb/ffn_loading_dma/sim_unified.cpp','-o',harness])
        exe=out/(label+'.exe');run(label+'-link',['g++','-static','-pthread']+objects+[harness,'-o',exe])
        for scenario,mode,packed in [('actual12','linear','packed'),('mixed_paused','linear-mixed','packed'),('single','linear','single')]:
            log=run(label+'-'+scenario,[exe,mode,'models/kwt_unified_optimized_v1','build/optimization/quantization/Q2_training_range',packed])
            if 'UNIFIED_RTL_ALL_PASS' not in log or log.count('UNIFIED_LINEAR_PASS layer=')!=12:raise RuntimeError(log)
            results.append(dict(mode=label,scenario=scenario,passed=True,layers=12,outputs_per_layer=25344,ordered_trace=True))
            print('POST_DMA_TRANSPORT_RTL_PASS',label,scenario,flush=True)
    result=dict(passed=True,scope='isolated accelerator DPIPE/DHAND RTL and actual FFN fixtures; functional shared responder',configurations=results)
    (report/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)


if __name__=='__main__':main()
