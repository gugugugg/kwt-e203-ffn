from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'scripts/server')]
from ffn_loading_dma import BUILD,REPORT,dump
from bind_ffn_loading_dma_soc import shared_controller


def main():
    out=BUILD/'shared_arbitration';out.mkdir(parents=True,exist_ok=True)
    report=REPORT/'shared-arbitration';report.mkdir(parents=True,exist_ok=True)
    source=out/'kwt_shared_dma_icb_sm40.sv';source.write_text(shared_controller())
    def run(label,command):
        with (report/(label+'.log')).open('w') as log:subprocess.run(command,cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    obj=out/'obj';native=out/'native';native.mkdir(exist_ok=True)
    run('verilator',['verilator_bin','--cc','--Wno-fatal','--top-module','kwt_shared_icb_sm40','--Mdir',str(obj),str(source),
        str(ROOT/'rtl/loading_dma/kwt_ld_icb_arbiter.sv'),str(ROOT/'tb/ffn_loading_dma/shared_memory_model.sv')])
    include=ROOT/'tools/oss-cad-suite/share/verilator/include';compiler=shutil.which('g++')
    sources=sorted(obj.glob('Vkwt_shared_icb_sm40*.cpp'))+[ROOT/'tb/ffn_loading_dma/shared_arbitration.cpp',include/'verilated.cpp',include/'verilated_threads.cpp']
    def compile_one(p):
        target=native/(p.stem+'.o');run('compile-'+p.stem,[compiler,'-std=c++20','-O2','-pthread','-DVL_TIME_CONTEXT',
            '-DVM_COVERAGE=0','-DVM_TRACE=0','-DVM_TIMING=0','-I'+str(include),'-I'+str(include/'vltstd'),'-I'+str(obj),'-c',str(p),'-o',str(target)]);return str(target)
    with ThreadPoolExecutor(max_workers=4) as pool:objects=list(pool.map(compile_one,sources))
    binary=out/'sim.exe';run('link',[compiler,'-static','-pthread']+objects+['-o',str(binary)])
    run('normal-contention',[str(binary)])
    log=(report/'normal-contention.log').read_text()
    if 'SHARED_DMA_NORMAL_ARBITRATION_PASS' not in log:raise RuntimeError(log)
    dump(REPORT/'shared-arbitration-check.json',dict(passed=True,scope='Host writes followed by concurrent CPU and DMA reads/writes with CPU response backpressure; functional SRAM model',log=log))
    print(log,flush=True)


if __name__=='__main__':main()
