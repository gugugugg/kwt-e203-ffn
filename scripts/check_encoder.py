"""Reproducible full-encoder RTL checks, independently labelled from official acceptance."""
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

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / 'reports/encoder'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tasks', type=int, default=14, choices=range(1, 15))
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args()
    REPORT.mkdir(parents=True, exist_ok=True)
    for name in ['obj', 'native', 'results']:
        (ROOT / 'build/encoder' / name).mkdir(parents=True, exist_ok=True)
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
            raise RuntimeError((REPORT / (name + '.log')).read_text(errors='replace')[-5000:])

    save()
    try:
        rtl = [ROOT / 'rtl/kwt_sram16x1024_model.sv', ROOT / 'rtl/kwt_spmem16.sv'] + sorted((ROOT / 'rtl/encoder').glob('*.sv'))
        sources = rtl + sorted((ROOT / 'rtl/encoder').glob('*.svh')) + sorted((ROOT / 'tb/encoder').glob('*')) + [
            Path(__file__), ROOT / 'scripts/generate_encoder_vectors.py', ROOT / 'scripts/Check-Encoder.ps1',
            ROOT / 'sim/fixed_ops.py', ROOT / 'sim/kwt_fixed.py', ROOT / 'models/kwt1_fixed16_v1/manifest.json']
        source_hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in sources}
        obj = ROOT / 'build/encoder/obj'
        cpp = shutil.which('g++')
        if not cpp:
            raise RuntimeError('Existing native g++ is required.')
        if not args.skip_build:
            run('vectors', [sys.executable, 'scripts/generate_encoder_vectors.py'])
            run('math-compile', ['iverilog', '-g2012', '-s', 'encoder_math_tb', '-o', 'build/encoder/math.vvp',
                                'rtl/encoder/kwt_encoder_div64.sv', 'rtl/encoder/kwt_encoder_sqrt128.sv', 'tb/encoder/encoder_math_tb.sv'])
            run('math', ['vvp', 'build/encoder/math.vvp'])
            run('lint', ['verilator_bin', '--lint-only', '-Wall', '--top-module', 'kwt_encoder', '-Irtl/encoder'] + [str(p) for p in rtl])
            script = 'read_verilog -sv -Irtl/encoder ' + ' '.join(p.relative_to(ROOT).as_posix() for p in rtl)
            script += '; hierarchy -check -top kwt_encoder; proc; opt; memory_dff; memory_collect; opt_clean; check -assert; stat; write_json build/encoder/structure.json; write_verilog -noattr build/encoder/encoder_coarse.v'
            run('structure', ['yosys', '-p', script])
            run('verilator', ['verilator_bin', '--cc', '--top-module', 'kwt_encoder', '-Irtl/encoder',
                              '--Mdir', str(obj)] + [str(p) for p in rtl])
            include = ROOT / 'tools/oss-cad-suite/share/verilator/include'
            units = sorted(obj.glob('Vkwt_encoder*.cpp')) + [ROOT / 'tb/encoder/sim_encoder.cpp', include / 'verilated.cpp', include / 'verilated_threads.cpp']

            def compile_one(source):
                output = ROOT / 'build/encoder/native' / (source.stem + '.o')
                command = [cpp, '-std=c++20', '-O2', '-pthread', '-DVL_TIME_CONTEXT', '-DVM_COVERAGE=0', '-DVM_TRACE=0', '-DVM_TIMING=0',
                           '-I'+str(include), '-I'+str(include / 'vltstd'), '-I'+str(obj), '-c', str(source), '-o', str(output)]
                with (REPORT / ('native-'+source.stem+'.log')).open('w') as stream:
                    subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
                return str(output)

            print('native-compile', flush=True)
            with ThreadPoolExecutor(max_workers=4) as workers:
                objects = list(workers.map(compile_one, units))
            run('link', [cpp, '-static', '-pthread'] + objects + ['-o', str(ROOT / 'build/encoder/encoder_sim.exe')])
            (ROOT / 'build/encoder/build-sources.json').write_text(json.dumps(source_hashes, indent=2))
        elif json.loads((ROOT / 'build/encoder/build-sources.json').read_text()) != source_hashes:
            raise RuntimeError('Encoder sources changed; rebuild required.')
        vectors = json.loads((ROOT / 'build/encoder/vectors/manifest.json').read_text())
        for name, expected in vectors['files'].items():
            if digest(ROOT / 'build/encoder/vectors' / name) != expected:
                raise RuntimeError('Frozen comparison fixture changed: ' + name)
        run('run', [str(ROOT / 'build/encoder/encoder_sim.exe'), str(args.tasks)])
        text = (REPORT / 'run.log').read_text()
        records = [{k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', line)} for line in text.splitlines() if line.startswith('ENCODER_TASK_PASS')]
        if len(records) != args.tasks or f'ENCODER_ALL_PASS tasks={args.tasks} ' not in text:
            raise RuntimeError('Missing full twelve-layer completion evidence.')
        for task in records:
            prefix = f"task_{task['task']:02d}"
            actual = ROOT / 'build/encoder/results' / (prefix + '_output.bin')
            expected = ROOT / 'build/encoder/vectors' / (prefix + '_expected.bin')
            if actual.read_bytes() != expected.read_bytes():
                raise RuntimeError('Saved final encoder differs from integer reference.')
            trace = ROOT / 'build/encoder/results' / (prefix + '_trace.bin')
            if digest(trace) != digest(ROOT / 'build/encoder/vectors' / (prefix + '_trace.bin')):
                raise RuntimeError('Saved full intermediate trace mismatch.')
            task.update(source=vectors['tasks'][task['task']], output_sha256=digest(actual), trace_sha256=digest(trace))
        report.update(status='passed', date='2026-10-21', entry_group='undergraduate', scope='optional full twelve-layer RTL',
                      task_count=args.tasks, tasks=records, layers_per_task=12, final_output_words=args.tasks*6336,
                      intermediate_words=sum(t['trace_words'] for t in records), all_intermediates_bit_exact=True,
                      source_sha256=source_hashes, simulator_sha256=digest(ROOT / 'build/encoder/encoder_sim.exe'),
                      vector_manifest_sha256=digest(ROOT / 'build/encoder/vectors/manifest.json'),
                      numerical_package_sha256=vectors['parameter_manifest_sha256'],
                      mandatory_math_in_rtl=True, reference_answers_loaded_into_rtl=False,
                      official_platform_integrated=False, encoder_real_cpu_integrated=False,
                      official_600_evaluated=False, target_150mhz_timing_verified=False, area_power_verified=False,
                      classifier_in_hardware=False, downloads_during_this_work=False)
        save()
        print(json.dumps({k: report[k] for k in ['status', 'task_count', 'final_output_words', 'intermediate_words']}, indent=2))
    except Exception:
        report['status'] = 'failed'
        save()
        raise


if __name__ == '__main__':
    main()
