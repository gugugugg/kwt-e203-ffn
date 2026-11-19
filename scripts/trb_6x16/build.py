"""Derive the 96-MAC transport from the accepted three-bank platform."""
from pathlib import Path
import json
import shutil

from fixture import ROOT, pack

NAME = "ffn_trb_sixteen"
PARENT = "ffn_trb_threebank"
BUILD = ROOT / "build/optimization"
HERE = Path(__file__).parent
SOC = BUILD / "complete_soc" / NAME
SOURCE = BUILD / "rtl_sources" / NAME / "encoder"
REPORT = ROOT / "reports/optimization" / "ffn_trb_6x16"
DMA = (("ld2_cmd_valid", "", True), ("ld2_cmd_ready", "", False),
       ("ld2_rsp_valid", "", False), ("ld2_rsp_rdata", "[31:0]", False))
HOST = (("host2_valid", "", False), ("host2_ready", "", True),
        ("host2_addr", "[16:0]", False), ("host2_data", "[31:0]", False))


def ports(items, reverse=False):
    return "".join("    %s wire %s%s,\n" %
                   ("output" if output != reverse else "input", width + " " if width else "", name)
                   for name, width, output in items)


def connect(items):
    return "".join("        .%s(%s),\n" % (name, name) for name, _, _ in items)


def change(src, before, after, count=1):
    assert src.count(before) == count, before
    return src.replace(before, after)


