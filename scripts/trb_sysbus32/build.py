"""Derive an INT16 T+R+B candidate with the platform System Bus in every SRAM path."""

import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PARENT = "ffn_sg_reuse"
NAME = "ffn_trb_sysbus32"
BUILD = ROOT / "build/optimization"
SOC = BUILD / "complete_soc" / NAME
FROZEN = BUILD / "complete_soc" / PARENT
REPORT = ROOT / "reports/optimization" / NAME
HOST = """    input wire host_cmd_valid,host_cmd_read,
    output wire host_cmd_ready,
    input wire [16:0] host_cmd_addr,
    input wire [31:0] host_cmd_wdata,
    input wire [3:0] host_cmd_wmask,
    output wire host_rsp_valid,
    input wire host_rsp_ready,
    output wire [31:0] host_rsp_rdata,
    output wire host_rsp_err"""
HOST_SIGNALS = ("cmd_valid", "cmd_read", "cmd_ready", "cmd_addr", "cmd_wdata",
                "cmd_wmask", "rsp_valid", "rsp_ready", "rsp_rdata", "rsp_err")
LD_PORTS = """    output wire ld_cmd_valid,
    input wire ld_cmd_ready,
    output wire [31:0] ld_cmd_addr,
    output wire ld_cmd_read,
    output wire [31:0] ld_cmd_wdata,
    output wire [3:0] ld_cmd_wmask,
    input wire ld_rsp_valid,
    output wire ld_rsp_ready,
    input wire [31:0] ld_rsp_rdata,
    input wire ld_rsp_err"""
BUS_SIGNALS = ("cmd_valid", "cmd_ready", "cmd_addr", "cmd_read", "cmd_wdata",
               "cmd_wmask", "rsp_valid", "rsp_ready", "rsp_rdata", "rsp_err")
WIDTH = {"cmd_addr": "[31:0] ", "cmd_wdata": "[31:0] ",
         "cmd_wmask": "[3:0] ", "rsp_rdata": "[31:0] "}


def replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError("Expected one match: " + before)
    return text.replace(before, after)


def bind(signals, port, net):
    return ",\n".join("    .%s%s(%s%s)" % (port, s, net, s) for s in signals)


def main_wrapper(text):
    text = replace(text, LD_PORTS + "\n);", HOST + "\n);")
    start = text.index("e203_subsys_mems u_e203_subsys_mems(")
    stop = text.index("    .sysmem_icb_cmd_valid", start)
    old = text[start:stop]
    dma_wires = "\n".join("wire %sld_%s;" % (WIDTH.get(s, ""), s) for s in BUS_SIGNALS)
    text = replace(text, "e203_subsys_perips u_e203_subsys_perips (",
                   dma_wires + "\n\ne203_subsys_perips u_e203_subsys_perips (")
    new_wires = "\n".join("wire %smerged_%s;" % (WIDTH.get(s, ""), s) for s in BUS_SIGNALS)
    masters = ",\n".join((
        "    .clk(hfclk),.rst_n(bus_rst_n)",
        bind(BUS_SIGNALS, "cpu_", "mem_icb_"), bind(BUS_SIGNALS, "ld_", "ld_"),
        bind(HOST_SIGNALS, "host_", "host_"), bind(BUS_SIGNALS, "mem_", "merged_"),
        bind(BUS_SIGNALS[:6], "sram_", "sysmem_icb_")))
    instance = "kwt_sysbus_masters shared_masters(\n" + masters + "\n);\n\n"
    decoder = "e203_subsys_mems u_e203_subsys_mems(\n" + bind(BUS_SIGNALS, "mem_icb_", "merged_") + ",\n"
    return replace(text, old, new_wires + "\n" + instance + decoder)


