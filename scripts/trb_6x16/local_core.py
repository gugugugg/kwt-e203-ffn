"""Run the same shared-controller and core protocol bench as the three-bank parent."""
from pathlib import Path
import os
import sys

from build import ROOT, HERE, SOC, SOURCE, change
from local import LOCAL, run

parent = (HERE.parent/"trb_threebank/core_tb.sv").read_text()
bench = parent.replace("ffn_trb_threebank/packed_inputs", "ffn_trb_sixteen/packed_inputs")
bench = change(bench, "    wire [31:0] host_rsp_rdata;", """    wire [31:0] host_rsp_rdata;
    reg host2_valid=0;
    wire host2_ready;
    reg [16:0] host2_addr=0;
    reg [31:0] host2_data=0;
    wire ld2_cmd_valid,ld2_cmd_ready,ld2_rsp_valid;
    wire [31:0] ld2_rsp_rdata;""")
bench = change(bench, "        if(busy&&ld_cmd_valid&&ld_cmd_ready) reads=reads+1;", """        if(busy&&ld_cmd_valid&&ld_cmd_ready) reads=reads+1;
        if(busy&&ld2_cmd_valid&&ld2_cmd_ready) reads=reads+1;""")
bench = change(bench, "                    for(integer i=1;i<11680;i=i+1) put_word(addresses[i],words[i]);",
    """                    integer i;
                    i=1;
                    while(i<11680) begin
                        @(negedge clk);
                        host_cmd_valid=1;host_cmd_addr=addresses[i];host_cmd_wdata=words[i];
                        host2_valid=i<11679;
                        if(host2_valid) begin host2_addr=addresses[i+1];host2_data=words[i+1];end
                        @(posedge clk);
                        while(!host_cmd_ready) @(posedge clk);
                        i=i+1+int'(host2_valid&&host2_ready);
                    end""")
bench = change(bench, "                begin\n                    put_word(0,words[0]);put_word(131021,1);\n                    integer i;",
              "                begin\n                    integer i;\n                    put_word(0,words[0]);put_word(131021,1);")
bench = change(bench, "@(negedge clk);host_cmd_valid=0;", "@(negedge clk);host_cmd_valid=0;host2_valid=0;")
bench = change(bench, "    integer output_stalls=0;", """    integer output_stalls=0;
    integer slot_peak=0,scratch_conflicts=0,first_issue=-1;
    always @(posedge clk) if(busy) begin
        if(core.issue&&first_issue<0) first_issue=cycle-origin;
        if(core.slot_count>slot_peak) slot_peak=core.slot_count;
        if(core.slot_complete[core.slot_read]&&(core.output_credit<2||core.result_fire)&&
            (core.quant_mask[core.scratch_lo]||core.quant_mask[core.scratch_hi]))
            scratch_conflicts=scratch_conflicts+1;
    end""")
bench = change(bench, "            wait(done);", """            wait(done);
            $display("SIXTEEN_LOCAL case=%0d issue=%0d slots=%0d conflicts=%0d",
                     case_no,first_issue,slot_peak,scratch_conflicts);
            first_issue=-1;slot_peak=0;scratch_conflicts=0;""")
folder=LOCAL/"core"
folder.mkdir(parents=True,exist_ok=True)
test=folder/"core_tb.sv"
test.write_text(bench)
cad=ROOT/"tools/oss-cad-suite"
os.environ["VERILATOR_ROOT"]=(cad/"share/verilator").as_posix()
run([cad/"bin/verilator_bin.exe","--cc","--exe","--main","--timing","-Wno-fatal",
     "--top-module","threebank_core_tb","--Mdir",folder,
     *sorted(SOURCE.glob("*.sv")),SOC/"kwt_shared_dma_icb_sm40.sv",LOCAL/"ram.sv",test],
     "core-verilator.log")
run(["mingw32-make.exe","-C",folder,"-f","Vthreebank_core_tb.mk",
     "VERILATOR_ROOT="+(cad/"share/verilator").as_posix(),"-j4"],"core-compile.log")
binary=folder/"Vthreebank_core_tb.exe"
run([binary,"+TASKS=12"],"core-actual12.log")
run([binary,"+TASKS=1","+CPU_PRESSURE"],"core-pressure.log")
