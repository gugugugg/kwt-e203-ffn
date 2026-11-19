"""Execute actual public E203 RV32 firmware for full twelve-layer encoder jobs."""
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

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/encoder_cpu'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tasks', type=int, default=14, choices=range(1, 15))
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--jobs', type=int, default=4, choices=range(1, 5))
    args = parser.parse_args()
    REPORT.mkdir(parents=True, exist_ok=True)
    for name in ['obj', 'native', 'results']:
        (ROOT / 'build/encoder_cpu' / name).mkdir(parents=True, exist_ok=True)
    steps = []
    report = {'status': 'in_progress', 'steps': steps}
    target = REPORT / 'checks.json'

    def save():
        target.write_text(json.dumps(report, indent=2), encoding='utf-8')

    def run(name, command):
        print(name, flush=True)
        start = time.perf_counter()
        with (REPORT / (name + '.log')).open('w', encoding='utf-8') as stream:
            p = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
        steps.append({'name': name, 'returncode': p.returncode, 'elapsed_host_seconds': time.perf_counter()-start})
        save()
        if p.returncode:
            raise RuntimeError((REPORT / (name + '.log')).read_text(errors='replace')[-6000:])

    save()
    try:
        upstream = ROOT / 'third_party/e203_hbirdv2'
        commit = subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip()
        dirty = subprocess.check_output(['git', '-C', str(upstream), 'status', '--porcelain'], text=True).strip()
        if commit != '9f3e34f337f5d0a1236a285871ffa2032491617a' or dirty:
            raise RuntimeError('Pinned public E203 source changed.')
        # Verify unchanged arithmetic against the completed standalone evidence.
        prior = json.loads((ROOT / 'reports/encoder/checks.json').read_text())
        if prior['status'] != 'passed' or prior['task_count'] != 14:
            raise RuntimeError('Full standalone encoder regression must pass first.')
        for name, value in prior['source_sha256'].items():
            if digest(ROOT / name) != value:
                raise RuntimeError('Previously validated encoder source changed: ' + name)
        paths = sorted((ROOT / 'rtl/encoder').glob('*')) + sorted((ROOT / 'rtl/encoder_bus').glob('*.sv'))
        paths += sorted((ROOT / 'software/encoder').glob('*')) + sorted((ROOT / 'software/encoder_cpu').glob('*'))
        paths += sorted((ROOT / 'tb/encoder_cpu').glob('*')) + [ROOT / 'rtl/kwt_spmem16.sv', ROOT / 'rtl/kwt_sram16x1024_model.sv',
            ROOT / 'software/cpu_integration/startup.S', ROOT / 'software/cpu_integration/link.ld', Path(__file__),
            ROOT / 'scripts/prepare_encoder_cpu.py', ROOT / 'scripts/Check-Encoder-CPU.ps1',
            ROOT / 'tb/encoder_bus/kwt_icb_encoder_tb.sv', ROOT / 'scripts/check_encoder_bus.py', ROOT / 'scripts/Check-Encoder-Bus.ps1',
            ROOT / 'build/encoder/vectors/manifest.json', ROOT / 'models/kwt1_fixed16_v1/manifest.json']
        seal = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
        obj = ROOT / 'build/encoder_cpu/obj'
        cpp = shutil.which('g++')
        if not cpp:
            raise RuntimeError('A real native compiler is required.')
        rtl = [ROOT / 'rtl/kwt_sram16x1024_model.sv', ROOT / 'rtl/kwt_spmem16.sv']
        rtl += sorted((ROOT / 'rtl/encoder').glob('*.sv')) + sorted((ROOT / 'rtl/encoder_bus').glob('*.sv'))
        if not args.skip_build:
            run('prepare', [sys.executable, 'scripts/prepare_encoder_cpu.py'])
            run('bus-checks', [sys.executable, 'scripts/check_encoder_bus.py'])
            run('interface-lint', ['verilator_bin', '--lint-only', '-Wall', '--top-module', 'kwt_icb_encoder', '-Irtl/encoder'] + [str(p) for p in rtl])
            up = upstream / 'rtl/e203'
            command = ['verilator_bin', '--cc', '--no-timing', '--Wno-fatal', '--top-module', 'kwt_encoder_cpu_soc',
                       '--Mdir', str(obj), '-Ibuild/encoder_cpu', '-Irtl/encoder', '-I'+str(up / 'core'),
                       '-I'+str(up / 'perips'), '-I'+str(up / 'perips/apb_i2c'), '-DDISABLE_SV_ASSERTION=1',
                       'tb/encoder_cpu/kwt_encoder_cpu_soc.sv'] + [str(p) for p in sorted(up.rglob('*.v'))] + [str(p) for p in rtl]
            run('verilator', command)
            warnings = [line for line in (REPORT / 'verilator.log').read_text().splitlines() if line.startswith('%Warning')]
            if any('third_party' not in line for line in warnings):
                raise RuntimeError('New project RTL/SoC warning must be fixed before execution.')
            include = ROOT / 'tools/oss-cad-suite/share/verilator/include'
            units = sorted(obj.glob('Vkwt_encoder_cpu_soc*.cpp')) + [ROOT / 'tb/encoder_cpu/sim_encoder_cpu.cpp', include / 'verilated.cpp', include / 'verilated_threads.cpp']

            def compile_one(source):
                output = ROOT / 'build/encoder_cpu/native' / (source.stem + '.o')
                command = [cpp, '-std=c++20', '-O3', '-pthread', '-DVL_TIME_CONTEXT', '-DVM_COVERAGE=0', '-DVM_TRACE=0', '-DVM_TIMING=0',
                           '-I'+str(include), '-I'+str(include / 'vltstd'), '-I'+str(obj), '-c', str(source), '-o', str(output)]
                with (REPORT / ('native-'+source.stem+'.log')).open('w') as stream:
                    subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
                return str(output)

            print('native-compile', flush=True)
            with ThreadPoolExecutor(max_workers=4) as workers:
                objects = list(workers.map(compile_one, units))
            run('link', [cpp, '-static', '-pthread'] + objects + ['-o', str(ROOT / 'build/encoder_cpu/encoder_cpu_sim.exe')])
            (ROOT / 'build/encoder_cpu/build-sources.json').write_text(json.dumps(seal, indent=2))
        elif json.loads((ROOT / 'build/encoder_cpu/build-sources.json').read_text()) != seal:
            raise RuntimeError('Integration sources changed; rebuild needed.')
        firmware = json.loads((REPORT / 'firmware.json').read_text())
        for name, value in firmware['images_sha256'].items():
            if digest(ROOT / 'build/encoder_cpu/images' / name) != value:
                raise RuntimeError('CPU input image changed: ' + name)
        if digest(ROOT / 'build/encoder_cpu/firmware.elf') != firmware['firmware_elf_sha256']:
            raise RuntimeError('CPU firmware changed after preparation.')
        jobs = min(args.jobs, args.tasks)
        groups = []
        first = 0
        for index in range(jobs):
            count = args.tasks//jobs + int(index < args.tasks % jobs)
            groups.append({'first': first, 'count': count})
            first += count
        report.update(host_parallel_simulation_jobs=jobs, simulation_groups=groups,
                      process_parallelism_is_not_hardware_parallelism=True)
        save()
        (REPORT / 'run.log').write_text('IN_PROGRESS: independent real-CPU simulation groups; see run_XX.log\n')

        def run_group(group):
            name = f"run_{group['first']:02d}"
            print(name, flush=True)
            start = time.perf_counter()
            with (REPORT / (name + '.log')).open('w') as stream:
                process = subprocess.run([str(ROOT / 'build/encoder_cpu/encoder_cpu_sim.exe'),
                                          f"+TASKS={group['count']}", f"+FIRST_TASK={group['first']}"],
                                         cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
            if process.returncode:
                raise RuntimeError((REPORT / (name + '.log')).read_text()[-6000:])
            text = (REPORT / (name + '.log')).read_text()
            if f"CPU_ENCODER_ALL_PASS tasks={group['count']} first={group['first']} " not in text:
                raise RuntimeError('Missing real CPU group completion: ' + name)
            return {'name': name, 'returncode': process.returncode, 'elapsed_host_seconds': time.perf_counter()-start}

        with ThreadPoolExecutor(max_workers=jobs) as workers:
            steps.extend(workers.map(run_group, groups))
        text = '\n'.join((REPORT / f"run_{g['first']:02d}.log").read_text() for g in groups)
        (REPORT / 'run.log').write_text(text, encoding='utf-8')
        records = [{k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', line)} for line in text.splitlines() if line.startswith('CPU_ENCODER_TASK_PASS')]
        traces = re.findall(r'CPU_ENCODER_TRACE_PASS task=(\d+) count=1603800', text)
        records.sort(key=lambda task: task['task'])
        if len(records) != args.tasks or sorted(map(int, traces)) != list(range(args.tasks)):
            raise RuntimeError('Missing real CPU completion/trace evidence.')
        manifest = json.loads((ROOT / 'build/encoder/vectors/manifest.json').read_text())
        for index, task in enumerate(records):
            if task['task'] != index:
                raise RuntimeError('Missing or duplicated CPU task index.')
            actual_path = ROOT / f'build/encoder_cpu/results/task_{index:02d}_codes.hex'
            codes = np.array([int(value, 16) for value in actual_path.read_text().splitlines()], dtype='<u2').view('<i2')
            expected = ROOT / f'build/encoder/vectors/task_{index:02d}_expected.bin'
            if codes.size != 6336 or codes.tobytes() != expected.read_bytes() or not np.isfinite(codes.astype('f8')*2.0**-12).all():
                raise RuntimeError('Actual CPU shared SRAM output differs from frozen integer reference.')
            binary = actual_path.with_name(f'task_{index:02d}_output.bin')
            binary.write_bytes(codes.tobytes())
            trace = actual_path.with_name(f'task_{index:02d}_trace.bin')
            if digest(trace) != digest(ROOT / f'build/encoder/vectors/task_{index:02d}_trace.bin'):
                raise RuntimeError('Actual CPU-driven intermediate trace differs.')
            if task['layers'] != 12 or task['load_words'] != 643652 or task['host_words'] != 450752 or task['read'] != 6336 or task['store'] != 6336:
                raise RuntimeError('Real CPU transaction coverage is incomplete.')
            task.update(source=manifest['tasks'][index], output_sha256=digest(binary), trace_sha256=digest(trace),
                        all_intermediates_bit_exact=True, decoded_all_finite=True)
        warnings = {}
        for name in re.findall(r'%Warning-([^:]+):', (REPORT / 'verilator.log').read_text()):
            warnings[name] = warnings.get(name, 0) + 1
        report.update(status='passed', date='2026-10-21', scope='real public E203 CPU RTL executes full twelve-layer encoder firmware',
                      entry_group='undergraduate', optional_scope='complete twelve-layer encoder',
                      public_cpu_firmware_executed=True, encoder_real_cpu_integrated=True,
                      public_e203_commit=commit, public_e203_upstream_modified=False,
                      task_count=args.tasks, tasks=records, final_output_words=args.tasks*6336,
                      intermediate_words=args.tasks*1603800, shared_sram_bytes=524288,
                      cpu_layer_starts=args.tasks*12, one_layer_parameters_resident_at_once=True,
                      layers_reuse_internal_activations=True, mandatory_math_in_accelerator_rtl=True,
                      reference_answers_cpu_accessible=False, classifier_in_hardware=False,
                      host_staging='one 32-bit write per eligible cycle, arbitrated with real CPU ICB memory requests',
                      memory_waits=True, ppi_command_and_response_waits=True,
                      firmware_elf_sha256=firmware['firmware_elf_sha256'],
                      simulator_sha256=digest(ROOT / 'build/encoder_cpu/encoder_cpu_sim.exe'),
                      source_sha256=seal, input_images_sha256=firmware['images_sha256'],
                      numerical_package_sha256=manifest['parameter_manifest_sha256'],
                      upstream_warning_counts=warnings, simulation='cycle-functional Verilator --no-timing; artificial #1 delays ignored',
                      original_cpu_clock_gating_enabled=True, official_platform_integrated=False,
                      target_150mhz_timing_verified=False, area_power_verified=False, official_600_evaluated=False,
                      downloads_during_this_work=False)
        save()
        print(json.dumps({k: report[k] for k in ['status', 'task_count', 'cpu_layer_starts', 'final_output_words', 'intermediate_words']}, indent=2))
    except Exception:
        report['status'] = 'failed'
        save()
        raise


if __name__ == '__main__':
    main()
