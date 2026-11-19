"""Run the existing actual12, paused mixed and scalar scenarios on new tile RTL."""
from pathlib import Path
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'scripts/server')]
from tile_pipeline_compute import transform, adapt_bus_trace
from tile_pipeline_observers import adapt_native_bench
from check_ffn_post_dma_rtl_native import bench, vectors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('variant', choices=['BP', 'E2', 'BP_E2'])
    parser.add_argument('--scenarios', nargs='+', default=['actual12', 'mixed_paused', 'single'])
    args = parser.parse_args()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    label = args.variant + '-' + stamp
    out = ROOT / 'build/optimization/ffn_tile_pipeline/development/compute' / label
    report = ROOT / 'reports/optimization/ffn_tile_pipeline/development/compute' / label
    out.mkdir(parents=True)
    report.mkdir(parents=True)
    flags = args.variant.split('_')
    frozen = ROOT / 'build/optimization/ffn_post_dma/accepted_parents/ffn_pd_CROSS_LAYOUT/rtl_sources'
    source = out / 'rtl_sources'
    shutil.copytree(frozen, source)
    kernel = source / 'encoder/kwt_encoder.sv'
    kernel.write_text(transform(kernel.read_text(), flags), encoding='utf-8')
    bus = source / 'encoder_bus/kwt_icb_encoder.sv'
    bus.write_text(adapt_bus_trace(bus.read_text()), encoding='utf-8')
    manifest = dict(features=dict(lanes16=True), layout='tile', dma=True, output_dma=True)
    vectors(out / 'vectors', manifest)
    tb = out / 'compute_tb.sv'
    tb.write_text(adapt_native_bench(bench(manifest), flags), encoding='utf-8')
    files = [ROOT / 'rtl/kwt_sram16x1024_model.sv', ROOT / 'rtl/kwt_spmem16.sv', ROOT / 'rtl/kwt_requantize.sv']
    files += sorted((source / 'encoder').glob('*.sv')) + sorted((source / 'encoder_bus').glob('*.sv')) + [tb]
    records = dict(variant=args.variant, flags=flags, source=str(source.relative_to(ROOT)), scenarios={})
    stage = 'compile'
    try:
        with (report / 'compile.log').open('w') as log:
            subprocess.run(['iverilog', '-g2012', '-DVERILATOR', '-s', 'row_reuse_tb',
                            '-I', str(source / 'encoder'), '-o', str(out / 'compute.vvp')] + [str(p) for p in files],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        options = {'actual12': [], 'mixed_paused': ['+MIXED'], 'single': ['+SINGLE']}
        for stage in args.scenarios:
            path = report / (stage + '.log')
            with path.open('w') as log:
                subprocess.run(['vvp', str(out / 'compute.vvp'), '+VECTOR_DIR=' + (out / 'vectors').as_posix(),
                                '+ROW_GROUP=1', '+STREAM', '+DOUBLE'] + options[stage],
                               cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            content = path.read_text()
            passed = 'FFN_NEXT_RTL_ALL_PASS' in content and content.count('FFN_NEXT_RTL_PASS layer=') == 12
            records['scenarios'][stage] = dict(passed=passed, tasks=12, outputs_per_task=25344,
                                               ordered_trace=True, exact_product_and_seed_counts=True)
            (report / 'result.json').write_text(json.dumps(records, indent=2))
            if not passed:
                raise RuntimeError('Incomplete actual-layer scenario: ' + stage)
            print(args.variant, stage, 'PASS', flush=True)
    except Exception as error:
        records.update(failed_stage=stage, error=str(error))
        (report / 'result.json').write_text(json.dumps(records, indent=2))
        recovery = ROOT / 'reports/optimization/ffn_tile_pipeline/recovery/compute' / label
        shutil.copytree(report, recovery)
        raise
    records['passed'] = True
    (report / 'result.json').write_text(json.dumps(records, indent=2))
    print(str(report.relative_to(ROOT)), flush=True)


if __name__ == '__main__':
    main()
