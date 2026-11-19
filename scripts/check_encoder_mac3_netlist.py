"""Coarse synthesis/SRAM shape and full twelve-layer check for MAC3 candidate."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess

from benchmark_encoder_cpu import digest

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'build/encoder_mac3'
REPORT=ROOT/'reports/encoder_mac3'


def main():
    report={'status':'in_progress','technology_mapped':False,'target_150mhz_timing_verified':False,'area_power_verified':False}
    target=REPORT/'netlist-checks.json'
    target.write_text(json.dumps(report,indent=2))

    def run(name,command):
        print(name,flush=True)
        with (REPORT/(name+'.log')).open('w') as stream:
            subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)

    try:
        rtl=[ROOT/'rtl/kwt_sram16x1024_model.sv',ROOT/'rtl/kwt_spmem16.sv']
        rtl += [p for p in sorted((ROOT/'rtl/encoder').glob('*.sv')) if p.name!='kwt_encoder.sv']
        rtl += [ROOT/'rtl/encoder_mac3/kwt_encoder_mac3.sv']
        seal={p.relative_to(ROOT).as_posix():digest(p) for p in rtl+list((ROOT/'rtl/encoder').glob('*.svh'))+[Path(__file__),ROOT/'tb/encoder/sim_encoder.cpp']}
        script='read_verilog -sv -Irtl/encoder '+' '.join(p.relative_to(ROOT).as_posix() for p in rtl)
        script+='; hierarchy -check -top kwt_encoder_mac3; proc; opt; memory_dff; memory_collect; opt_clean; check -assert; stat; write_json build/encoder_mac3/structure.json; write_verilog -noattr build/encoder_mac3/encoder_coarse.v'
        run('structure',['yosys','-p',script])
        design=json.loads((BUILD/'structure.json').read_text()); memories={}

        def walk(name):
            for cell in design['modules'][name].get('cells',{}).values():
                if cell['type']=='$mem_v2':
                    p=cell['parameters']; width=int(p['WIDTH'],2); size=int(p['SIZE'],2)
                    if width!=16 or size not in [128,1024,4096] or int(p['RD_CLK_ENABLE'],2)!=1 or int(p['WR_PORTS'],2)!=1 or int(p['RD_PORTS'],2)!=1:
                        raise ValueError('Unexpected memory ports/shape.')
                    key=f'{width}x{size}'; memories[key]=memories.get(key,0)+1
                elif cell['type'] in design['modules']:
                    walk(cell['type'])

        walk('kwt_encoder_mac3')
        if memories!={'16x1024':136,'16x128':10}:
            raise ValueError('SRAM instance count changed.')
        obj=BUILD/'coarse-obj'; native=BUILD/'coarse-native'; results=BUILD/'coarse-results'
        for folder in [obj,native,results]:
            folder.mkdir(exist_ok=True)
        run('coarse-verilator',['verilator_bin','--cc','--Wno-fatal','--top-module','kwt_encoder_mac3','--Mdir',str(obj),str(BUILD/'encoder_coarse.v')])
        source=(ROOT/'tb/encoder/sim_encoder.cpp').read_text().replace('Vkwt_encoder','Vkwt_encoder_mac3')
        (BUILD/'sim_encoder_mac3.cpp').write_text(source)
        include=ROOT/'tools/oss-cad-suite/share/verilator/include'; cpp=shutil.which('g++')
        units=sorted(obj.glob('Vkwt_encoder_mac3*.cpp'))+[BUILD/'sim_encoder_mac3.cpp',include/'verilated.cpp',include/'verilated_threads.cpp']

        def compile_one(source):
            output=native/(source.stem+'.o')
            run('coarse-native-'+source.stem,[cpp,'-std=c++20','-O3','-pthread','-DVL_TIME_CONTEXT','-DVM_COVERAGE=0','-DVM_TRACE=0','-DVM_TIMING=0',
                '-I'+str(include),'-I'+str(include/'vltstd'),'-I'+str(obj),'-c',str(source),'-o',str(output)])
            return str(output)

        with ThreadPoolExecutor(max_workers=4) as workers:
            objects=list(workers.map(compile_one,units))
        exe=BUILD/'encoder_coarse_sim.exe'
        run('coarse-link',[cpp,'-static','-pthread']+objects+['-o',str(exe)])
        run('coarse-run',[str(exe),'1',str(results)])
        text=(REPORT/'coarse-run.log').read_text()
        if 'ENCODER_ALL_PASS tasks=1 words=6336' not in text:
            raise ValueError('Missing complete netlist task.')
        for actual,expected in [('task_00_output.bin','task_00_expected.bin'),('task_00_trace.bin','task_00_trace.bin')]:
            if digest(results/actual)!=digest(ROOT/'build/encoder/vectors'/expected):
                raise ValueError('Netlist final/intermediate mismatch.')
        for name,expected in seal.items():
            if digest(ROOT/name)!=expected:
                raise ValueError('Source changed during synthesis test.')
        report.update(status='passed',source_sha256=seal,memory_instances=memories,internal_sram_bytes=281088,
            complete_twelve_layer_coarse_tasks=1,final_words=6336,intermediate_words=1603800,
            coarse_netlist_sha256=digest(BUILD/'encoder_coarse.v'),coarse_simulator_sha256=digest(exe))
        target.write_text(json.dumps(report,indent=2)); print(json.dumps(report['memory_instances']))
    except Exception:
        report['status']='failed'; target.write_text(json.dumps(report,indent=2)); raise


if __name__=='__main__':
    main()
