"""Run the frozen physical-bank testbench with a cycle-by-cycle reference core."""
import os
from pathlib import Path
import re
import subprocess
import sys

from build import BUILD, CORE, PARENT, ROOT, VARIANTS, replace_once

OBSERVE = """
    wire ref_busy,ref_done,ref_error,ref_ld_cmd_valid,ref_ld_cmd_read;
    wire ref_ld_rsp_ready,ref_ld2_cmd_valid;
    wire [31:0] ref_ld_cmd_addr,ref_ld_cmd_wdata,ref_ld_cmd_wdata_hi;
    wire [3:0] ref_ld_cmd_wmask;
    kwt_threebank_reference reference_core(
        .busy(ref_busy),.done(ref_done),.error(ref_error),.ld_cmd_valid(ref_ld_cmd_valid),
        .ld_cmd_read(ref_ld_cmd_read),.ld_cmd_addr(ref_ld_cmd_addr),.ld_cmd_wdata(ref_ld_cmd_wdata),
        .ld_cmd_wdata_hi(ref_ld_cmd_wdata_hi),.ld_cmd_wmask(ref_ld_cmd_wmask),
        .ld_rsp_ready(ref_ld_rsp_ready),.ld2_cmd_valid(ref_ld2_cmd_valid),.*);
    integer dual_ingress=0,wrap_ingress=0,quant_edges=0,tail_quant=0,pair_commits=0;
    always @(posedge clk) if(rst_n) begin
        if({busy,done,error,ld_cmd_valid,ld_rsp_ready,ld2_cmd_valid}!==
           {ref_busy,ref_done,ref_error,ref_ld_cmd_valid,ref_ld_rsp_ready,ref_ld2_cmd_valid})
            $fatal(1,"control mismatch cycle=%0d",cycle);
        if(ld_cmd_valid && {ld_cmd_read,ld_cmd_addr,ld_cmd_wdata,ld_cmd_wdata_hi,ld_cmd_wmask}!==
           {ref_ld_cmd_read,ref_ld_cmd_addr,ref_ld_cmd_wdata,ref_ld_cmd_wdata_hi,ref_ld_cmd_wmask})
            $fatal(1,"DMA request mismatch cycle=%0d",cycle);
        if(core.issue!==reference_core.issue||core.emit_valid!==reference_core.emit_valid||
           core.quant_valid!==reference_core.quant_valid||core.load_count!==reference_core.load_count||
           core.scratch_read!==reference_core.scratch_read)
            $fatal(1,"schedule mismatch cycle=%0d",cycle);
        if(core.load_count!=0) for(integer lane=0;lane<4;lane++)
            if(lane<core.load_count&&core.front[lane]!==reference_core.front[lane])
                $fatal(1,"load data mismatch cycle=%0d lane=%0d",cycle,lane);
        if(!$onehot0(reference_core.column_emit[15:0]))
            $fatal(1,"quantizer emit overlap cycle=%0d",cycle);
        if({core.emit_page,core.emit_tail,core.emit_slot,core.emit_col} !==
           {reference_core.emit_page,reference_core.emit_tail,reference_core.emit_slot,reference_core.emit_col} ||
           core.quant_shift[0]!==reference_core.quant_shift[0]||core.quant_shift[1]!==reference_core.quant_shift[1])
            $fatal(1,"quantizer selection metadata mismatch cycle=%0d",cycle);
        for(integer lane=0;lane<8;lane++)
            if(core.quant_source[lane]!==reference_core.quant_source[lane])
                $fatal(1,"quantizer selection value mismatch cycle=%0d lane=%0d",cycle,lane);
        if(core.quant_valid) begin
            if({core.quant_data,core.quant_page,core.quant_tail,core.quant_slot,core.quant_col} !==
               {reference_core.quant_data,reference_core.quant_page,reference_core.quant_tail,
                reference_core.quant_slot,reference_core.quant_col})
                $fatal(1,"quantized data mismatch cycle=%0d",cycle);
            quant_edges++;
            if(core.quant_tail) tail_quant++;
        end
        if(core.return_fire&&core.return_fire2) begin
            dual_ingress++;
            if(core.ingress_tail==7) wrap_ingress++;
        end
        if(mem.pair_commit) pair_commits++;
    end
"""

def run(command, log):
    with log.open("w") as stream:
        subprocess.run([str(x) for x in command], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)


def main(key):
    variant = VARIANTS[key]
    soc = BUILD / "complete_soc" / variant
    frozen = BUILD / "complete_soc" / PARENT
    core = BUILD / "rtl_sources" / variant / CORE
    work = soc / "local/compare"
    work.mkdir(parents=True, exist_ok=True)
    report = ROOT / "reports/optimization/ffn_trb_pair_area_power/local" / key
    report.mkdir(parents=True, exist_ok=True)
    reference = work / "reference.sv"
    reference.write_text(replace_once((BUILD / "rtl_sources" / PARENT / CORE).read_text(),
                         "module kwt_threebank_core (", "module kwt_threebank_reference ("), encoding="utf-8")
    bench = work / "compare.sv"
    text = (frozen / "local/core/core_tb.sv").read_text().replace(PARENT, variant)
    text = replace_once(text, "    kwt_threebank_core core(.*);",
                         "    kwt_threebank_core core(.*);\n" + OBSERVE)
    text = replace_once(text, "        $finish;", """        if(dual_ingress==0||wrap_ingress==0||quant_edges!=number_of_cases*3200||
            tail_quant!=number_of_cases*128||pair_commits!=number_of_cases*6336)
            $fatal(1,"coverage dual=%0d wrap=%0d quant=%0d tail=%0d commits=%0d",
                   dual_ingress,wrap_ingress,quant_edges,tail_quant,pair_commits);
        $display("PAIR_CYCLE_EQ_PASS tasks=%0d dual=%0d wrap=%0d quant=%0d tail=%0d commits=%0d",
                 number_of_cases,dual_ingress,wrap_ingress,quant_edges,tail_quant,pair_commits);
        $finish;""")
    bench.write_text(text, encoding="utf-8")
    cad = ROOT / "tools/oss-cad-suite"
    share = cad / "share/verilator"
    os.environ["VERILATOR_ROOT"] = share.as_posix()
    run([cad / "bin/verilator_bin.exe", "--cc", "--exe", "--main", "--timing", "-Wno-fatal",
         "--top-module", "threebank_core_tb", "--Mdir", work, core, reference,
         core.with_name("kwt_ffn_clock_gate.sv"), core.with_name("kwt_ffn_requantize.sv"),
         soc / "kwt_shared_dma_icb_sm40.sv", BUILD / "complete_soc/ffn_trb_4x32/local/ram.sv", bench],
        report / "elaboration.log")
    run(["mingw32-make.exe", "-C", work, "-f", "Vthreebank_core_tb.mk",
         "VERILATOR_ROOT=" + share.as_posix(), "-j4"], report / "compile.log")
    binary = work / "Vthreebank_core_tb.exe"
    for scenario, args, count in (("actual12", ["+TASKS=12"], 12),
                                 ("pressure", ["+TASKS=1", "+CPU_PRESSURE", "+ACK_PRESSURE"], 1)):
        log = report / (scenario + ".log")
        run([binary] + args, log)
        result = log.read_text()
        rows = re.findall(r"THREEBANK_CORE_PASS .*reads=11680 writes=12672 acks=12672", result)
        if len(rows) != count or "PAIR_CYCLE_EQ_PASS tasks=%d " % count not in result:
            raise ValueError(log)
        print(key, scenario, count, "passed", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])

