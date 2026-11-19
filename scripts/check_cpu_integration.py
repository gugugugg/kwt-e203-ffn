"""Build and run real public E203 instructions against the accelerator and shared RAM."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/cpu'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--tasks',type=int,default=14,choices=range(1,15))
    parser.add_argument('--skip-build',action='store_true')
    args=parser.parse_args()
    REPORT.mkdir(parents=True,exist_ok=True)
    obj=ROOT/'build/cpu/obj'
    obj.mkdir(parents=True,exist_ok=True)
    (ROOT/'build/cpu/results').mkdir(parents=True,exist_ok=True)
    native=ROOT/'build/cpu/native-obj'
    native.mkdir(parents=True,exist_ok=True)
    steps=[]
    result={'status':'in_progress','steps':steps}
    report_path=REPORT/'checks.json'

    def save():
        report_path.write_text(json.dumps(result,indent=2),encoding='utf-8')

    def run(name,command):
        print(name,flush=True)
        start=time.perf_counter()
        with (REPORT/(name+'.log')).open('w',encoding='utf-8') as output:
            p=subprocess.run(command,cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
        steps.append({'name':name,'returncode':p.returncode,'elapsed_host_seconds':time.perf_counter()-start})
        save()
        if p.returncode:
            raise RuntimeError((REPORT/(name+'.log')).read_text(encoding='utf-8',errors='replace')[-5000:])

    save()
    try:
        upstream=ROOT/'third_party/e203_hbirdv2'
        commit=subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()
        dirty=subprocess.check_output(['git','-C',str(upstream),'status','--porcelain','--untracked-files=no'],text=True).strip()
        if commit!='9f3e34f337f5d0a1236a285871ffa2032491617a' or dirty:
            raise ValueError('Public E203 source differs from the pinned clean version.')
        cpp_compiler=shutil.which('g++')
        if not cpp_compiler:
            raise RuntimeError('A native g++ compiler is needed; do not substitute a fake CPU simulation.')
        source_paths=list((ROOT/'software/cpu_integration').glob('*'))+list((ROOT/'tb/cpu').glob('*'))
        source_paths += list((ROOT/'rtl').glob('*.sv'))+[ROOT/'software/kwt/kwt_driver.c',ROOT/'software/kwt/kwt_driver.h',
                       ROOT/'scripts/prepare_cpu_integration.py',ROOT/'scripts/check_cpu_integration.py',
                       ROOT/'scripts/Check-CPU.ps1',ROOT/'build/rtl/vectors/manifest.json',
                       ROOT/'models/kwt1_fixed16_v1/manifest.json']
        build_sources={p.relative_to(ROOT).as_posix():digest(p) for p in source_paths}
        vector_manifest=json.loads((ROOT/'build/rtl/vectors/manifest.json').read_text())
        if vector_manifest['parameter_manifest_sha256']!=(ROOT/'models/kwt1_fixed16_v1/manifest.sha256').read_text().strip():
            raise ValueError('RTL input fixture configuration differs from the current numerical package.')
        for filename,expected_hash in vector_manifest['files'].items():
            if digest(ROOT/'build/rtl/vectors'/filename)!=expected_hash:
                raise ValueError('A frozen input/reference fixture changed: '+filename)
        if not args.skip_build:
            run('prepare',[sys.executable,'scripts/prepare_cpu_integration.py'])
            up=upstream/'rtl/e203'
            rtl_files=[str(p) for p in sorted(up.rglob('*.v'))]+[str(p) for p in sorted((ROOT/'rtl').glob('*.sv'))]
            command=[str(ROOT/'tools/oss-cad-suite/bin/verilator_bin.exe'),'--cc','--no-timing','--Wno-fatal',
                     '--top-module','kwt_cpu_soc','--Mdir',str(obj),'-Ibuild/cpu',
                     '-I'+str(up/'core'),'-I'+str(up/'perips'),'-I'+str(up/'perips/apb_i2c'),
                     '-DDISABLE_SV_ASSERTION=1','tb/cpu/kwt_cpu_soc.sv']+rtl_files
            run('verilator-build',command)
            warnings=[line for line in (REPORT/'verilator-build.log').read_text().splitlines() if line.startswith('%Warning')]
            if any('third_party' not in line for line in warnings):
                raise RuntimeError('Resolve new harness/accelerator Verilator warnings before running.')
            include=ROOT/'tools/oss-cad-suite/share/verilator/include'
            sources=sorted(obj.glob('Vkwt_cpu_soc*.cpp'))+[ROOT/'tb/cpu/sim_main.cpp',include/'verilated.cpp',include/'verilated_threads.cpp']
            def compile_one(source):
                output=native/(source.stem+'.o')
                command=[cpp_compiler,'-std=c++20','-O2','-pthread','-DVL_TIME_CONTEXT','-DVM_COVERAGE=0',
                         '-DVM_TRACE=0','-DVM_TIMING=0','-I'+str(include),'-I'+str(include/'vltstd'),
                         '-I'+str(obj),'-c',str(source),'-o',str(output)]
                with (REPORT/('native-'+source.stem+'.log')).open('w') as log:
                    process=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
                if process.returncode:
                    raise RuntimeError('Native compilation failed: '+source.name)
                return str(output)
            print('native-compile (4 workers)',flush=True)
            with ThreadPoolExecutor(max_workers=4) as workers:
                objects=list(workers.map(compile_one,sources))
            run('native-link',[cpp_compiler,'-static','-pthread']+objects+['-o',str(ROOT/'build/cpu/cpu_sim.exe')])
            (ROOT/'build/cpu/build-sources.json').write_text(json.dumps(build_sources,indent=2))
        elif json.loads((ROOT/'build/cpu/build-sources.json').read_text())!=build_sources:
            raise RuntimeError('Sources changed since the simulation build; rebuild required.')
        run('run',[str(ROOT/'build/cpu/cpu_sim.exe'),f'+TASKS={args.tasks}'])
        text=(REPORT/'run.log').read_text()
        records=[]
        for line in text.splitlines():
            if line.startswith('CPU_TASK_PASS '):
                records.append({key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',line)})
        if len(records)!=args.tasks or f'CPU_ALL_PASS tasks={args.tasks} ' not in text:
            raise RuntimeError('Real CPU completion evidence missing.')
        vectors=json.loads((ROOT/'build/rtl/vectors/manifest.json').read_text())
        package=json.loads((ROOT/'models/kwt1_fixed16_v1/manifest.json').read_text())
        real_reference=np.load(sorted((ROOT/'data/numerical/fixed16_v1/ffn_vectors').glob('*.npz'))[0])
        for index,record in enumerate(records):
            actual_path=ROOT/f'build/cpu/results/task_{index:02d}_codes.hex'
            actual=np.array([int(value,16) for value in actual_path.read_text().splitlines()],dtype='<u2').view('<i2').reshape(99,256)
            expected=np.array([int(value,16) for value in (ROOT/f'build/rtl/vectors/task_{index:02d}_expected.hex').read_text().splitlines()],dtype='<u2').view('<i2').reshape(99,256)
            if not np.array_equal(actual,expected):
                raise RuntimeError('Saved CPU writeback differs from integer reference.')
            record.update(source=vectors['ffn_tasks'][index]['source'],layer=vectors['ffn_tasks'][index]['layer'],
                          result_sha256=digest(actual_path),integer_output_bit_exact=True)
            if index<12:
                f=package['layers'][index]['ffn_fc1_f']
                decoded=actual.astype(np.float64)*2.0**-f
                floating=real_reference[f'layer_{index:02d}_reference_float32'].astype(np.float64)
                record['nrmse_vs_float']=float(np.sqrt(np.mean((decoded-floating)**2))/max(np.sqrt(np.mean(floating**2)),1e-8))
                if record['nrmse_vs_float']>0.03:
                    raise RuntimeError('Local undergraduate single-task NRMSE exceeds 3%.')
        real_reference.close()
        warning_counts={}
        for line in (REPORT/'verilator-build.log').read_text().splitlines():
            match=re.match(r'%Warning-([^:]+):',line)
            if match:
                warning_counts[match[1]]=warning_counts.get(match[1],0)+1
        result.update(status='passed',entry_group='undergraduate',date='2026-10-21',
                      scope='real public E203 CPU RTL executes RV32 firmware, not a bus functional model',
                      public_e203_commit=commit,public_e203_upstream_modified=False,
                      public_cpu_firmware_executed=True,task_count=len(records),tasks=records,
                      output_words_bit_exact=args.tasks*25344,shared_sram_bytes=524288,
                      explicit_cpu_clear_words_per_task=23744,load_words_per_task=23744,
                      cold_data_and_parameter_reloaded_per_task=True,
                      reference_answers_cpu_accessible=False,mandatory_math_executed_by_accelerator_rtl=True,
                      firmware_sha256=digest(ROOT/'build/cpu/firmware.elf'),
                      simulator_sha256=digest(ROOT/'build/cpu/cpu_sim.exe'),source_sha256=build_sources,
                      shared_image_sha256={p.name:digest(p) for p in sorted((ROOT/'build/cpu/images').glob('*.hex'))},
                      numerical_package_sha256=vectors['parameter_manifest_sha256'],
                      host_compiler=cpp_compiler,verilator_upstream_warning_counts=warning_counts,
                      simulation='cycle-functional --no-timing; public RTL artificial #1 delays ignored',
                      cpu_clock_gating='original enabled logic, test_mode=0',
                      external_memory_waits='deterministic command/response waits enabled',
                      fixture_load='host supplies one layer into shared SRAM before CPU job; no external DDR controller',
                      official_platform_integrated=False,official_600_evaluated=False,
                      target_150mhz_timing_verified=False,area_power_verified=False,
                      full_encoder_rtl_completed=False,downloads_during_this_work=False)
        save()
        print(json.dumps({key:result[key] for key in ['status','public_cpu_firmware_executed','task_count',
                                                      'output_words_bit_exact','public_e203_commit']},indent=2),flush=True)
    except Exception:
        result['status']='failed'
        save()
        raise


if __name__=='__main__':
    main()
