"""Compare the gated FIFO data with the original writer in the existing replay."""
import os
import subprocess

from fifo_eco import NAME, REPORT, ROOT, rtl

SOC = ROOT / "build/optimization/complete_soc/ffn_trb_4x32"
SOURCE = ROOT / "build/optimization/rtl_sources/ffn_trb_4x32/encoder"
WORK = ROOT / "build/optimization" / NAME / "local"
SHADOW = """    reg [63:0] expected_fifo[0:16];
    reg [16:0] fifo_initialized=0;
    integer fifo_pushes=0, fifo_overlap=0, fifo_wrap=0;
    reg prior_done=0;
    always @(posedge clk) begin
        if (!rst_n || core.starting) begin
            fifo_initialized=0;
            fifo_pushes=0;
            fifo_overlap=0;
            fifo_wrap=0;
        end else if (core.busy && core.pending_result) begin
            expected_fifo[core.out_tail]={
                core.result_q[3'(core.pending_base+3'd3)],
                core.result_q[3'(core.pending_base+3'd2)],
                core.result_q[3'(core.pending_base+3'd1)],
                core.result_q[core.pending_base]};
            fifo_initialized[core.out_tail]=1;
            fifo_pushes++;
            if (core.result_fire) fifo_overlap++;
            if (core.out_tail==16) fifo_wrap++;
        end
    end
    always @(negedge clk) begin
        for (integer entry=0; entry<17; entry++)
            if (fifo_initialized[entry] && core.out_word[entry] !== expected_fifo[entry])
                $fatal(1,"FIFO state mismatch entry=%0d",entry);
        if (done && !prior_done) begin
            if (fifo_pushes!=6336 || fifo_overlap==0 || fifo_wrap!=372)
                $fatal(1,"FIFO replay did not cover expected queue activity");
            $display("FIFO_STATE_MATCH pushes=%0d overlap=%0d wraps=%0d",
                fifo_pushes,fifo_overlap,fifo_wrap);
        end
        prior_done=done;
    end
"""


def run(args, log):
    with (REPORT / log).open("w") as stream:
        subprocess.run([str(arg) for arg in args], cwd=str(ROOT), stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    core = rtl()
    bench = WORK / "core_tb.sv"
    original = (SOC / "local/core/core_tb.sv").read_text()
    anchor = "    kwt_shared_icb_sm40 mem(.*);"
    assert original.count(anchor) == 1
    bench.write_text(original.replace(anchor, anchor + "\n" + SHADOW))
    cad = ROOT / "tools/oss-cad-suite"
    share = cad / "share/verilator"
    os.environ["VERILATOR_ROOT"] = share.as_posix()
    run([cad / "bin/verilator_bin.exe", "--cc", "--exe", "--main", "--timing", "-Wno-fatal",
         "--top-module", "threebank_core_tb", "--Mdir", WORK, core,
         SOURCE / "kwt_ffn_clock_gate.sv", SOURCE / "kwt_ffn_requantize.sv",
         SOC / "kwt_shared_dma_icb_sm40.sv", SOC / "local/ram.sv", bench], "local-verilator.log")
    run(["mingw32-make.exe", "-C", WORK, "-f", "Vthreebank_core_tb.mk",
         "VERILATOR_ROOT=" + share.as_posix(), "-j4"], "local-compile.log")
    binary = WORK / "Vthreebank_core_tb.exe"
    run([binary, "+TASKS=12"], "local-actual12.log")
    run([binary, "+TASKS=1", "+CPU_PRESSURE"], "local-pressure.log")


if __name__ == "__main__":
    main()
