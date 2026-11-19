"""Replay the frozen fixtures and CPU contention through the paired physical writes."""

import os
import subprocess

from build import FROZEN, NAME, REPORT, ROOT, SOC, SOURCE


WORK = SOC / "local/core"


def bench_text(text):
    start = text.index("    wire ld_cmd_read=1;")
    end = text.index("    kwt_threebank_core core", start)
    text = text[:start] + """    wire ld_cmd_read;
    wire [31:0] ld_cmd_wdata,ld_cmd_wdata_hi;
    wire [3:0] ld_cmd_wmask;
    wire [11:0] ld_input_committed;
    wire [13:0] ld_parameter_committed;
    wire write_valid=ld_cmd_valid&&!ld_cmd_read;
    reg write_response=0;
    wire mem_rsp_valid,mem_rsp_ready;
    reg ack_pressure=0;
    assign ld_rsp_valid=mem_rsp_valid&&!(write_response&&ack_pressure);
    assign mem_rsp_ready=ld_rsp_ready&&!(write_response&&ack_pressure);
""" + text[end:]
    text = text.replace("kwt_shared_icb_sm40 mem(.*);",
                        "kwt_shared_icb_sm40 mem(.ld_rsp_valid(mem_rsp_valid),.ld_rsp_ready(mem_rsp_ready),.*);")
    text = text.replace("wire write_valid=ld_cmd_valid&&!ld_cmd_read;", """wire write_valid=ld_cmd_valid&&!ld_cmd_read;
    integer ack_stalls=0;
    integer cpu_responses=0;""")
    text = text.replace("core.output_credit<=32||core.output_credit==33&&core.result_fire",
                        "core.output_credit<=32||core.result_fire")
    text = text.replace("wait(wb_valid);", "wait(write_valid);")
    text = text.replace("32'ha0000000+{13'b0,wb_addr,2'b00}", "ld_cmd_addr")
    start = text.index("    always @(posedge clk) begin\n        cycle<=")
    end = text.index("    task put_word", start)
    text = text[:start] + """    always @(negedge clk) if($test$plusargs("ACK_PRESSURE"))
        ack_pressure=(cycle%17)<3;
    always @(posedge clk) begin
        cycle<=cycle+1;
        if(cpu_rsp_valid&&cpu_rsp_ready) cpu_responses=cpu_responses+1;
        if(busy&&ld_cmd_valid&&ld_cmd_ready&&ld_cmd_read) reads=reads+1;
        if(busy&&ld2_cmd_valid&&ld2_cmd_ready) reads=reads+1;
        if(write_valid&&!ld_cmd_ready) output_stalls=output_stalls+1;
        if(mem_rsp_valid&&write_response&&!mem_rsp_ready) ack_stalls=ack_stalls+1;
        if(error) $fatal(1,"DMA response error");
        if(ld_cmd_valid&&ld_cmd_ready) write_response<=!ld_cmd_read;
        if(write_valid&&ld_cmd_ready) begin
            index=int'(ld_cmd_addr[18:2])-16384;
            if(!mem.pair_commit||mem.host_dual||ld2_cmd_ready||
                index<0||index>=12672||(index%2)!=0)
                $fatal(1,"invalid shared pair index=%0d",index);
            for(integer lane=0;lane<2;lane++) begin
                if(seen[index+lane]||(lane==0?ld_cmd_wdata:ld_cmd_wdata_hi)!==
                   {expected[2*(index+lane)+1],expected[2*(index+lane)]})
                    $fatal(1,"value case=%0d index=%0d lane=%0d",case_no,index,lane);
                seen[index+lane]=1;
            end
            writes=writes+2;last_commit=cycle-origin;
        end
        if(ld_rsp_valid&&ld_rsp_ready&&write_response) acks=acks+2;
    end
    for(genvar bank=4;bank<=7;bank++) begin: physical_pair
        wire low_hit=mem.joined_bank_word[16:12]==5'(bank);
        wire high_hit=(mem.joined_bank_word[16:12]^5'd1)==5'(bank);
        always @(posedge clk) if(mem.pair_commit) begin
            if(mem.memory.banks[bank].bank_write!==(low_hit||high_hit))
                $fatal(1,"physical pair enable bank=%0d",bank);
            if(low_hit||high_hit) begin
                if(mem.memory.banks[bank].bank_addr!==mem.joined_bank_word[11:0]||
                   mem.memory.banks[bank].bank_wmask!==4'hf||
                   mem.memory.banks[bank].bank_wdata!==(low_hit?ld_cmd_wdata:ld_cmd_wdata_hi))
                    $fatal(1,"physical pair payload bank=%0d",bank);
            end
        end
    end
    task cpu_access(input logic is_read,input [31:0] address,input [31:0] data,
                    input [3:0] mask,input [31:0] check);
        @(negedge clk);
        cpu_cmd_valid=1;cpu_cmd_read=is_read;cpu_cmd_addr=address;cpu_cmd_wdata=data;cpu_cmd_wmask=mask;
        @(posedge clk);
        while(!cpu_cmd_ready) @(posedge clk);
        @(negedge clk);cpu_cmd_valid=0;
        while(!cpu_rsp_valid) @(negedge clk);
        if(cpu_rsp_err||(is_read&&cpu_rsp_rdata!==check))
            $fatal(1,"CPU result window address=%h got=%h expected=%h",address,cpu_rsp_rdata,check);
    endtask
""" + text[end:]
    text = text.replace("        $finish;", """        if($test$plusargs("ACK_PRESSURE")&&ack_stalls==0)
            $fatal(1,"ACK backpressure did not exercise result writes");
        if($test$plusargs("CPU_PRESSURE")&&cpu_responses!=256)
            $fatal(1,"CPU contention response count %0d",cpu_responses);
        cpu_access(1,32'ha0010000,0,0,{expected[1],expected[0]});
        cpu_access(1,32'ha0010004,0,0,{expected[3],expected[2]});
        cpu_access(0,32'ha0010000,32'h55006600,4'b1010,0);
        cpu_access(1,32'ha0010000,0,0,{8'h55,expected[1][7:0],8'h66,expected[0][7:0]});
        cpu_access(1,32'ha0010004,0,0,{expected[3],expected[2]});
        $display("PAIR_CPU_READ_MASK_PASS ack_stalls=%0d",ack_stalls);
        $finish;""")
    return text.replace("/ffn_trb_4x32/", "/" + NAME + "/")


