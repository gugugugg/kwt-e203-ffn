"""Build the isolated three-bank candidate from the frozen T+R+B platform."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

from fixture import ROOT, pack

NAME = "ffn_trb_threebank"
PARENT = "ffn_sg_reuse"
REPORT = ROOT / "reports/optimization" / NAME
BUILD = ROOT / "build/optimization"
HERE = Path(__file__).parent
SOC = BUILD / "complete_soc" / NAME
SOURCE = BUILD / "rtl_sources" / NAME
FIRMWARE = BUILD / "firmware" / NAME
OUTPUT = ROOT / "constraints" / NAME / (NAME + ".json")

WRITE_PORTS = (
    ("wb_valid", "", "output"),
    ("wb_ready", "", "input"),
    ("wb_addr", "[16:0]", "output"),
    ("wb_data", "[31:0]", "output"),
    ("wb_ack_valid", "", "input"),
    ("wb_ack_ready", "", "output"),
)


def text(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def replace(src, old, new, count=1):
    assert src.count(old) == count, old
    return src.replace(old, new)


def declarations(reverse=False):
    ports = []
    for name, width, direction in WRITE_PORTS:
        if reverse:
            direction = "input" if direction == "output" else "output"
        ports.append("    " + " ".join(x for x in (direction, "wire", width, name) if x))
    return ",\n".join(ports)


def connections():
    return "".join("        .%s(%s),\n" % (name, name) for name, _, _ in WRITE_PORTS)


def transport(src):
    src = replace(src, "    output wire ld_rsp_err\n);",
                  "    output wire ld_rsp_err,\n" + declarations(reverse=True) + "\n);")
    begin = src.index("    wire staged_dma_ready;")
    end = src.index("    function automatic [16:0] bank_word", begin)
    src = src[:begin] + """    wire staged_dma_ready;
    reg [11:0] input_committed;
    reg [13:0] parameter_committed;
    reg stream_enabled;
    wire [16:0] ld_word=ld_cmd_addr[18:2];
    wire host_input=!host_cmd_read&&host_cmd_wmask==4'hf&&host_cmd_addr<17'd3168;
    wire host_input_next=host_input&&host_cmd_addr=={5'b0,input_committed};
    wire host_parameter_next=!host_cmd_read&&host_cmd_wmask==4'hf&&
        parameter_committed<14'd8512&&host_cmd_addr==17'd32768+17'(parameter_committed);
    wire ld_input=ld_word<17'd3168;
    wire ld_parameter=ld_word>=17'd32768&&ld_word<17'd41280;
    wire dma_load_eligible=(ld_input&&ld_word<{5'b0,input_committed})||
        (ld_parameter&&ld_word<17'd32768+17'(parameter_committed));

""" + src[end:]
    src = replace(src, "if(addr[16:13]==4'b0100)", "if(addr[16:13]==4'b0100 || addr[16:13]==4'b0000)")
    begin = src.index("    wire joined_load_read=")
    end = src.index("kwt_tp_shared_read_arbiter memory_arbiter(", begin)
    src = src[:begin] + """    wire joined_load_read=joined_cmd_dma&&joined_cmd_read&&joined_address_valid;
    wire joined_fire;
    wire host_stream=host_cmd_valid&&stream_enabled&&(host_input_next||host_parameter_next);
    wire host_dual_candidate=joined_fire&&joined_load_read&&host_stream;
    wire host_bank_conflict=host_dual_candidate&&host_bank_word[16:12]==joined_bank_word[16:12];
    wire host_dual=host_dual_candidate&&!host_bank_conflict;
    wire host_foreground=host_cmd_valid&&!host_stream;
    assign ld_cmd_ready=staged_dma_ready&&dma_load_eligible;
""" + src[end:]
    src = replace(src, "ld_cmd_valid&&dma_input_eligible&&dma_load_eligible",
                  "ld_cmd_valid&&dma_load_eligible")
    begin = src.index("    wire next_fast_access=")
    end = src.index("    wire early_response", begin)
    src = src[:begin] + "    wire next_fast_access=joined_load_read;\n" + src[end:]
    src = replace(src, "(!(host_background||host_stream)||!joined_cmd_valid)",
                  "(!host_stream||!joined_cmd_valid)")
    begin = src.index("    always @(posedge clk or negedge rst_n) begin\n        if(!rst_n) begin\n            input_committed")
    end = src.index("    wire host_primary=", begin)
    src = src[:begin] + """    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin input_committed<=0; parameter_committed<=0; stream_enabled<=0;end
        else if(host_fire&&!host_cmd_read) begin
            if(host_input&&host_cmd_addr==0) begin
                input_committed<=1;parameter_committed<=0;stream_enabled<=0;
            end else if(host_input_next) input_committed<=input_committed+12'd1;
            else if(host_parameter_next) parameter_committed<=parameter_committed+14'd1;
            else if(host_cmd_addr==17'd131021&&host_cmd_wdata==1) stream_enabled<=1;
        end
    end
""" + src[end:]
    src = replace(src, "    wire physical_write=(physical_accept&&live_we)||host_dual;",
                  """    wire physical_write=(physical_accept&&live_we)||host_dual;
    reg result_pending;
    wire wb_bank_valid=wb_addr>=17'h4000&&wb_addr<17'h7180;
    wire wb_primary_conflict=physical_accept&&live_addr[16:12]==wb_addr[16:12];
    wire wb_host_conflict=host_dual&&host_bank_word[16:12]==wb_addr[16:12];
    assign wb_ready=rst_n&&wb_bank_valid&&(!result_pending||wb_ack_ready)&&
        !wb_primary_conflict&&!wb_host_conflict;
    wire result_commit=wb_valid&&wb_ready;
    assign wb_ack_valid=result_pending;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) result_pending<=0;
        else if(result_commit) result_pending<=1;
        else if(wb_ack_ready) result_pending<=0;
    end""")
    src = replace(src, ".addr(physical_accept?live_addr:held_addr),.stream_write(host_dual),.stream_addr(host_bank_word),",
                  """.addr(physical_accept?live_addr:held_addr),.stream_write(host_dual),.stream_addr(host_bank_word),
        .result_write(result_commit),.result_addr(wb_addr),.result_data(wb_data),""")
    src = replace(src, "    input wire stream_write,\n    input wire [31:0] wdata,",
                  """    input wire stream_write,result_write,
    input wire [16:0] result_addr,
    input wire [31:0] result_data,
    input wire [31:0] wdata,""")
    src = replace(src, "if(bank==0||bank==8||bank==9||bank==10||bank==14)",
                  "if(bank==0||bank==1||bank==8||bank==9||bank==10)")
    src = replace(src, "        wire bank_write=we||stream_hit;",
                  """        wire result_hit;
        if(bank>=4&&bank<=7) begin: result_bank
            assign result_hit=result_write&&result_addr[16:12]==5'(bank);
        end else begin: no_result
            assign result_hit=0;
        end
        wire bank_write=we||stream_hit||result_hit;
        wire [31:0] bank_wdata=result_hit?result_data:wdata;
        wire [3:0] bank_wmask=result_hit?4'hf:wmask;""")
    src = replace(src, "wire [11:0] bank_addr=stream_hit?stream_addr[11:0]:addr[11:0];",
                  """wire [11:0] bank_addr=result_hit?result_addr[11:0]:
            stream_hit?stream_addr[11:0]:addr[11:0];""")
    src = replace(src, "||stream_hit)),", "||stream_hit||result_hit)),")
    src = replace(src, "wmask[half*2+1]", "bank_wmask[half*2+1]")
    src = replace(src, "wmask[half*2]", "bank_wmask[half*2]")
    return replace(src, ".D(wdata[half*16+:16])", ".D(bank_wdata[half*16+:16])")


def firmware(config):
    old = ROOT / config["firmware"]
    inputs = FIRMWARE / "input-files"
    shutil.copytree(old / "input-files", inputs, dirs_exist_ok=True)
    metadata = json.loads((old / "firmware.json").read_text())
    driver = inputs / "driver.c"
    body = driver.read_text()
    body = body[:body.index("static void wr_base(")]
    begin = body.index("static int ld_transfer(")
    body = body[:begin] + body[body.index("static int wait_state(", begin):]
    text(driver, body + """
int kwu_run_linear(const kwu_device *d,const uint32_t input[3168],
                   kwu_stage_layer stage,void *context,int16_t output[25344]) {
    (void)input;(void)output;
    int rc=begin(d,3); if(rc)return rc;
    wr(d,CTRL,1);fence_io();
    uint32_t s=rd(d,EVENT);
    if((s&128u)||!(s&16u)||rd(d,LAYER)!=0)return KWU_HW_ERROR;
    const uint32_t *parameters,*shifts;
    rc=stage(context,0,&parameters,&shifts);if(rc)return rc;
    wr(d,0x48u,1);fence_io();
    if(rd(d,0x50u)&4u)return KWU_HW_ERROR;
    return wait_state(d,64u);
}
""")
    argv = metadata["compile_and_link_argv"]
    elf, binary = FIRMWARE / "firmware.elf", FIRMWARE / "firmware.bin"
    argv[-1] = str(elf)
    compiler = Path(argv[0])
    for command, log in ((argv, "firmware-build.log"),
        ([str(compiler.with_name("riscv-none-elf-objcopy.exe")), "-O", "binary", str(elf), str(binary)], "objcopy.log"),
        ([str(compiler.with_name("riscv-none-elf-objdump.exe")), "-d", str(elf)], "disassembly.txt")):
        with (FIRMWARE / log).open("w") as stream:
            subprocess.run(command, cwd=inputs, stdout=stream, stderr=subprocess.STDOUT, check=True)
    raw = binary.read_bytes()
    image = raw + bytes(262144 - len(raw))
    text(FIRMWARE / "firmware_itcm.hex", "".join("%016x\n" % int.from_bytes(image[i:i+8], "little")
                                              for i in range(0, len(image), 8)))
    metadata.update(compile_and_link_argv=argv, firmware_bytes=len(raw), boot_words=(len(raw)+7)//8,
                    descriptor_count=1, startup_descriptor_order=["packet0", "input1024", "packet1", "input2144", "packets2to15"])
    text(FIRMWARE / "firmware.json", json.dumps(metadata, indent=2) + "\n")
    return metadata["boot_words"]


def fixtures():
    for case in range(12):
        addresses, words = pack(case)
        text(SOC / "packed_inputs" / ("task_%02d_payload.hex" % (case + 1)),
             "".join("%08x\n" % word for word in words))
        text(SOC / "packed_inputs" / ("task_%02d_addresses.hex" % (case + 1)),
             "".join("%05x\n" % addr for addr in addresses))


def materialize(reuse_firmware=False):
    screen = json.loads((REPORT / "screen.json").read_text())
    assert screen["passes_model"]
    config = json.loads((ROOT / "constraints/ffn_selected.json").read_text())
    assert config["variant"] == PARENT
    parent = BUILD / "complete_soc" / PARENT
    (SOURCE / "encoder").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HERE / "core.sv", SOURCE / "encoder" / "kwt_threebank_core.sv")
    shutil.copyfile(ROOT / config["source_snapshot"] / "encoder" / "kwt_ffn_requantize.sv",
                    SOURCE / "encoder" / "kwt_ffn_requantize.sv")
    boot_words = (json.loads((FIRMWARE / "firmware.json").read_text())["boot_words"]
                  if reuse_firmware else firmware(config))
    text(SOC / "boot_count.svh", "localparam integer BOOT_WORDS=%d;\n" % boot_words)
    words = [0x800002b7, 0x00028067] + [0x13] * 1022
    text(SOC / "bootrom.rcf", "".join(format(word, "032b") + "\n" for word in words))
    for path in list(parent.iterdir()) + list((parent / "eda").glob("*.tcl")):
        name = path.name
        if not path.is_file() or path.suffix not in (".sv",".v",".svh",".f",".json",".sh",".tcl"):
            continue
        if name in ("gate_tb.sv","gate_files.f","compile_gate.sh","sram_probes.svh",
                    "pr1_assessment.tcl","q8_leaf_power.tcl","boot_count.svh"):
            continue
        data = path.read_text().replace(PARENT, NAME)
        if name == "ROM1KX32.v":
            data = replace(data, "build/optimization/complete_soc/ffn_ara_SR/bootrom.rcf",
                           "build/optimization/complete_soc/" + NAME + "/bootrom.rcf", count=2)
        elif name == "kwt_shared_dma_icb_sm40.sv":
            data = transport(data)
        elif name == "kwt_loading_dma_accelerator.sv":
            data = replace(data, "    input wire ld_rsp_err\n);",
                           "    input wire ld_rsp_err,\n" + declarations() + "\n);")
            data = data[:data.index("    wire trace_valid;")] + (HERE / "endpoint.svh").read_text()
        elif name.startswith("e203_subsys_") and name.endswith(".v"):
            data = replace(data, "    input wire ld_rsp_err\n", "    input wire ld_rsp_err,\n" + declarations() + "\n")
            if name != "e203_subsys_perips.v":
                data = replace(data, "        .ld_rsp_err(ld_rsp_err),\n",
                               "        .ld_rsp_err(ld_rsp_err),\n" + connections())
        elif name == "kwt_loading_dma_endpoint.svh":
            data = replace(data, "        .ld_rsp_err(ld_rsp_err),\n",
                           "        .ld_rsp_err(ld_rsp_err),\n" + connections())
        elif name == "kwt_complete_soc.sv":
            wires = "".join("wire %s%s;\n" % ((width+" ") if width else "", signal)
                            for signal,width,_ in WRITE_PORTS)
            data = replace(data, "wire ld_rsp_err;\n", "wire ld_rsp_err;\n" + wires)
            data = replace(data, "        .ld_rsp_err(ld_rsp_err),\n",
                           "        .ld_rsp_err(ld_rsp_err),\n" + connections(), count=2)
        elif name == "complete_soc_tb.sv":
            from bench import make_bench
            data = make_bench(data)
        elif name in ("files.f", "synthesis_files.f"):
            data = "\n".join(line for line in data.splitlines()
                             if not line.endswith(("GENERIC_RVT_ARM.v", "GENERIC_LVT_ARM.v")) and
                             ("/rtl_sources/" + NAME + "/" not in line or "kwt_ffn_requantize.sv" in line))
            data += "\n" + (SOURCE / "encoder/kwt_threebank_core.sv").relative_to(ROOT).as_posix() + "\n"
        elif name == "configuration.json":
            data = json.dumps(dict(variant=NAME, parent_variant=PARENT,
                source_snapshot=SOURCE.relative_to(ROOT).as_posix(), firmware=FIRMWARE.relative_to(ROOT).as_posix(),
                core_path=config["core_path"], compute_mac_count=64, requantizers=4, candidate=True), indent=2) + "\n"
        text(SOC / path.relative_to(parent), data)
    fixtures()
    text(OUTPUT, json.dumps(dict(variant=NAME, parent_variant=PARENT, clock_hz=150000000,
        model_cycles=screen["cold_cycles_total"], macros={"RAMSP1024X16":8,"RAMSP128X16":16},
        source_snapshot=SOURCE.relative_to(ROOT).as_posix(), soc=SOC.relative_to(ROOT).as_posix(),
        firmware=FIRMWARE.relative_to(ROOT).as_posix()), indent=2) + "\n")


if __name__ == "__main__":
    materialize(reuse_firmware=sys.argv[1:] == ["--reuse-firmware"])

