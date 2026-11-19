"""Prove one-bit pipeline behavior and replay all 64 operand bits in the core."""
import os
import subprocess

from parity_eco import NAME, REPORT, ROOT, rtl
from local_fifo import SHADOW as FIFO_SHADOW, SOC, SOURCE

WORK = ROOT / "build/optimization" / NAME / "local"
MODEL = """module parity_equivalence(input clk,reset,valid,data,output equivalent);
    reg [30:0] tags, seen, reference;
    reg phase;
    wire [15:0] match, phase_match;
    wire [14:0] source_match;
    always @(posedge clk) begin
        if (reset) begin
            tags<=0;
            seen<=0;
            phase<=0;
        end else begin
            tags<={tags[29:0],valid};
            phase<=!phase;
            seen<=seen|{tags[29:0],valid};
            if (valid) reference[0]<=data;
            for(integer stage=1;stage<31;stage++)
                if(tags[stage-1]) reference[stage]<=reference[stage-1];
        end
    end
    wire [15:0] bank0,bank1;
    for(genvar tap=0;tap<16;tap++) begin: slice
        reg a,b,last;
        wire advance=tap==0?valid:tags[2*tap-1];
        wire in0,in1;
        if(tap==0) begin
            assign in0=data;
            assign in1=data;
        end else begin
            assign in0=bank0[tap-1];
            assign in1=bank1[tap-1];
            assign source_match[tap-1]=!tags[2*tap-1]||
                ((phase?in1:in0)==reference[2*tap-1]);
        end
        always @(posedge clk) if(!reset&&advance) begin
            if(phase) b<=in1;
            else a<=in0;
            last<=phase;
        end
        assign bank0[tap]=a;
        assign bank1[tap]=b;
        assign match[tap]=!seen[2*tap]||((last?b:a)==reference[2*tap]);
        assign phase_match[tap]=!tags[2*tap]||(seen[2*tap]&&last==!phase);
    end
    assign equivalent=reset||((&match)&&(&phase_match)&&(&source_match));
endmodule
"""

SHADOW = """    reg [63:0] expected_operand[1:31];
    reg [30:0] operand_initialized=0;
    integer operand_checks=0, operand_bubbles=0;
    always @(posedge clk) begin
        if(!rst_n) operand_initialized=0;
        else for(integer stage=31;stage>0;stage--) begin
            if(core.tags[stage-1].valid) begin
                if(stage==1) expected_operand[stage]=core.tags[0].side?
                    {core.input_q[7],core.input_q[6],core.input_q[5],core.input_q[4]}:
                    {core.tags[0].tail?16'b0:core.input_q[3],core.input_q[2],core.input_q[1],core.input_q[0]};
                else expected_operand[stage]=expected_operand[stage-1];
                operand_initialized[stage-1]=1;
            end
        end
    end
    always @(negedge clk) if(rst_n) begin
        for(integer tap=0;tap<16;tap++) begin
            if(operand_initialized[2*tap]) begin
                if(core.operands[2*tap+1]!==expected_operand[2*tap+1])
                    $fatal(1,"operand tap mismatch tap=%0d cycle=%0d",tap,cycle);
                operand_checks++;
                if(!core.tags[2*tap+1].valid) operand_bubbles++;
            end
        end
    end
    final $display("OPERAND_TAP_REPLAY checked=%0d bubbles=%0d",operand_checks,operand_bubbles);
"""


def run(args, log):
    with (REPORT / log).open("w") as stream:
        subprocess.run([str(arg) for arg in args], cwd=str(ROOT), stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def formal():
    REPORT.mkdir(parents=True, exist_ok=True)
    proof = REPORT / "operand_equivalence.v"
    proof.write_text(MODEL)
    yosys = ROOT / "tools/oss-cad-suite/bin/yosys.exe"
    run([yosys, "-Q", "-T", "-p", "read_verilog -sv %s; prep -top parity_equivalence; "
         "flatten; opt; sat -verify -set reset 0 -set-at 1 reset 1 "
         "-seq 36 -prove equivalent 1; sat -verify -tempinduct -tempinduct-inductonly "
         "-maxsteps 2 -set reset 0 -prove equivalent 1" % proof.relative_to(ROOT).as_posix()],
        "operand-equivalence.log")


def replay():
    WORK.mkdir(parents=True, exist_ok=True)
    core = rtl()
    bench = WORK / "core_tb.sv"
    original = (SOC / "local/core/core_tb.sv").read_text()
    anchor = "    kwt_shared_icb_sm40 mem(.*);"
    assert original.count(anchor) == 1
    loop = "        for(case_no=1;case_no<=number_of_cases;case_no=case_no+1) begin"
    assert original.count(loop) == 1
    reset = """
            if(case_no==2&&$test$plusargs("OPERAND_RESET_RESTART")) begin
                @(negedge clk);rst_n=0;
                repeat(3) @(negedge clk);rst_n=1;
            end"""
    bench.write_text(original.replace(anchor, anchor + "\n" + FIFO_SHADOW + SHADOW)
                     .replace(loop, loop + reset))
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
    run([binary, "+TASKS=2", "+OPERAND_RESET_RESTART"], "local-reset-restart.log")


if __name__ == "__main__":
    formal()
    replay()
