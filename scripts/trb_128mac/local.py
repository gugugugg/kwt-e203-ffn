"""Build/run the complete local E203 simulation with synchronous SRAM models."""
import argparse
import os
from pathlib import Path
import subprocess

from build import ROOT, REPORT, SOC

LOCAL = SOC / "local"
BINARY = LOCAL / "Vcomplete_soc_tb.exe"


def run(argv, log):
    with (REPORT / log).open("w", encoding="utf-8") as stream:
        subprocess.run([str(arg) for arg in argv], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def memory_models():
    LOCAL.mkdir(parents=True, exist_ok=True)
    ram = LOCAL / "ram.sv"
    ram.write_text("".join("""
module RAMSP{depth}X16(input CLK,CEN,GWEN,input [15:0] WEN,input [{aw}:0] A,
    input [15:0] D,output reg [15:0] Q,input [2:0] EMA,input [1:0] EMAW,input RET1N);
    reg [15:0] contents[0:{last}];
    always @(posedge CLK) if(!CEN) begin
        if(GWEN) Q<=contents[A];
        else for(integer b=0;b<16;b=b+1) if(!WEN[b]) contents[A][b]<=D[b];
    end
endmodule
""".format(depth=depth, aw=depth.bit_length()-2, last=depth-1) for depth in (128,1024,4096)), encoding="utf-8")
    return ram


def make():
    ram = memory_models()
    upstream=ROOT / "build/server/official_2025/e203_hbirdv2-master/rtl/e203"
    local_bench=LOCAL/"complete_soc_tb.sv"
    original_bench=(SOC/"complete_soc_tb.sv").read_text()
    local_bench.write_text(original_bench.replace("        @(negedge reference_clk);rst_n=1;",
        "        force dut.soc.hfclk=reference_clk;\n        @(negedge reference_clk);rst_n=1;"),encoding="utf-8")
    files=LOCAL/"files.f"
    original=(SOC/"files.f").read_text().splitlines()
    entries=[local_bench.relative_to(ROOT).as_posix() if x.endswith("/complete_soc_tb.sv") else x
             for x in original if not x.startswith("/storage1/")]
    files.write_text("\n".join(entries+[ram.relative_to(ROOT).as_posix()])+"\n",encoding="utf-8")
    cad=ROOT / "tools/oss-cad-suite"
    os.environ["VERILATOR_ROOT"]=(cad/"share/verilator").as_posix()
    run([cad/"bin/verilator_bin.exe","--cc","--exe","--main","--timing","-Wno-fatal",
         "--top-module","complete_soc_tb","--Mdir",LOCAL,"+define+ARM_UD_MODEL",
         *("+incdir+"+str(path) for path in (SOC,upstream/"core",upstream/"perips",upstream/"perips/apb_i2c",
                                            ROOT/"rtl/public_encoder")), "-f", files], "local-verilator.log")
    run(["mingw32-make.exe","-C",LOCAL,"-f","Vcomplete_soc_tb.mk","VERILATOR_ROOT="+(cad/"share/verilator").as_posix(),"-j4"],"local-compile.log")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--build",action="store_true")
    parser.add_argument("--tasks",type=int,default=1)
    args=parser.parse_args()
    if args.build:
        make()
    if not BINARY.is_file():
        BINARY=LOCAL / "Vcomplete_soc_tb"
    (SOC/"results").mkdir(exist_ok=True)
    run([BINARY,"+FIRST_TASK=1","+TASKS=%d"%args.tasks], "local-cpu%02d.log"%args.tasks)