def wrapper(text, name):
    if name == "e203_subsys_main.v":
        return main_wrapper(text)
    if name == "e203_subsys_top.v":
        text = replace(text, LD_PORTS + "\n);", HOST + "\n);")
        text = re.sub(r"(?m)^ +\.ld_(?:cmd|rsp)_\w+\(ld_\w+\),\n", "", text)
        marker = "e203_subsys_main  u_e203_subsys_main("
        return replace(text, marker, marker + "\n" + bind(HOST_SIGNALS, "host_", "host_") + ",")
    text = replace(text, "    output wire [31:0] host_rsp_rdata\n);",
                   "    output wire [31:0] host_rsp_rdata,\n    output wire host_rsp_err\n);")
    text = re.sub(r"(?m)^wire (?:\[\d+:\d+\] )?ld_(?:cmd|rsp)_\w+;\n", "", text)
    text = re.sub(r"(?m)^ +\.ld_(?:cmd|rsp)_\w+\(ld_\w+\),\n", "", text)
    start = text.index("kwt_shared_icb_sm40 shared_memory(")
    end = text.index("endmodule", start)
    text = text[:start] + "kwt_shared_icb_sm40 shared_memory(\n    .clk(system_clk),.rst_n(system_reset_n),\n" + \
        bind(BUS_SIGNALS, "cpu_", "sysmem_icb_") + "\n);\n" + text[end:]
    marker = "    .sysmem_icb_cmd_valid(sysmem_icb_cmd_valid),"
    return replace(text, marker, bind(HOST_SIGNALS, "host_", "host_") + ",\n" + marker)


def bench(text):
    for field, new in (("cpu_cmd_valid", "mem_icb_cmd_valid"), ("cpu_cmd_ready", "mem_icb_cmd_ready"),
                       ("cpu_cmd_addr", "mem_icb_cmd_addr"), ("cpu_cmd_read", "mem_icb_cmd_read"),
                       ("cpu_cmd_wdata", "mem_icb_cmd_wdata"), ("cpu_cmd_wmask", "mem_icb_cmd_wmask")):
        text = replace(text, "dut.shared_memory."+field,
                       "dut.soc.u_e203_subsys_main."+new)
    text = replace(text, "    wire host_cmd_ready,host_rsp_valid;",
                   "    wire host_cmd_ready,host_rsp_valid,host_rsp_err;")
    text = re.sub(r"(?m)^.*\b(?:force|release) dut\.shared_memory\.(?:clk|rst_n).*$\n", "", text)
    text = replace(text, "        for(integer b=0;b<64;b=b+1) put_word(131008+b,b==3?32'(requested_tasks):0);\n"
                         "        host_idle();\n        repeat(4) @(negedge clk);\n", "")
    marker = "        @(negedge reference_clk);rst_n=1;\n        wait(system_reset_n===1'b1);"
    text = replace(text, marker, marker + """
        for(integer b=0;b<64;b=b+1) put_word(131008+b,b==3?32'(requested_tasks):0);
        host_idle();""")
    text = replace(text, "        if((dut.shared_memory.memory.en&&dut.shared_memory.memory.we)||dut.shared_memory.host_dual)",
                   "        if(dut.shared_memory.memory.en&&dut.shared_memory.memory.we)")
    start = text.index("    wire pd_handoff_opportunity=")
    end = text.index("    wire pd_wait_opportunity=", start)
    text = text[:start] + "    wire pd_handoff_opportunity=1'b0;\n" + text[end:]
    start = text.index("    integer ce_read_handoffs")
    end = text.index("`endif", start)
    text = text[:start] + "    integer ce_read_handoffs=0,ce_write_handoffs=0;\n" + text[end:]
    text = replace(text, "dut.shared_memory.joined_rsp_valid&&dut.shared_memory.joined_rsp_ready",
                   "dut.soc.u_e203_subsys_main.ld_rsp_valid&&dut.soc.u_e203_subsys_main.ld_rsp_ready")
    start = text.index("    integer staged_late_words")
    end = text.index("`endif", start)
    text = text[:start] + """    integer staged_late_words=0,staged_mac_words=0,staged_last_input=0,staged_group_blocked=0;
    integer bank_dual=0,bank_conflict=0,bank_wait=0;
    always @(posedge system_clk) if(system_reset_n&&host_rsp_valid&&host_rsp_ready&&host_rsp_err)
        $fatal(1,"SYSTEM_BUS_LOADER_ERROR");
    reg [31:0] dma_read_address;
    wire dma_accept=dut.soc.u_e203_subsys_main.ld_cmd_valid&&dut.soc.u_e203_subsys_main.ld_cmd_ready;
    wire dma_ack=dut.soc.u_e203_subsys_main.ld_rsp_valid&&dut.soc.u_e203_subsys_main.ld_rsp_ready;
    reg dma_read_pending=0;
    always @(posedge system_clk) if(system_reset_n) begin
        if(activity_window&&dma_ack&&dma_read_pending) begin
            if(dut.soc.u_e203_subsys_main.ld_rsp_rdata!==host_buffer[dma_read_address[18:2]])
                $fatal(1,"SYSTEM_BUS_DMA_READ addr=%h got=%h expected=%h",dma_read_address,
                    dut.soc.u_e203_subsys_main.ld_rsp_rdata,host_buffer[dma_read_address[18:2]]);
        end
        if(dma_accept) begin
            dma_read_address<=dut.soc.u_e203_subsys_main.ld_cmd_addr;
            dma_read_pending<=dut.soc.u_e203_subsys_main.ld_cmd_read;
        end else if(dma_ack) dma_read_pending<=0;
    end
""" + text[end:]
    text = re.sub(r"(?m)^.*(?:\$set_gate_level_monitoring|\$toggle_start|\$toggle_stop|\$toggle_report).*$",
                  lambda match: "`ifndef VERILATOR\n" + match[0] + "\n`endif", text)
    return text