def run(command, name):
    with (REPORT / name).open("w") as log:
        subprocess.run([str(arg) for arg in command], cwd=str(ROOT), stdout=log,
                       stderr=subprocess.STDOUT, check=True)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    bench = WORK / "core_tb.sv"
    bench.write_text(bench_text((FROZEN / "local/core/core_tb.sv").read_text()), encoding="utf-8")
    cad = ROOT / "tools/oss-cad-suite"
    share = cad / "share/verilator"
    os.environ["VERILATOR_ROOT"] = share.as_posix()
    run([cad / "bin/verilator_bin.exe", "--cc", "--exe", "--main", "--timing", "-Wno-fatal",
         "--top-module", "threebank_core_tb", "--Mdir", WORK, SOURCE / "kwt_threebank_core.sv",
         SOURCE / "kwt_ffn_clock_gate.sv", SOURCE / "kwt_ffn_requantize.sv", SOC / "kwt_shared_dma_icb_sm40.sv",
         FROZEN / "local/ram.sv", bench], "core-verilator.log")
    run(["mingw32-make.exe", "-C", WORK, "-f", "Vthreebank_core_tb.mk",
         "VERILATOR_ROOT=" + share.as_posix(), "-j4"], "core-compile.log")
    binary = WORK / "Vthreebank_core_tb.exe"
    run([binary, "+TASKS=12"], "core-actual12.log")
    run([binary, "+TASKS=1", "+CPU_PRESSURE", "+ACK_PRESSURE"], "core-pressure.log")


if __name__ == "__main__":
    main()