def transport(src):
    src = change(src, "    output wire ld_rsp_err,\n", "    output wire ld_rsp_err,\n" + ports(DMA, True))
    src = change(src, "    input wire [3:0] host_cmd_wmask,\n", "    input wire [3:0] host_cmd_wmask,\n" + ports(HOST))
    src = change(src, "addr[16:13]==4'b0100 || addr[16:13]==4'b0000",
                 "addr[16:14]==3'd2 || addr[16:14]==3'd0")
    src = change(src, "{addr[16:13],addr[0],addr[11:1],addr[12]}",
                 "{addr[16:14],addr[1:0],addr[11:2],addr[13:12]}")
    transaction = "    reg pending,read_pending,error_pending,to_host,pending_fast_access;\n"
    src = change(src, transaction, "")
    src = change(src, "    wire staged_dma_ready;\n", transaction + "    wire staged_dma_ready;\n")
    start = src.index("    wire host_dual_candidate=")
    end = src.index("    wire host_foreground=", start)
    src = src[:start] + """    wire [16:0] second_word=ld_word+17'd1;
    wire [16:0] second_read_addr=bank_word(second_word);
    wire second_committed=(ld_input&&second_word<{5'b0,input_committed})||
        (ld_parameter&&second_word<17'd32768+17'(parameter_committed));
    assign ld2_cmd_ready=joined_fire&&joined_load_read&&ld_rsp_ready&&second_committed&&
        second_read_addr[16:12]!=joined_bank_word[16:12];
    wire second_read=ld2_cmd_valid&&ld2_cmd_ready;
    wire [16:0] second_host_addr=bank_word(host2_addr);
    wire host_bank_conflict=(joined_fire&&joined_address_valid&&host_bank_word[16:12]==joined_bank_word[16:12])||
        (second_read&&host_bank_word[16:12]==second_read_addr[16:12]);
    wire host_dual=host_stream&&!host_rsp_valid&&!host_bank_conflict&&
        (!joined_fire||joined_load_read)&&(!pending||pending_fast_access)&&!stored_rsp_valid;
    wire host2_input=host2_addr<17'd3168&&
        host2_addr==17'(input_committed)+17'(host_input_next);
    wire host2_parameter=host2_addr>=17'd32768&&host2_addr<17'd41280&&
        host2_addr==17'd32768+17'(parameter_committed)+17'(host_parameter_next);
    assign host2_ready=host_dual&&(host2_input||host2_parameter)&&
        second_host_addr[16:12]!=host_bank_word[16:12]&&
        !(joined_fire&&joined_address_valid&&second_host_addr[16:12]==joined_bank_word[16:12])&&
        !(second_read&&second_host_addr[16:12]==second_read_addr[16:12]);
    wire host2_fire=host2_valid&&host2_ready;
""" + src[end:]
    src = change(src, "    assign host_cmd_ready=(idle&&(!host_stream||!joined_cmd_valid))||host_dual;",
                 "    assign host_cmd_ready=host_stream?host_dual:idle;")
    src = change(src, """            end else if(host_input_next) input_committed<=input_committed+12'd1;
            else if(host_parameter_next) parameter_committed<=parameter_committed+14'd1;
            else if(host_cmd_addr==17'd131021&&host_cmd_wdata==1) stream_enabled<=1;""",
                 """            end else begin
                if(host_input_next||(host2_fire&&host2_input))
                    input_committed<=input_committed+12'(host_input_next)+12'(host2_fire&&host2_input);
                if(host_parameter_next||(host2_fire&&host2_parameter))
                    parameter_committed<=parameter_committed+14'(host_parameter_next)+14'(host2_fire&&host2_parameter);
                if(host_cmd_addr==17'd131021&&host_cmd_wdata==1) stream_enabled<=1;
            end""")
    src = change(src, "    wire [31:0] memory_rdata;", """    wire [31:0] memory_rdata;
    reg second_pending;
    always @(posedge clk or negedge rst_n)
        if(!rst_n) second_pending<=0;
        else second_pending<=second_read;
    assign ld2_rsp_valid=second_pending;""")
    src = change(src, "        .result_write(result_commit),", """        .read2(second_read),.read2_addr(second_read_addr),.rdata2(ld2_rsp_rdata),
        .stream2_write(host2_fire),.stream2_addr(second_host_addr),.stream2_data(host2_data),
        .result_write(result_commit),""")
    src = change(src, "    input wire stream_write,result_write,",
                 """    input wire stream_write,result_write,read2,stream2_write,
    input wire [16:0] read2_addr,stream2_addr,
    input wire [31:0] stream2_data,
    output wire [31:0] rdata2,""")
    src = change(src, "    reg [4:0] read_bank;", """    reg [4:0] read_bank;
    reg [2:0] second_bank;
    always @(posedge clk) if(read2) second_bank<={read2_addr[15],read2_addr[13:12]};
    assign rdata2=second_bank[2]?bank_data[(8+second_bank[1:0])*32+:32]:
                                 bank_data[second_bank[1:0]*32+:32];""")
    src = change(src, "        wire stream_hit;", "        wire stream_hit,stream2_hit,read2_hit;")
    src = change(src, "if(bank==0||bank==1||bank==8||bank==9||bank==10)",
                 "if(bank<4||(bank>=8&&bank<12))")
    src = change(src, """        end else begin: primary_only
            assign stream_hit=1'b0;""", """            assign stream2_hit=stream2_write&&stream2_addr[16:12]==5'(bank);
            assign read2_hit=read2&&read2_addr[16:12]==5'(bank);
        end else begin: primary_only
            assign stream_hit=1'b0;
            assign stream2_hit=1'b0;
            assign read2_hit=1'b0;""")
    src = change(src, "        wire bank_write=we||stream_hit||result_hit;",
                 """        wire primary_hit=en&&addr[16:12]==5'(bank);
        wire bank_write=(primary_hit&&we)||stream_hit||stream2_hit||result_hit;""")
    src = change(src, "result_hit?result_data:wdata", "result_hit?result_data:stream2_hit?stream2_data:wdata")
    src = change(src, "result_hit?4'hf:wmask", "(result_hit||stream2_hit)?4'hf:wmask")
    src = change(src, "stream_hit?stream_addr[11:0]:addr[11:0]",
                 """stream_hit?stream_addr[11:0]:stream2_hit?stream2_addr[11:0]:
            read2_hit?read2_addr[11:0]:addr[11:0]""")
    return change(src, "((en&&addr[16:12]==5'(bank))||stream_hit||result_hit)",
                  "(primary_hit||stream_hit||stream2_hit||read2_hit||result_hit)")


def bench(src):
    src = change(src, '    `include "platform_instance.svh"',
                 """    reg host2_valid=0;
    wire host2_ready;
    reg [16:0] host2_addr=0;
    reg [31:0] host2_data=0;
    `include "platform_instance.svh" """.rstrip())
    src = change(src, "command_phase();host_cmd_valid=0;\n    endtask",
                 "command_phase();host_cmd_valid=0;host2_valid=0;\n    endtask")
    src = change(src, "        if(activity_window&&source_fire) ld_dma_reads=ld_dma_reads+1;",
                 """        if(activity_window&&source_fire) ld_dma_reads=ld_dma_reads+1;
        if(activity_window&&dut.ld2_cmd_valid&&dut.ld2_cmd_ready) ld_dma_reads=ld_dma_reads+1;
        if(activity_window&&host2_valid&&host2_ready) host_payload=host_payload+1;""")
    src = change(src, "            for(integer i=1;i<11680;i=i+1) put_word(int'(payload_addr[i]),payload[i]);",
                 """            begin : stream_payload
                integer i;
                i=1;
                while(i<11680) begin
                    command_phase();
                    host_cmd_valid=1;host_cmd_read=0;host_cmd_addr=payload_addr[i];host_cmd_wdata=payload[i];
                    host2_valid=i<11679;
                    if(host2_valid) begin host2_addr=payload_addr[i+1];host2_data=payload[i+1];end
                    @(posedge clk);
                    while(!host_cmd_ready) @(posedge clk);
                    i=i+1+int'(host2_valid&&host2_ready);
                end
            end""")
    return src


