"""Run the existing real-input dual-mode ICB/trace checks for each optimization."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import time
from materialize_ffn_loading_dma import prepare, variants
from ffn_loading_dma import load
VARIANTS=variants()

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('variant', choices=VARIANTS)
    parser.add_argument('--package', default='models/kwt_unified_v1')
    parser.add_argument('--vectors', default='build/unified/vectors')
    parser.add_argument('--linear-only', action='store_true')
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--stall-output', action='store_true')
    parser.add_argument('--single-output', action='store_true')
    parser.add_argument('--mixed-output', action='store_true')
    parser.add_argument('--label', default='baseline_parameters')
    args = parser.parse_args()
    out = ROOT / 'build/optimization/rtl' / args.variant
    report = ROOT / 'reports/optimization/rtl' / args.variant
    obj, native = out / 'obj', out / 'native'
    for p in [obj, native, report]:
        p.mkdir(parents=True, exist_ok=True)
    def run(name, cmd):
        with (report / (name + '.log')).open('w') as stream:
            subprocess.run(cmd, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    if not args.skip_build:
        snapshot = prepare(args.variant)
        rtl = [ROOT / 'rtl/kwt_sram16x1024_model.sv', ROOT / 'rtl/kwt_spmem16.sv', ROOT / 'rtl/kwt_requantize.sv']
        rtl += sorted((snapshot / 'encoder').glob('*.sv')) + sorted((snapshot / 'encoder_bus').glob('*.sv'))
        run('verilator', ['verilator_bin', '--cc', '--Wno-fatal', '--top-module', 'kwt_icb_encoder',
            '-I' + str(snapshot / 'encoder'), '--Mdir', str(obj)] + [str(p) for p in rtl])
        include = ROOT / 'tools/oss-cad-suite/share/verilator/include'
        sources = sorted(obj.glob('Vkwt_icb_encoder*.cpp')) + [ROOT / 'tb/ffn_loading_dma/sim_unified.cpp',
                   include / 'verilated.cpp', include / 'verilated_threads.cpp']
        compiler = shutil.which('g++')
        def compile_one(source):
            output = native / (source.stem + '.o')
            run('compile-' + source.stem, [compiler, '-std=c++20', '-O2', '-pthread', '-DVL_TIME_CONTEXT',
                '-DRESIDUAL_ROW_GROUP=%d'%load(args.variant)['changes'].get('row_group',2 if load(args.variant)['effective_changes'].get('row_pair') else 1),
                '-DLOADING_DMA_ENABLED=%d'%load(args.variant)['dma'], '-DLOADING_DMA_OUTPUT=%d'%load(args.variant)['output_dma'], '-DLOADING_DMA_TILE=%d'%(load(args.variant)['layout']=='tile'), '-DLOADING_DMA_LANES=%d'%(16 if load(args.variant)['features']['lanes16'] else 8),
                '-DRESIDUAL_STREAM=%d'%bool(load(args.variant)['changes'].get('stream')),
                '-DRESIDUAL_DOUBLE_BUFFER=%d'%bool(load(args.variant)['changes'].get('double_buffer')), '-DVM_COVERAGE=0', '-DVM_TRACE=0', '-DVM_TIMING=0', '-I' + str(include),
                '-I' + str(include / 'vltstd'), '-I' + str(obj), '-c', str(source), '-o', str(output)])
            return str(output)
        with ThreadPoolExecutor(max_workers=4) as workers:
            objects = list(workers.map(compile_one, sources))
        run('link', [compiler, '-static', '-pthread'] + objects + ['-o', str(out / 'sim.exe')])
    start = time.perf_counter()
    scope = 'linear' if args.linear_only else 'mixed'
    packed = 'OUTPUT' in VARIANTS[args.variant] and not args.single_output
    if args.stall_output:
        scope = 'linear-stall'
    if args.mixed_output:
        scope = 'linear-mixed'
    command = [str(out / 'sim.exe'), scope, args.package, args.vectors, 'packed' if packed else 'single']
    run(args.label, command)
    result = {'variant': args.variant, 'defines': VARIANTS[args.variant], 'passed': True,
              'scope': 'accelerator ICB RTL, actual-input final and intermediate integer comparisons',
              'linear_tasks': 12, 'encoder_tasks': 0 if args.linear_only else 2,
              'package': args.package, 'vectors': args.vectors, 'packed_output': packed,
              'elapsed_seconds': time.perf_counter() - start,
              'task_lines': [s for s in (report / (args.label + '.log')).read_text().splitlines()
                             if '_PASS' in s]}
    (report / (args.label + '.json')).write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
