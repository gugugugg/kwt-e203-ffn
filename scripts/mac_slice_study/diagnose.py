from prepare import ROOT,OUT,REPORT,IR
import subprocess
import sys

s=(OUT/'local_tb.sv').read_text()
probe='''initial begin repeat(REPEATS)begin #10000;
 $display("SLICE_DIAGNOSTIC_TIME %t state=%d row=%d",$time,dut.core.state,dut.core.row);$fflush();
 end $finish;end
'''.replace('REPEATS',sys.argv[1] if len(sys.argv)>1 else '30')
(OUT/'diagnostic_tb.sv').write_text(s.replace('endmodule',probe+'endmodule'))
files=[ROOT/'rtl/kwt_sram16x1024_model.sv',ROOT/'rtl/kwt_spmem16.sv',ROOT/'rtl/kwt_requantize.sv']
files+=sorted((IR/'encoder').glob('*.sv'))+sorted((IR/'encoder_bus').glob('*.sv'))
files += [OUT/'local_REF.sv',OUT/'local_SHARE4.sv',OUT/'diagnostic_tb.sv']
with (REPORT/'diagnostic-compile.log').open('w') as log:
 subprocess.run(['iverilog','-g2012','-DVERILATOR','-s','row_reuse_tb','-I',str(IR/'encoder'),'-o',str(OUT/'diagnostic.vvp')]+[str(p) for p in files],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
with (REPORT/'diagnostic.log').open('w') as log:
 subprocess.run(['vvp','-v',str(OUT/'diagnostic.vvp'),'+VECTOR_DIR='+str(ROOT/'build/optimization/rtl/ffn_lp_IR/native_vectors'),'+ROW_GROUP=1','+STREAM','+DOUBLE'],cwd=str(ROOT),stdout=log,stderr=subprocess.STDOUT,check=True)
