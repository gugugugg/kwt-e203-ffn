"""Check the actual12-task stimulus with four-state latch/NBA semantics locally."""
import json
import subprocess
from prepare import ROOT, BUILD, REPORT


def main():
    source=ROOT/'build/optimization/rtl_sources/ffn_cp_C16'
    out=BUILD/'development'
    report=REPORT/'development'
    files=[ROOT/'rtl/kwt_sram16x1024_model.sv',ROOT/'rtl/kwt_spmem16.sv',ROOT/'rtl/kwt_requantize.sv']
    files+=sorted((source/'encoder').glob('*.sv'))+sorted((source/'encoder_bus').glob('*.sv'))+[out/'column_parallel_tb.sv']
    with (report/'four-state-compile.log').open('w') as log:
        subprocess.run(['iverilog','-g2012','-DVERILATOR','-s','row_reuse_tb','-I',str(source/'encoder'),
            '-o',str(out/'four-state.vvp')]+[str(p) for p in files],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    with (report/'four-state-actual12.log').open('w') as log:
        subprocess.run(['vvp',str(out/'four-state.vvp'),'+VECTOR_DIR='+str(out/'vectors'),
            '+ROW_GROUP=2','+STREAM','+DOUBLE'],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
    text=(report/'four-state-actual12.log').read_text()
    if text.count('FFN_NEXT_RTL_PASS layer=')!=12 or 'FFN_NEXT_RTL_ALL_PASS' not in text:
        raise RuntimeError('Incomplete four-state actual12')
    (report/'four-state-actual12.json').write_text(json.dumps(dict(passed=True,tasks=12,outputs=304128,
        ordered_trace=True,compute_lanes=32,backend='Icarus four-state actual HIGH latch and NBA simulation',
        native_CPU=False,native_PPA=False),indent=2))
    print('COLUMN_FOUR_STATE_ACTUAL12_PASS',flush=True)


if __name__=='__main__':main()
