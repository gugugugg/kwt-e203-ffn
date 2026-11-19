"""Check new compute deltas with the existing twelve-layer ICB/trace fixture."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import time

from materialize_ffn_codegen_schedule import schedule, booth, split_accumulator, gray_address, cut_through, expand_fifo
from post_dma_compute import transform

ROOT = Path(__file__).resolve().parents[1]
BASE = 'build/optimization/ffn_transport/frozen_baseline/rtl_sources'
INHERITED = 'build/optimization/rtl_sources/ffn_tr_dev_HFSQG'
CASES = {
    'AREG': (BASE, (), ('AREG',)),
    'QD4': (BASE, (), ('QD4',)),
    'PM': (BASE, (), ('PM',)),
    'AREG_PM': (BASE, (), ('AREG', 'PM')),
    'M_PM': (BASE, ('M',), ('PM',)),
    'D18_PM': (BASE, ('D18',), ('PM',)),
    'inherited_all': (INHERITED, ('P', 'E', 'M', 'D18', 'GADDR', 'U', 'FIFO64'), ('AREG', 'PM', 'QD4')),
}


def prepare(case, destination):
    parent, inherited, flags = CASES[case]
    shutil.copytree(ROOT / parent, destination, dirs_exist_ok=True)
    core = destination / 'encoder/kwt_encoder.sv'
    text = core.read_text()
    if set(inherited) & {'P', 'E'}:
        text = schedule(text, 'P' in inherited, 'E' in inherited)
    for flag, function in [('M', booth), ('D18', split_accumulator), ('GADDR', gray_address),
                           ('U', cut_through), ('FIFO64', expand_fifo)]:
        if flag in inherited:
            text = function(text)
    text = transform(text, flags)
    core.write_text(text, newline='\n')
    record = dict(parent=parent, inherited=list(inherited), compute=list(flags))
    (destination / 'compute-configuration.json').write_text(json.dumps(record, indent=2))
    return record


def check(case, run_name, labels):
    build = ROOT / 'build/optimization/ffn_post_dma/development' / run_name / ('compute_' + case)
    report = ROOT / 'reports/optimization/ffn_post_dma/development' / run_name / ('compute_' + case)
    obj, native = build / 'obj', build / 'native'
    for folder in [obj, native, report]:
        folder.mkdir(parents=True, exist_ok=True)
    result = dict(case=case, purpose='implementation_check', passed=False, scenarios={})
    start = time.perf_counter()

    def run(label, command):
        with (report / (label + '.log')).open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)

    try:
        snapshot = build / 'rtl_sources'
        result.update(prepare(case, snapshot))
        rtl = [ROOT / 'rtl/kwt_sram16x1024_model.sv', ROOT / 'rtl/kwt_spmem16.sv', ROOT / 'rtl/kwt_requantize.sv']
        rtl += sorted((snapshot / 'encoder').glob('*.sv')) + sorted((snapshot / 'encoder_bus').glob('*.sv'))
        run('verilator', ['verilator_bin', '--cc', '--Wno-fatal', '--top-module', 'kwt_icb_encoder',
                         '-I' + str(snapshot / 'encoder'), '--Mdir', str(obj)] + [str(p) for p in rtl])
        include = ROOT / 'tools/oss-cad-suite/share/verilator/include'
        sources = sorted(obj.glob('Vkwt_icb_encoder*.cpp')) + [ROOT / 'tb/ffn_post_dma/compute_sim.cpp',
                   include / 'verilated.cpp', include / 'verilated_threads.cpp']
        compiler = shutil.which('g++')

        def compile_one(source):
            output = native / (source.stem + '.o')
            run('compile-' + source.stem, [compiler, '-std=c++20', '-O2', '-pthread', '-DVL_TIME_CONTEXT',
                '-DRESIDUAL_ROW_GROUP=1', '-DRESIDUAL_STREAM=1', '-DRESIDUAL_DOUBLE_BUFFER=1',
                '-DVM_COVERAGE=0', '-DVM_TRACE=0', '-DVM_TIMING=0', '-I' + str(include),
                '-I' + str(include / 'vltstd'), '-I' + str(obj), '-c', str(source), '-o', str(output)])
            return str(output)

        with ThreadPoolExecutor(max_workers=4) as workers:
            objects = list(workers.map(compile_one, sources))
        executable = build / 'sim.exe'
        run('link', [compiler, '-static', '-pthread'] + objects + ['-o', str(executable)])
        for label in labels:
            run(label, [str(executable), label, 'models/kwt_unified_optimized_v1',
                        'build/optimization/quantization/Q2_training_range'])
            lines = [line for line in (report / (label + '.log')).read_text().splitlines() if '_PASS' in line]
            result['scenarios'][label] = dict(passed=True, task_lines=lines)
        result['passed'] = True
    except Exception as error:
        result['error'] = str(error)
    result['elapsed_seconds'] = time.perf_counter() - start
    (report / 'result.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(dict(case=case, passed=result['passed'], report=str(report),
                         error=result.get('error'))), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', nargs='+', choices=CASES, default=list(CASES))
    parser.add_argument('--labels', nargs='+', choices=['actual12', 'mixed_paused', 'single'],
                        default=['actual12', 'mixed_paused', 'single'])
    parser.add_argument('--run', default=datetime.now().strftime('compute-%Y%m%d-%H%M%S'))
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=2) as workers:
        rows = list(workers.map(lambda case: check(case, args.run, args.labels), args.cases))
    report = ROOT / 'reports/optimization/ffn_post_dma/development' / args.run
    report.mkdir(parents=True, exist_ok=True)
    passed = all(row['passed'] for row in rows)
    (report / 'compute-summary.json').write_text(json.dumps(dict(passed=passed, configurations=rows,
        scope='accelerator RTL actual twelve-layer ICB, ordered trace, pause and reload checks'), indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
