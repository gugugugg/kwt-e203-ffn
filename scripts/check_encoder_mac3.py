"""Validate a three-cycle synchronous SRAM MAC schedule using real E203 firmware."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

import numpy as np

from benchmark_encoder_cpu import digest, replace_once

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'build/encoder_mac3'
REPORT=ROOT/'reports/encoder_mac3'


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--tasks', type=int, default=14, choices=range(1,15))
    parser.add_argument('--jobs', type=int, default=4, choices=range(1,5))
    parser.add_argument('--skip-build', action='store_true')
    args=parser.parse_args()
    for folder in [BUILD,REPORT,BUILD/'obj',BUILD/'native',BUILD/'results']:
        folder.mkdir(parents=True,exist_ok=True)
    report={'status':'in_progress','steps':[]}

    def save():
        (REPORT/'checks.json').write_text(json.dumps(report,indent=2))

    def run(name,command):
        print(name,flush=True)
        start=time.perf_counter()
        with (REPORT/(name+'.log')).open('w') as stream:
            process=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
        if process.returncode:
            raise RuntimeError((REPORT/(name+'.log')).read_text(errors='replace')[-5000:])
        return {'name':name,'returncode':process.returncode,'host_seconds':time.perf_counter()-start}

    save()
    try:
        # Same source and fixture seal used by the currently frozen CPU regression.
        prior=json.loads((ROOT/'reports/encoder_cpu/checks.json').read_text())
        for name,expected in prior['source_sha256'].items():
            if digest(ROOT/name)!=expected:
                raise ValueError('Original source changed '+name)
        upstream=ROOT/'third_party/e203_hbirdv2'
        if subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()!=prior['public_e203_commit']:
            raise ValueError('CPU commit changed.')
        if subprocess.check_output(['git','-C',str(upstream),'status','--porcelain'],text=True).strip():
            raise ValueError('CPU dirty.')
        manifest=json.loads((ROOT/'build/encoder/vectors/manifest.json').read_text())
        for name,expected in manifest['files'].items():
            if digest(ROOT/'build/encoder/vectors'/name)!=expected:
                raise ValueError('Numerical fixtures changed '+name)
        for name,expected in prior['input_images_sha256'].items():
            if digest(ROOT/'build/encoder_cpu/images'/name)!=expected:
                raise ValueError('Shared images changed '+name)
        # Use the original (already accepted) firmware. Only the MAC schedule changes.
        fw=ROOT/'build/encoder_cpu/firmware_itcm.hex'
        bus=(ROOT/'rtl/encoder_bus/kwt_icb_encoder.sv').read_text()
        bus=replace_once(bus,'module kwt_icb_encoder(','module kwt_icb_encoder_mac3(')
        bus=replace_once(bus,'kwt_encoder core(','kwt_encoder_mac3 core(')
        (BUILD/'kwt_icb_encoder_mac3.sv').write_text(bus)
        sv=(ROOT/'build/encoder_perf/kwt_encoder_cpu_soc.sv').read_text()
        sv=replace_once(sv,'kwt_icb_encoder accelerator(','kwt_icb_encoder_mac3 accelerator(')
        (BUILD/'kwt_encoder_cpu_soc.sv').write_text(sv)
        paths=[ROOT/name for name in prior['source_sha256']]+[Path(__file__),ROOT/'scripts/Check-Encoder-MAC3.ps1',
            ROOT/'scripts/benchmark_encoder_cpu.py', ROOT/'rtl/encoder_mac3/kwt_encoder_mac3.sv',
            BUILD/'kwt_icb_encoder_mac3.sv', BUILD/'kwt_encoder_cpu_soc.sv',ROOT/'build/encoder_perf/sim_encoder_cpu.cpp',
            ROOT/'build/encoder_cpu/e203_cpu_instance.svh',fw]
        seal={p.relative_to(ROOT).as_posix():digest(p) for p in paths}
        rtl=[ROOT/'rtl/kwt_sram16x1024_model.sv',ROOT/'rtl/kwt_spmem16.sv']
        rtl += [p for p in sorted((ROOT/'rtl/encoder').glob('*.sv')) if p.name!='kwt_encoder.sv']
        rtl += [ROOT/'rtl/encoder_mac3/kwt_encoder_mac3.sv',BUILD/'kwt_icb_encoder_mac3.sv']
        obj=BUILD/'obj'; exe=BUILD/'encoder_mac3_sim.exe'; cpp=shutil.which('g++')
        if not cpp:
            raise ValueError('Native compiler missing.')
        if not args.skip_build:
            report['steps'].append(run('lint',['verilator_bin','--lint-only','-Wall','--top-module','kwt_icb_encoder_mac3','-Irtl/encoder']+[str(p) for p in rtl]))
            up=upstream/'rtl/e203'
            report['steps'].append(run('verilator',['verilator_bin','--cc','--no-timing','--Wno-fatal','--top-module','kwt_encoder_cpu_soc',
                '--Mdir',str(obj),'-Ibuild/encoder_cpu','-Irtl/encoder','-I'+str(up/'core'),'-I'+str(up/'perips'),
                '-I'+str(up/'perips/apb_i2c'),'-DDISABLE_SV_ASSERTION=1',str(BUILD/'kwt_encoder_cpu_soc.sv')]
                +[str(p) for p in sorted(up.rglob('*.v'))]+[str(p) for p in rtl]))
            if any('third_party' not in line for line in (REPORT/'verilator.log').read_text().splitlines() if line.startswith('%Warning')):
                raise ValueError('New project warning.')
            include=ROOT/'tools/oss-cad-suite/share/verilator/include'
            units=sorted(obj.glob('Vkwt_encoder_cpu_soc*.cpp'))+[ROOT/'build/encoder_perf/sim_encoder_cpu.cpp',include/'verilated.cpp',include/'verilated_threads.cpp']

            def compile_one(source):
                output=BUILD/'native'/(source.stem+'.o')
                run('native-'+source.stem,[cpp,'-std=c++20','-O3','-pthread','-DVL_TIME_CONTEXT','-DVM_COVERAGE=0','-DVM_TRACE=0','-DVM_TIMING=0',
                    '-I'+str(include),'-I'+str(include/'vltstd'),'-I'+str(obj),'-c',str(source),'-o',str(output)])
                return str(output)

            with ThreadPoolExecutor(max_workers=4) as workers:
                objects=list(workers.map(compile_one,units))
            report['steps'].append(run('link',[cpp,'-static','-pthread']+objects+['-o',str(exe)]))
            (BUILD/'build-sources.json').write_text(json.dumps(seal,indent=2))
        elif json.loads((BUILD/'build-sources.json').read_text())!=seal:
            raise ValueError('Source changed; rebuild required.')
        n=min(args.jobs,args.tasks); first=0; groups=[]
        for i in range(n):
            count=args.tasks//n+int(i<args.tasks%n)
            groups.append((first,count)); first+=count
        report.update(source_sha256=seal,firmware_binary_sha256=digest(ROOT/'build/encoder_cpu/firmware.bin'),
            simulator_sha256=digest(exe),tasks_requested=args.tasks,host_parallel_jobs=n,groups=groups)
        save()

        def run_group(group):
            first,count=group
            return run(f'run-{first:02d}',[str(exe),f'+TASKS={count}',f'+FIRST_TASK={first}',
                '+FIRMWARE='+str(fw),'+RESULT_DIR='+str(BUILD/'results'),'+EXPECTED_READS=643652'])

        with ThreadPoolExecutor(max_workers=n) as workers:
            for step in workers.map(run_group,groups):
                report['steps'].append(step); save()
        text='\n'.join((REPORT/f'run-{first:02d}.log').read_text() for first,count in groups)
        records=[{k:int(v) for k,v in re.findall(r'(\w+)=(\d+)',line)} for line in text.splitlines() if line.startswith('CPU_ENCODER_TASK_PASS')]
        records.sort(key=lambda r:r['task'])
        if [r['task'] for r in records]!=list(range(args.tasks)):
            raise ValueError('Incomplete tasks.')
        traces=sorted(map(int,re.findall(r'CPU_ENCODER_TRACE_PASS task=(\d+) count=1603800',text)))
        if traces!=list(range(args.tasks)):
            raise ValueError('Missing full intermediate comparison.')
        maths={int(t):int(c) for t,c in re.findall(r'PERF_MATH task=(\d+) cycles=(\d+)',text)}
        state_records={}
        for task,state,cycles in re.findall(r'PERF_STATE task=(\d+) state=(\d+) cycles=(\d+)',text):
            state_records.setdefault(int(task),{})[state]=int(cycles)
        for r in records:
            i=r['task']; path=BUILD/f'results/task_{i:02d}_codes.hex'
            codes=np.array([int(v,16) for v in path.read_text().split()],dtype='<u2').view('<i2')
            trace=BUILD/f'results/task_{i:02d}_trace.bin'
            expected=ROOT/f'build/encoder/vectors/task_{i:02d}_expected.bin'
            if codes.size!=6336 or codes.tobytes()!=expected.read_bytes() or digest(trace)!=digest(ROOT/f'build/encoder/vectors/task_{i:02d}_trace.bin'):
                raise ValueError('CPU result/intermediate mismatch.')
            if state_records[i]['8']!=0:
                raise ValueError('Old B_REQ state still executed.')
            (BUILD/f'results/task_{i:02d}_output.bin').write_bytes(codes.tobytes())
            r.update(bit_exact=True,output_sha256=digest(expected),trace_sha256=digest(trace),math_cycles=maths[i],state_cycles=state_records[i])
        selected=records[:min(12,args.tasks)]; base=prior['tasks'][:len(selected)]
        total=sum(r['task_cycles'] for r in selected); base_total=sum(r['task_cycles'] for r in base)
        for name,expected in seal.items():
            if digest(ROOT/name)!=expected:
                raise ValueError('Source changed during experiment '+name)
        report.update(status='passed',scope='local twelve-layer MAC schedule experiment with original real E203 firmware',
            task_count=len(records),tasks=records,comparison_tasks=len(selected),total_cycles=total,baseline_total_cycles=base_total,
            cycle_reduction_percent=100*(1-total/base_total),throughput_ratio=base_total/total,
            cpu_firmware_unchanged=True,all_intermediates_and_outputs_bit_exact=True,
            math_cycle_saving_per_task=9228384,expected_math_cycles=52449024,
            official_platform_integrated=False,target_150mhz_timing_verified=False,area_power_energy_verified=False,
            official_performance_tasks=False,downloads_during_this_work=False)
        if any(r['math_cycles']!=52449024 for r in records):
            raise ValueError('Unexpected actual math cycle budget.')
        save()
        print(json.dumps({k:report[k] for k in ['status','task_count','total_cycles','cycle_reduction_percent','throughput_ratio']},indent=2))
    except Exception:
        report['status']='failed'; save(); raise


if __name__=='__main__':
    main()
