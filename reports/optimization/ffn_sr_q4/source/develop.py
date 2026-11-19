"""Run the existing SR normal interface regressions against the isolated Q4 RTL."""
from concurrent.futures import ThreadPoolExecutor
import subprocess
import sys

from prepare import BUILD, REPORT, ROOT, VARIANT, dump, prepare
sys.path[:0] = [str(ROOT/'scripts'), str(ROOT/'scripts/server')]
from check_ffn_sr_area_rtl_native import bench, vectors
from sr_area.observers import adapt_native_bench


def run(args, logfile):
    with logfile.open('w') as stream:
        subprocess.run(args,cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT,check=True)
    return logfile.read_text(errors='replace')


def main():
    manifest, _, candidate = prepare()
    out=BUILD/'development'
    out.mkdir(parents=True,exist_ok=True)
    vectors(out/'vectors',manifest)
    tb=out/'q4_tb.sv'
    tb.write_text(adapt_native_bench(bench(manifest),manifest['hardware']))
    files=[ROOT/'rtl'/leaf for leaf in ('kwt_sram16x1024_model.sv','kwt_spmem16.sv','kwt_requantize.sv')]
    files+=sorted((candidate/'encoder').glob('*.sv'))+sorted((candidate/'encoder_bus').glob('*.sv'))
    target=out/'verilator'
    run(['verilator_bin.exe','--cc','--exe','--main','--timing','--compiler','gcc',
         '-Wno-fatal','--top-module','row_reuse_tb','--output-split','20000','--Mdir',str(target),
         '-I'+str(candidate/'encoder')]+[str(p) for p in files]+[str(tb)],REPORT/'local-elaborate.log')
    run(['mingw32-make','-C',str(target),'-f','Vrow_reuse_tb.mk',
         'VERILATOR_ROOT=E:/xpian/tools/oss-cad-suite/share/verilator',
         'PYTHON3=E:/xpian/.venv/Scripts/python.exe','-j','4'],REPORT/'local-build.log')
    args=[str(target/'Vrow_reuse_tb.exe'),'+VECTOR_DIR='+str(out/'vectors'),'+ROW_GROUP=2','+STREAM','+DOUBLE']

    def scenario(entry):
        name, opts = entry
        log=run(args+opts,REPORT/('local-'+name+'.log'))
        if log.count('FFN_NEXT_RTL_PASS layer=')!=12 or 'FFN_NEXT_RTL_ALL_PASS' not in log:
            raise RuntimeError('Incomplete Q4 local scenario '+name)
        print('Q4_LOCAL_PASS',name,flush=True)
        return dict(scenario=name,tasks=12,ordered_outputs=304128)

    with ThreadPoolExecutor(max_workers=3) as pool:
        rows=list(pool.map(scenario,[('actual12',[]),('mixed_paused',['+MIXED']),('single',['+SINGLE'])]))
    dump(REPORT/'local-acceptance.json',dict(variant=VARIANT,passed=True,scenarios=rows))


if __name__=='__main__':
    main()
