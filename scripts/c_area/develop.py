"""Local full-accelerator normal tests, without native CPU or EDA execution."""
import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from prepare import ROOT, BUILD, REPORT, prepare
from observers import adapt_native_bench

sys.path.insert(0, str(ROOT/'scripts/server'))
from check_ffn_c_area_rtl_native import bench, vectors


def main():
    parser=argparse.ArgumentParser();parser.add_argument('variant');args=parser.parse_args()
    manifest, source = prepare(args.variant)
    out = BUILD/'development'/args.variant
    out.mkdir(parents=True, exist_ok=True)
    report = REPORT/'development'/args.variant
    report.mkdir(parents=True, exist_ok=True)
    for path in [Path(__file__).parent/'prepare.py', Path(__file__).parent/'observers.py', Path(__file__)]:
        ast.parse(path.read_text(), feature_version=(3, 6))
    vectors(out/'vectors', manifest)
    tb = out/'c_area_tb.sv'
    tb.write_text(adapt_native_bench(bench(manifest),manifest['hardware']))
    files = [ROOT/'rtl/kwt_sram16x1024_model.sv', ROOT/'rtl/kwt_spmem16.sv', ROOT/'rtl/kwt_requantize.sv']
    files += sorted((source/'encoder').glob('*.sv')) + sorted((source/'encoder_bus').glob('*.sv')) + [tb]
    target = out/'verilator'
    with (report/'compile.log').open('w') as log:
        subprocess.run(['verilator_bin.exe','--cc','--exe','--main','--timing','--compiler','gcc','-Wno-fatal',
            '--top-module','row_reuse_tb','--output-split','20000','--Mdir',str(target),'-I'+str(source/'encoder')]+
            [str(p) for p in files],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
        subprocess.run(['mingw32-make','-C',str(target),'-f','Vrow_reuse_tb.mk',
            'VERILATOR_ROOT=E:/xpian/tools/oss-cad-suite/share/verilator',
            'PYTHON3=E:/xpian/.venv/Scripts/python.exe','-j','4'],
            cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    results=[]
    for scenario,options in [('actual12',[]),('mixed_paused',['+MIXED']),('single',['+SINGLE'])]:
        with (report/(scenario+'.log')).open('w') as log:
            subprocess.run([str(target/'Vrow_reuse_tb.exe'),'+VECTOR_DIR='+str(out/'vectors'),
                '+ROW_GROUP=2','+STREAM','+DOUBLE']+options,cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
        text = (report/(scenario+'.log')).read_text()
        if text.count('FFN_NEXT_RTL_PASS layer=') != 12 or 'FFN_NEXT_RTL_ALL_PASS' not in text:
            raise RuntimeError('Incomplete normal scenario: '+scenario)
        row=dict(scenario=scenario,passed=True,tasks=12,outputs_per_task=25344,ordered_trace=True,
                 contributions_per_output=64,bias_per_output=1,compute_lanes=32,physical_weight_banks=16)
        results.append(row)
        (report/(scenario+'.json')).write_text(json.dumps(row,indent=2))
        print('COLUMN_PARALLEL_LOCAL_PASS',scenario,flush=True)
    (report/'acceptance.json').write_text(json.dumps(dict(passed=True,results=results,
        tasks=36,outputs=912384,backend='Verilator local accelerator/DMA normal scenarios',
        native_CPU=False,native_PPA=False,published_C_unchanged=True),indent=2))


if __name__=='__main__':main()