def main():
    REPORT.mkdir(parents=True, exist_ok=True)
    if not (FROZEN / "complete_soc_tb.sv").is_file():
        raise FileNotFoundError(str(FROZEN / "complete_soc_tb.sv"))
    source = BUILD / "rtl_sources" / PARENT
    for original in source.rglob("*"):
        if original.is_file():
            target = BUILD / "rtl_sources" / NAME / original.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
    paths = list(FROZEN.iterdir()) + list((FROZEN / "eda").glob("*.tcl"))
    paths += list((FROZEN / "packed_inputs").glob("*.hex"))
    for path in paths:
        if (not path.is_file() or path.suffix not in (".sv", ".svh", ".v", ".f", ".json", ".tcl", ".rcf", ".hex")
                or path.name in ("gate_tb.sv", "gate_files.f", "profile_tb.sv", "profile_files.f")):
            continue
        text = path.read_text(encoding="utf-8").replace(PARENT, NAME)
        text = text.replace("build/optimization/firmware/" + NAME, "build/optimization/firmware/" + PARENT)
        if path.name in ("kwt_complete_soc.sv", "e203_subsys_main.v", "e203_subsys_top.v"):
            text = wrapper(text, path.name)
        elif path.name == "kwt_shared_dma_icb_sm40.sv":
            text = (HERE / "shared.sv").read_text(encoding="utf-8")
        elif path.name == "complete_soc_tb.sv":
            text = bench(text)
        elif path.name == "ROM1KX32.v":
            text, count = re.subn(r'"build/optimization/complete_soc/[^"/]+/bootrom.rcf"',
                                  '"build/optimization/complete_soc/' + NAME + '/bootrom.rcf"', text)
            assert count == 2
        elif path.name == "platform_instance.svh":
            text = replace(text, "    .host_rsp_rdata(host_rsp_rdata)\n", 
                           "    .host_rsp_rdata(host_rsp_rdata),\n    .host_rsp_err(host_rsp_err)\n")
        elif path.name in ("files.f", "synthesis_files.f"):
            text += "\nbuild/optimization/complete_soc/" + NAME + "/kwt_sysbus_masters.sv\n"
        elif path.name == "area.tcl":
            text = replace(text, '[string match shared_memory/* $name]',
                           '[string match shared_memory/* $name] || [string match soc/u_e203_subsys_main/shared_masters/* $name]')
        elif path.name == "configuration.json":
            config = json.loads(text)
            config.update(parent_variant=PARENT, shared_bank_overlap=False, shared_access_data_bits=32,
                          dma_via_platform_decoder=True, host_via_platform_decoder=True)
            text = json.dumps(config, indent=2) + "\n"
        target = SOC / path.relative_to(FROZEN)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    shutil.copyfile(HERE / "masters.sv", SOC / "kwt_sysbus_masters.sv")
    # The platform boot ROM transfers control to the frozen firmware at 0x80000000.
    instructions = [0x800002b7, 0x00028067] + [0x13] * 1022
    (SOC / "bootrom.rcf").write_text("".join(format(word, "032b") + "\n" for word in instructions),
                                    encoding="ascii")


if __name__ == "__main__":
    main()
