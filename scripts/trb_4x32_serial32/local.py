"""Run the frozen payloads against the serial 32-bit core and actual arbiter."""

import sys

from build import NAME, REPORT, ROOT, SOC, SOURCE, host_bench, replace


def main():
    sys.path.insert(0, str(ROOT / "scripts/trb_4x32_shared_pair"))
    import local_core as prior

    frozen = ROOT / "build/optimization/complete_soc/ffn_trb_4x32"
    work = SOC / "local/core"
    work.mkdir(parents=True, exist_ok=True)
    text = prior.bench_text((frozen / "local/core/core_tb.sv").read_text())
    text = replace(text, "ld_cmd_wdata,ld_cmd_wdata_hi", "ld_cmd_wdata")
    begin = text.index("            if(!mem.pair_commit")
    end = text.index("    task cpu_access", begin)
    text = text[:begin] + """            if(!mem.physical_accept||!mem.live_we||mem.host_fire||
               mem.live_addr!==ld_cmd_addr[18:2]||mem.live_wdata!==ld_cmd_wdata||
               index<0||index>=12672)
                $fatal(1,"invalid shared single word index=%0d",index);
            if(seen[index]||ld_cmd_wdata!=={expected[2*index+1],expected[2*index]})
                $fatal(1,"value case=%0d index=%0d",case_no,index);
            seen[index]=1;
            writes=writes+1;
            if(cycle-origin==last_commit+1) consecutive_writes=consecutive_writes+1;
            last_commit=cycle-origin;
        end
        if(ld_rsp_valid&&ld_rsp_ready&&write_response) acks=acks+1;
    end
""" + text[end:]
    text = host_bench(text)
    text = replace(text, "integer ack_stalls=0;", "integer ack_stalls=0,consecutive_writes=0;")
    text = replace(text, "core.output_credit<=32||core.result_fire",
                   "core.output_credit<=32||core.output_credit==33&&core.result_fire")
    text = replace(text, "        $finish;", """        if(consecutive_writes==0) $fatal(1,"no consecutive 32-bit writes");
        $display("SERIAL32_CONSECUTIVE_WRITES %0d",consecutive_writes);
        $finish;""")
    bench = work / "core_tb.sv"
    bench.write_text(text.replace(prior.NAME, NAME), encoding="utf-8")
    prior.REPORT, prior.SOURCE, prior.SOC, prior.WORK = REPORT, SOURCE, SOC, work
    cad = ROOT / "tools/oss-cad-suite"
    share = cad / "share/verilator"
    prior.run([cad / "bin/verilator_bin.exe", "--cc", "--exe", "--main", "--timing", "-Wno-fatal",
               "--top-module", "threebank_core_tb", "--Mdir", work, SOURCE / "kwt_threebank_core.sv",
               SOURCE / "kwt_ffn_clock_gate.sv", SOURCE / "kwt_ffn_requantize.sv",
               SOC / "kwt_shared_dma_icb_sm40.sv", frozen / "local/ram.sv", bench], "core-verilator.log")
    prior.run(["mingw32-make.exe", "-C", work, "-f", "Vthreebank_core_tb.mk",
               "VERILATOR_ROOT=" + share.as_posix(), "-j4"], "core-compile.log")
    binary = work / "Vthreebank_core_tb.exe"
    prior.run([binary, "+TASKS=12"], "core-actual12.log")
    prior.run([binary, "+TASKS=1", "+CPU_PRESSURE", "+ACK_PRESSURE"], "core-pressure.log")


if __name__ == "__main__":
    main()
