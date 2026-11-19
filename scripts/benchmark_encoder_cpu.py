"""Controlled real-E203 firmware ablation, one unchanged encoder/SoC executable.

All variants start cold, load every parameter and compute all twelve layers.
Host concurrency reduces experiment wall time, never reported as hardware speed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/encoder_perf'
REPORT = ROOT / 'reports/encoder_perf'
VARIANTS = ('baseline', 'unroll16', 'packed32')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Upstream local harness changed; inspect adapter: ' + before[:90])
    return text.replace(before, after, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tasks', type=int, choices=range(1, 15), default=14)
    parser.add_argument('--jobs', type=int, choices=range(1, 5), default=4)
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args()
    for folder in [BUILD, REPORT, BUILD/'obj', BUILD/'native']:
        folder.mkdir(parents=True, exist_ok=True)
    report = {'status': 'in_progress', 'scope': 'local same-hardware firmware ablation', 'steps': []}

    def save():
        (REPORT/'checks.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

    def run(name, command):
        start = time.perf_counter()
        print(name, flush=True)
        with (REPORT/(name+'.log')).open('w') as stream:
            process = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        record = {'name': name, 'returncode': process.returncode, 'host_seconds': time.perf_counter()-start}
        if process.returncode:
            raise RuntimeError((REPORT/(name+'.log')).read_text(errors='replace')[-6000:])
        return record

    save()
    try:
        # Preserve the independently accepted original engineering configuration.
        original = json.loads((ROOT/'reports/encoder_cpu/checks.json').read_text())
        if original['status'] != 'passed' or original['task_count'] != 14:
            raise ValueError('Original full CPU regression is required.')
        for name, expected in original['source_sha256'].items():
            if digest(ROOT/name) != expected:
                raise ValueError('Original verified source differs: '+name)
        upstream = ROOT/'third_party/e203_hbirdv2'
        commit = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = subprocess.check_output(['git', '-C', str(upstream), 'status', '--porcelain'], text=True).strip()
        if commit != original['public_e203_commit'] or dirty:
            raise ValueError('Pinned public CPU differs.')
        firmware = json.loads((ROOT/'reports/encoder_cpu/firmware.json').read_text())
        for name, expected in firmware['images_sha256'].items():
            if digest(ROOT/'build/encoder_cpu/images'/name) != expected:
                raise ValueError('Input/parameter fixture differs: '+name)
        manifest = json.loads((ROOT/'build/encoder/vectors/manifest.json').read_text())
        for name, expected in manifest['files'].items():
            if digest(ROOT/'build/encoder/vectors'/name) != expected:
                raise ValueError('Frozen numerical vector differs: '+name)
        if digest(ROOT/'models/kwt1_fixed16_v1/manifest.json') != manifest['parameter_manifest_sha256']:
            raise ValueError('Numerical model manifest differs.')

        # Test-only adapters add selectable firmware/output paths, count assertions,
        # and state occupancy observation. Arithmetic, bus, waits and host are shared.
        sv = (ROOT/'tb/encoder_cpu/kwt_encoder_cpu_soc.sv').read_text()
        sv = replace_once(sv, 'integer i,byte_index,fd,mismatch;',
                         'integer i,byte_index,fd,mismatch;\n    integer expected_shared_reads=643652;\n    reg [63:0] math_cycles=0;\n    reg [63:0] state_cycles[0:45];\n    string firmware_path;')
        sv = replace_once(sv, 'if($value$plusargs("TASKS=%d",requested_tasks)) begin end',
                         'if(!$value$plusargs("FIRMWARE=%s",firmware_path)) $fatal(1,"Missing firmware");\n        if($value$plusargs("EXPECTED_READS=%d",expected_shared_reads)) begin end\n        if($value$plusargs("TASKS=%d",requested_tasks)) begin end')
        sv = replace_once(sv, '$readmemh("build/encoder_cpu/firmware_itcm.hex",', '$readmemh(firmware_path,')
        sv = replace_once(sv, 'starts<=0; resets<=0; output_reads<=0; staged_layers<=0; task_start<=cycles; task_commits<=commits;',
                         'starts<=0; resets<=0; output_reads<=0; staged_layers<=0; task_start<=cycles; task_commits<=commits;\n                                math_cycles<=0;\n                                for(i=0;i<46;i=i+1) state_cycles[i]<=0;')
        sv = replace_once(sv, 'host_task_request<=0; host_layer_request<=0;\n            if(ppi_icb_rsp_valid',
                         'host_task_request<=0; host_layer_request<=0;\n            if(accelerator.core.state>=3 && accelerator.core.state<=42) math_cycles<=math_cycles+1;\n            if(accelerator.core.state<46) state_cycles[accelerator.core.state]<=state_cycles[accelerator.core.state]+1;\n            if(ppi_icb_rsp_valid')
        sv = replace_once(sv, 'mismatch=0; result_name=',
                         'if(shared_reads!=32\'(expected_shared_reads)||shared_writes!=6336) $fatal(1,"Unexpected actual CPU SRAM traffic");\n                                $display("PERF_MATH task=%0d cycles=%0d",current_task,math_cycles);\n                                for(i=0;i<46;i=i+1) $display("PERF_STATE task=%0d state=%0d cycles=%0d",current_task,i,state_cycles[i]);\n                                mismatch=0; result_name=')
        (BUILD/'kwt_encoder_cpu_soc.sv').write_text(sv)
        cpp_text = (ROOT/'tb/encoder_cpu/sim_encoder_cpu.cpp').read_text()
        cpp_text = replace_once(cpp_text, 'struct TraceChecker {', 'static std::string result_dir;\nstruct TraceChecker {')
        cpp_text = replace_once(cpp_text, '"build/encoder_cpu/results/task_%02d_trace.bin",task',
                                '"%s/task_%02d_trace.bin",result_dir.c_str(),task')
        cpp_text = replace_once(cpp_text, 'auto top=std::make_unique<Vkwt_encoder_cpu_soc>(context.get());',
                                'for(int i=1;i<argc;++i) { std::string arg(argv[i]); if(arg.rfind("+RESULT_DIR=",0)==0) result_dir=arg.substr(12); }\n        if(result_dir.empty()) throw std::runtime_error("Missing output directory");\n        auto top=std::make_unique<Vkwt_encoder_cpu_soc>(context.get());')
        (BUILD/'sim_encoder_cpu.cpp').write_text(cpp_text)
        paths = [ROOT/name for name in original['source_sha256']]
        paths += [Path(__file__), ROOT/'scripts/Benchmark-Encoder-CPU.ps1', ROOT/'software/encoder_perf/kwt_encoder_driver_packed.c',
                  BUILD/'kwt_encoder_cpu_soc.sv', BUILD/'sim_encoder_cpu.cpp', ROOT/'build/encoder_cpu/e203_cpu_instance.svh']
        seal = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
        obj = BUILD/'obj'
        exe = BUILD/'encoder_perf_sim.exe'
        cpp = shutil.which('g++')
        if not cpp:
            raise ValueError('Native C++ compiler missing.')
        if not args.skip_build:
            up = upstream/'rtl/e203'
            rtl = [ROOT/'rtl/kwt_sram16x1024_model.sv', ROOT/'rtl/kwt_spmem16.sv']
            rtl += sorted((ROOT/'rtl/encoder').glob('*.sv')) + sorted((ROOT/'rtl/encoder_bus').glob('*.sv'))
            command = ['verilator_bin', '--cc', '--no-timing', '--Wno-fatal', '--top-module', 'kwt_encoder_cpu_soc',
                       '--Mdir', str(obj), '-Ibuild/encoder_cpu', '-Irtl/encoder', '-I'+str(up/'core'),
                       '-I'+str(up/'perips'), '-I'+str(up/'perips/apb_i2c'), '-DDISABLE_SV_ASSERTION=1',
                       str(BUILD/'kwt_encoder_cpu_soc.sv')] + [str(p) for p in sorted(up.rglob('*.v'))] + [str(p) for p in rtl]
            report['steps'].append(run('verilator', command))
            warnings = [line for line in (REPORT/'verilator.log').read_text().splitlines() if line.startswith('%Warning')]
            if any('third_party' not in line for line in warnings):
                raise ValueError('New test adapter RTL warning.')
            include = ROOT/'tools/oss-cad-suite/share/verilator/include'
            units = sorted(obj.glob('Vkwt_encoder_cpu_soc*.cpp')) + [BUILD/'sim_encoder_cpu.cpp', include/'verilated.cpp', include/'verilated_threads.cpp']

            def compile_one(source):
                output = BUILD/'native'/(source.stem+'.o')
                run('native-'+source.stem, [cpp, '-std=c++20', '-O3', '-pthread', '-DVL_TIME_CONTEXT', '-DVM_COVERAGE=0',
                    '-DVM_TRACE=0', '-DVM_TIMING=0', '-I'+str(include), '-I'+str(include/'vltstd'), '-I'+str(obj),
                    '-c', str(source), '-o', str(output)])
                return str(output)

            with ThreadPoolExecutor(max_workers=4) as workers:
                objects = list(workers.map(compile_one, units))
            report['steps'].append(run('link', [cpp, '-static', '-pthread']+objects+['-o', str(exe)]))
            (BUILD/'build-sources.json').write_text(json.dumps(seal, indent=2))
        elif json.loads((BUILD/'build-sources.json').read_text()) != seal:
            raise ValueError('Changed sources; rebuild required.')

        variant_meta = {}
        for variant in VARIANTS:
            folder = BUILD/variant
            folder.mkdir(exist_ok=True)
            (folder/'results').mkdir(exist_ok=True)
            driver = 'software/encoder/kwt_encoder_driver.c' if variant == 'baseline' else 'software/encoder_perf/kwt_encoder_driver_packed.c'
            flags = ['-march=rv32imac_zicsr_zifencei', '-mabi=ilp32', '-msmall-data-limit=0', '-mno-relax',
                     '-ffreestanding', '-fno-builtin', '-O2', '-Wall', '-Wextra', '-Werror', '-nostdlib',
                     '-Isoftware/encoder', '-Tsoftware/cpu_integration/link.ld', '-Wl,--no-relax,-Map,'+str(folder/'firmware.map')]
            if variant == 'unroll16':
                flags += ['-DKWE_SCALAR_UNROLL=1']
            report['steps'].append(run(variant+'-firmware', ['riscv-none-elf-gcc']+flags+[
                'software/cpu_integration/startup.S', 'software/encoder_cpu/main.c', driver, '-lgcc', '-o', str(folder/'firmware.elf')]))
            run(variant+'-objcopy', ['riscv-none-elf-objcopy', '-O', 'binary', str(folder/'firmware.elf'), str(folder/'firmware.bin')])
            run(variant+'-disassembly', ['riscv-none-elf-objdump', '-d', str(folder/'firmware.elf')])
            binary = (folder/'firmware.bin').read_bytes()
            if len(binary) > 65536:
                raise ValueError('Firmware exceeds ITCM.')
            if variant == 'baseline' and digest(folder/'firmware.bin') != digest(ROOT/'build/encoder_cpu/firmware.bin'):
                raise ValueError('Baseline must reproduce the original firmware binary before timing.')
            image = binary+bytes(65536-len(binary))
            (folder/'firmware_itcm.hex').write_text(''.join(f'{int(v):016x}\n' for v in np.frombuffer(image, dtype='<u8')))
            variant_meta[variant] = {'firmware_bytes': len(binary), 'binary_sha256': digest(folder/'firmware.bin'),
                                     'elf_sha256': digest(folder/'firmware.elf'), 'flags': flags}
        report.update(source_sha256=seal, input_images_sha256=firmware['images_sha256'], variants=variant_meta,
                      simulator_sha256=digest(exe), same_simulator_for_all_variants=True,
                      numerical_package_sha256=manifest['parameter_manifest_sha256'], tasks_per_variant=args.tasks,
                      host_parallel_jobs=args.jobs, host_concurrency_is_not_hardware_speedup=True)
        save()
        jobs = []
        for variant in VARIANTS:
            n = min(args.jobs, args.tasks)
            first = 0
            for i in range(n):
                count = args.tasks//n+int(i < args.tasks % n)
                folder = BUILD/variant
                jobs.append((variant, first, count, [str(exe), f'+TASKS={count}', f'+FIRST_TASK={first}',
                    '+FIRMWARE='+str(folder/'firmware_itcm.hex'), '+RESULT_DIR='+str(folder/'results'),
                    '+EXPECTED_READS='+str(321826 if variant == 'packed32' else 643652)]))
                first += count

        def run_group(job):
            variant, first, count, command = job
            step = run(f'{variant}-run-{first:02d}', command)
            text = (REPORT/(step['name']+'.log')).read_text()
            if f'CPU_ENCODER_ALL_PASS tasks={count} first={first} ' not in text:
                raise ValueError('Missing completion '+step['name'])
            return step

        with ThreadPoolExecutor(max_workers=args.jobs) as workers:
            for step in workers.map(run_group, jobs):
                report['steps'].append(step)
                save()
        for variant in VARIANTS:
            text = '\n'.join((REPORT/(f'{v}-run-{first:02d}.log')).read_text() for v, first, count, _ in jobs if v == variant)
            records = [{k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', line)}
                       for line in text.splitlines() if line.startswith('CPU_ENCODER_TASK_PASS')]
            records.sort(key=lambda record: record['task'])
            math = {int(t): int(c) for t, c in re.findall(r'PERF_MATH task=(\d+) cycles=(\d+)', text)}
            states = {}
            for task, state, cycles in re.findall(r'PERF_STATE task=(\d+) state=(\d+) cycles=(\d+)', text):
                states.setdefault(int(task), {})[state] = int(cycles)
            traces = sorted(map(int, re.findall(r'CPU_ENCODER_TRACE_PASS task=(\d+) count=1603800', text)))
            if [r['task'] for r in records] != list(range(args.tasks)) or traces != list(range(args.tasks)):
                raise ValueError('Incomplete variant tasks/trace '+variant)
            for record in records:
                index = record['task']
                folder = BUILD/variant/'results'
                codes = np.array([int(v,16) for v in (folder/f'task_{index:02d}_codes.hex').read_text().splitlines()], dtype='<u2').view('<i2')
                expected = ROOT/f'build/encoder/vectors/task_{index:02d}_expected.bin'
                trace = folder/f'task_{index:02d}_trace.bin'
                if codes.size != 6336 or codes.tobytes() != expected.read_bytes():
                    raise ValueError('Final result differs '+variant)
                if digest(trace) != digest(ROOT/f'build/encoder/vectors/task_{index:02d}_trace.bin'):
                    raise ValueError('Intermediate result differs '+variant)
                (folder/f'task_{index:02d}_output.bin').write_bytes(codes.tobytes())
                record.update(output_sha256=digest(expected), trace_sha256=digest(trace),
                              math_cycles=math[index], state_cycles=states[index], bit_exact=True)
            variant_meta[variant]['tasks'] = records
        baseline = variant_meta['baseline']['tasks']
        for variant in VARIANTS:
            records = variant_meta[variant]['tasks']
            for old, new in zip(baseline, records):
                if old['math_cycles'] != new['math_cycles']:
                    raise ValueError('Math cycle workload changed.')
                if variant == 'baseline' and old['task_cycles'] != original['tasks'][old['task']]['task_cycles']:
                    raise ValueError('Baseline does not reproduce original same-wait timing.')
            # The first twelve local samples cover all twelve labels. Extra tasks
            # are zero/full-range stress checks, excluded from aggregate comparison.
            selected = records[:min(12, args.tasks)]
            base_selected = baseline[:len(selected)]
            total = sum(r['task_cycles'] for r in selected)
            base_total = sum(r['task_cycles'] for r in base_selected)
            variant_meta[variant].update(comparison_tasks=len(selected), total_cycles=total,
                cycle_reduction_percent=100*(1-total/base_total), throughput_ratio=base_total/total,
                mean_task_cycles=total/len(selected),
                shared_read_reduction_percent=100*(1-sum(r['shared_reads'] for r in selected)/sum(r['shared_reads'] for r in base_selected)))
        for name, expected in seal.items():
            if digest(ROOT/name) != expected:
                raise ValueError('Source changed during experiment '+name)
        report.update(status='passed', all_outputs_and_intermediates_bit_exact=True,
            cold_task_caches=True, all_parameters_loaded_each_task=True, same_shared_sram_and_waits=True,
            timing_window='first task loading request through final actual shared SRAM output write',
            original_baseline_cycles_reproduced=True, official_12_performance_tasks=False,
            official_platform_integrated=False, target_150mhz_timing_verified=False,
            area_power_energy_verified=False, downloads_during_this_work=False)
        save()
        lines = ['# 开源 E203 固件同条件性能对照', '',
                 '本地完整十二层编码器；同一硬件仿真可执行文件、同一输入/权重/冷缓存/加载端/总线等待。',
                 '周期包括输入与参数加载、CPU 调度和实际 SRAM 写回。并行主机进程不算硬件加速。', '',
                 '| 配置 | 12 类本地任务总周期 | 周期减少 | 吞吐比 | 每项共享 SRAM 读请求 | 固件字节 |',
                 '| --- | ---: | ---: | ---: | ---: | ---: |']
        for variant in VARIANTS:
            v = variant_meta[variant]
            lines.append(f"| {variant} | {v['total_cycles']:,} | {v['cycle_reduction_percent']:.4f}% | {v['throughput_ratio']:.6f}× | {v['tasks'][0]['shared_reads']:,} | {v['firmware_bytes']} |")
        lines += ['', f'每配置 {args.tasks} 项、每项 12 层；全部最终输出和中间整数值逐位一致。',
                  'baseline=原始逐半字循环；unroll16=仅展开循环；packed32=展开并每次读两个半字。',
                  '使用原 DATA 16 位装载端口，无新增缓存/计算单元/DDR，所有算术留在 RTL。',
                  '最后两项（完整 14 项运行时）为全零/满范围随机压力向量，不混入十二类聚合数据。',
                  '这不是官方 12 个性能任务成绩；未验证 150 MHz、工艺面积或功耗/能耗。',
                  '逐状态占用在 checks.json；原始逐层日志、反汇编和固件哈希在本目录。']
        (REPORT/'README.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
        print(json.dumps({v: {k: variant_meta[v][k] for k in ['total_cycles','cycle_reduction_percent','throughput_ratio']} for v in VARIANTS}, indent=2))
    except Exception:
        report['status'] = 'failed'
        save()
        raise


if __name__ == '__main__':
    main()
