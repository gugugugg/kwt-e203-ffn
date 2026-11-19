"""Replay the existing cases with the original parameter writer as a shadow."""
import os
from pathlib import Path
import subprocess

from eco import NAME, materialize_rtl

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/optimization" / NAME
WORK = ROOT / "build/optimization" / NAME / "local"
BASE = ROOT / "build/optimization/complete_soc/ffn_trb_4x32"
SOURCE = ROOT / "build/optimization/rtl_sources/ffn_trb_4x32/encoder"
PARENT = ROOT / "reports/optimization/ffn_trb_4x32_private_sram/kwt_threebank_core.sv"

SHADOW = """    reg [31:0] expected_bias[0:1][0:31];
    reg [7:0] expected_shift[0:1][0:31];
    reg [39:0] valid[0:1];
    integer writes_in_cycle;
    integer dual_writes=0;
    reg prior_done=0;
    always @(posedge clk) begin
        writes_in_cycle=0;
        if (!rst_n || core.starting) begin
            valid[0]=0;
            valid[1]=0;
        end else if (core.busy && !core.load_input)
            for (integer lane=0;lane<2;lane=lane+1) begin
                if (core.load_count>lane && core.load_offset+lane<40) begin
                    if (core.load_offset+lane<32)
                        expected_bias[core.load_tile[0]][5'(core.load_offset+lane)]=core.front[lane];
                    else
                        for(integer sub=0;sub<4;sub=sub+1)
                            expected_shift[core.load_tile[0]][{3'(core.load_offset+lane),2'(sub)}]
                                =core.front[lane][8*sub+:8];
                    valid[core.load_tile[0]][core.load_offset+lane]=1;
                    writes_in_cycle++;
                end
            end
        if (writes_in_cycle==2) dual_writes++;
    end
    always @(negedge clk) begin
        for (integer page=0;page<2;page++)
            for (integer col=0;col<32;col++) begin
                if (valid[page][col] && core.bias[page][col] !== expected_bias[page][col])
                    $fatal(1,"bias state mismatch page=%0d col=%0d",page,col);
                if (valid[page][32+col/4] && core.shift[page][col] !== expected_shift[page][col])
                    $fatal(1,"shift state mismatch page=%0d col=%0d",page,col);
            end
        if (done && !prior_done) begin
            if (dual_writes==0) $fatal(1,"no dual parameter writes exercised");
            $display("PARAMETER_STATE_MATCH dual_cycles=%0d",dual_writes);
            dual_writes=0;
        end
        prior_done=done;
    end
"""


def run(args, log):
    with (REPORT / log).open("w") as output:
        subprocess.run([str(arg) for arg in args], cwd=str(ROOT), stdout=output,
                       stderr=subprocess.STDOUT, check=True)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)
    core = REPORT / "kwt_threebank_core.sv"
    materialize_rtl(PARENT, core)
    bench = WORK / "core_tb.sv"
    original = (BASE / "local/core/core_tb.sv").read_text()
    bench.write_text(original.replace("    kwt_shared_icb_sm40 mem(.*);",
                                      "    kwt_shared_icb_sm40 mem(.*);\n" + SHADOW))
    cad = ROOT / "tools/oss-cad-suite"
    share = cad / "share/verilator"
    os.environ["VERILATOR_ROOT"] = share.as_posix()
    run([cad / "bin/verilator_bin.exe", "--cc", "--exe", "--main", "--timing", "-Wno-fatal",
         "--top-module", "threebank_core_tb", "--Mdir", WORK, core,
         SOURCE / "kwt_ffn_clock_gate.sv", SOURCE / "kwt_ffn_requantize.sv",
         BASE / "kwt_shared_dma_icb_sm40.sv", BASE / "local/ram.sv", bench], "local-verilator.log")
    run(["mingw32-make.exe", "-C", WORK, "-f", "Vthreebank_core_tb.mk",
         "VERILATOR_ROOT=" + share.as_posix(), "-j4"], "local-compile.log")
    binary = WORK / "Vthreebank_core_tb.exe"
    run([binary, "+TASKS=12"], "local-actual12.log")
    run([binary, "+TASKS=1", "+CPU_PRESSURE"], "local-pressure.log")


if __name__ == "__main__":
    main()
