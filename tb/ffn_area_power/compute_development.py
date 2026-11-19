"""Run existing twelve-layer normal scenarios on C generated from frozen CROSS."""
from pathlib import Path
import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'scripts/server')]
from area_power_compute import transform_core
from area_power_observers import adapt_native_bench
from check_ffn_post_dma_rtl_native import bench, vectors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenarios', nargs='+', choices=['actual12', 'mixed_paused', 'single'],
                        default=['actual12', 'mixed_paused', 'single'])
    args = parser.parse_args()
    parallel = json.loads((ROOT / 'constraints/ffn_parallel.json').read_text())
    label = 'C-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    out = ROOT / 'build/optimization/ffn_area_power/development/compute' / label
    report = ROOT / 'reports/optimization/ffn_area_power/development/compute' / label
    out.mkdir(parents=True)
    report.mkdir(parents=True)
    frozen = ROOT / 'build/optimization/rtl_sources/ffn_tp_CROSS'
    source = out / 'rtl_sources'
    shutil.copytree(str(frozen), str(source))
    for helper in [ROOT / 'scripts/area_power_compute.py', ROOT / 'scripts/server/area_power_observers.py', Path(__file__)]:
        shutil.copyfile(str(helper), str(report / helper.name))
    kernel = source / 'encoder/kwt_encoder.sv'
    kernel.write_text(transform_core(kernel.read_text()), encoding='utf-8')
    manifest = dict(features=dict(lanes16=True), layout='tile', dma=True, output_dma=True)
    vectors(out / 'vectors', manifest)
    tb = out / 'compute_tb.sv'
    tb.write_text(adapt_native_bench(bench(manifest), ['C']), encoding='utf-8')
    files = [ROOT / 'rtl/kwt_sram16x1024_model.sv', ROOT / 'rtl/kwt_spmem16.sv', ROOT / 'rtl/kwt_requantize.sv']
    files += sorted((source / 'encoder').glob('*.sv')) + sorted((source / 'encoder_bus').glob('*.sv')) + [tb]
    records = dict(variant='C', hardware=['C'], frozen_source=str(frozen.relative_to(ROOT)),
                   source=str(source.relative_to(ROOT)), settings=parallel, scenarios={},
                   scope='Local existing accelerator PIO/DMA normal scenarios; public CPU and SS PPA are separate')
    stage = 'compile'
    try:
        with (report / 'compile.log').open('w') as log:
            subprocess.run(['iverilog', '-g2012', '-DVERILATOR', '-s', 'row_reuse_tb',
                            '-I', str(source / 'encoder'), '-o', str(out / 'compute.vvp')] + [str(p) for p in files],
                           cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, check=True)
        options = {'actual12': [], 'mixed_paused': ['+MIXED'], 'single': ['+SINGLE']}
        expected_counts = dict(initial_bias_pairs=8, seed_waits=1583, next_bias_requests=12664,
                               first_requests=1583, follow_requests=11081, reseed_pairs=12664,
                               shadow_captures=0, push_cycles=12672, push_words=25344, pair_pushes=12672)
        for stage in args.scenarios:
            path = report / (stage + '.log')
            with path.open('w') as log:
                subprocess.run(['vvp', str(out / 'compute.vvp'), '+VECTOR_DIR=' + (out / 'vectors').as_posix(),
                                '+ROW_GROUP=1', '+STREAM', '+DOUBLE'] + options[stage],
                               cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, check=True)
            content = path.read_text()
            counts = []
            for line in content.splitlines():
                if line.startswith('AREA_POWER_COMPUTE_COUNTS '):
                    counts.append(dict((key, int(value)) for key, value in re.findall(r'(\w+)=(\d+)', line)))
            count_pass = len(counts) == 12 and all(all(row.get(key) == value for key, value in expected_counts.items()) for row in counts)
            passed = ('FFN_NEXT_RTL_ALL_PASS' in content and
                      content.count('FFN_NEXT_RTL_PASS layer=') == 12 and count_pass)
            records['scenarios'][stage] = dict(passed=passed, tasks=12, outputs_per_task=25344,
                                               ordered_trace=True, exact_product_and_seed_counts=True,
                                               reseed_identity_observed=True, counters=counts)
            (report / 'result.json').write_text(json.dumps(records, indent=2))
            if not passed:
                raise RuntimeError('Incomplete normal layer checks or C event counts: ' + stage)
            print('C', stage, 'PASS', flush=True)
    except Exception as error:
        records.update(failed_stage=stage, error=str(error))
        (report / 'result.json').write_text(json.dumps(records, indent=2))
        print(str(report.relative_to(ROOT)), flush=True)
        raise
    records['passed'] = True
    (report / 'result.json').write_text(json.dumps(records, indent=2))
    print(str(report.relative_to(ROOT)), flush=True)


if __name__ == '__main__':
    main()
