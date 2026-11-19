from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'build/unified'
REPORT=ROOT/'reports/unified'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--linear-only',action='store_true')
    args=parser.parse_args()
    obj=BUILD/'obj'
    native=BUILD/'native'
    for folder in [obj,native,REPORT]:folder.mkdir(parents=True,exist_ok=True)
    def run(name,command):
        print(name,flush=True)
        with (REPORT/(name+'.log')).open('w') as out:
            subprocess.run(command,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,check=True)
    if not args.skip_build:
        rtl=[ROOT/'rtl/kwt_sram16x1024_model.sv',ROOT/'rtl/kwt_spmem16.sv',ROOT/'rtl/kwt_requantize.sv']
        rtl+=sorted((ROOT/'rtl/encoder').glob('*.sv'))+sorted((ROOT/'rtl/encoder_bus').glob('*.sv'))
        run('verilator',['verilator_bin','--cc','--Wno-fatal','--top-module','kwt_icb_encoder',
                        '-Irtl/encoder','--Mdir',str(obj)]+[str(p) for p in rtl])
        include=ROOT/'tools/oss-cad-suite/share/verilator/include'
        sources=sorted(obj.glob('Vkwt_icb_encoder*.cpp'))+[
            ROOT/'tb/unified/sim_unified.cpp',include/'verilated.cpp',include/'verilated_threads.cpp']
        compiler=shutil.which('g++')
        def compile_one(source):
            output=native/(source.stem+'.o')
            run('compile-'+source.stem,[compiler,'-std=c++20','-O2','-pthread','-DVL_TIME_CONTEXT',
                '-DVM_COVERAGE=0','-DVM_TRACE=0','-DVM_TIMING=0','-I'+str(include),
                '-I'+str(include/'vltstd'),'-I'+str(obj),'-c',str(source),'-o',str(output)])
            return str(output)
        with ThreadPoolExecutor(max_workers=4) as workers:objects=list(workers.map(compile_one,sources))
        run('link',[compiler,'-static','-pthread']+objects+['-o',str(BUILD/'unified_sim.exe')])
    start=time.perf_counter()
    command=[str(BUILD/'unified_sim.exe')]+(['linear'] if args.linear_only else [])
    run('linear-run' if args.linear_only else 'mixed-run',command)
    report={'passed':True,'scope':'RTL ICB functional regression','linear_tasks':12,
            'encoder_tasks':0 if args.linear_only else 2,'elapsed_seconds':time.perf_counter()-start}
    (REPORT/'rtl_checks.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':
    main()