def materialize():
    model=json.loads((REPORT/"model-result.json").read_text())
    assert model["selected"]==1
    assert json.loads((ROOT/"constraints/ffn_selected.json").read_text())["variant"]=="ffn_sg_reuse"
    parent=BUILD/"complete_soc"/PARENT
    SOURCE.mkdir(parents=True,exist_ok=True)
    SOC.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(HERE/"core.sv", SOURCE/"kwt_threebank_core.sv")
    shutil.copyfile(BUILD/"rtl_sources"/PARENT/"encoder/kwt_ffn_requantize.sv", SOURCE/"kwt_ffn_requantize.sv")
    shutil.copyfile(BUILD/"rtl_sources/ffn_sg_reuse/encoder/kwt_ffn_clock_gate.sv", SOURCE/"kwt_ffn_clock_gate.sv")
    for path in list(parent.iterdir())+list((parent/"eda").glob("*.tcl")):
        name=path.name
        if not path.is_file() or path.suffix not in (".sv",".v",".svh",".f",".json",".rcf",".sh",".tcl"):
            continue
        if name in ("gate_tb.sv","gate_files.f","compile_gate.sh","profile_tb.sv","sram_probes.svh"):
            continue
        src=path.read_text().replace(PARENT,NAME)
        if name=="kwt_shared_dma_icb_sm40.sv":
            src=transport(src)
        elif name in ("e203_subsys_top.v","e203_subsys_main.v","e203_subsys_perips.v","kwt_loading_dma_accelerator.sv"):
            src=change(src,"    input wire ld_rsp_err,\n","    input wire ld_rsp_err,\n"+ports(DMA))
            if name in ("e203_subsys_top.v","e203_subsys_main.v"):
                src=change(src,"        .ld_rsp_err(ld_rsp_err),\n","        .ld_rsp_err(ld_rsp_err),\n"+connect(DMA))
        elif name=="kwt_loading_dma_endpoint.svh":
            src=change(src,"        .ld_rsp_err(ld_rsp_err),\n","        .ld_rsp_err(ld_rsp_err),\n"+connect(DMA))
        elif name=="kwt_complete_soc.sv":
            wires="".join("wire %s%s;\n"%(width+" " if width else "", signal) for signal,width,_ in DMA)
            src=change(src,"wire ld_rsp_err;\n","wire ld_rsp_err;\n"+wires)
            src=change(src,"        .ld_rsp_err(ld_rsp_err),\n","        .ld_rsp_err(ld_rsp_err),\n"+connect(DMA),2)
            src=change(src,"    input wire [3:0] host_cmd_wmask,\n","    input wire [3:0] host_cmd_wmask,\n"+ports(HOST))
            src=change(src,"kwt_shared_icb_sm40 shared_memory(\n","kwt_shared_icb_sm40 shared_memory(\n"+connect(HOST))
        elif name=="platform_instance.svh":
            src=change(src,"    .host_cmd_wmask(host_cmd_wmask),\n","    .host_cmd_wmask(host_cmd_wmask),\n"+connect(HOST))
        elif name=="complete_soc_tb.sv":
            src=bench(src).replace("build/optimization/firmware/"+NAME,"build/optimization/firmware/"+PARENT)
        elif name in ("files.f","synthesis_files.f"):
            src+="\n"+(SOURCE/"kwt_ffn_clock_gate.sv").relative_to(ROOT).as_posix()+"\n"
        elif name=="configuration.json":
            config=json.loads(src)
            config.update(parent_variant=PARENT,compute_mac_count=96,requantizers=6,
                          firmware="build/optimization/firmware/"+PARENT)
            src=json.dumps(config,indent=2)+"\n"
        destination=SOC/path.relative_to(parent)
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(src,encoding="utf-8")
    inputs=SOC/"packed_inputs"
    inputs.mkdir(exist_ok=True)
    for case in range(12):
        addresses,words=pack(case)
        (inputs/("task_%02d_payload.hex"%(case+1))).write_text("".join("%08x\n"%word for word in words))
        (inputs/("task_%02d_addresses.hex"%(case+1))).write_text("".join("%05x\n"%word for word in addresses))


if __name__=="__main__":
    materialize()


