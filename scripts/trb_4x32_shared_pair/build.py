"""Materialize the isolated shared-arbitration candidate from the frozen 4x32 SoC."""

import json
from pathlib import Path
import re
import shutil


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
NAME = "ffn_trb_4x32_shared_pair"
PARENT = "ffn_trb_4x32"
REPORT = ROOT / "reports/optimization" / NAME
BUILD = ROOT / "build/optimization"
SOC = BUILD / "complete_soc" / NAME
SOURCE = BUILD / "rtl_sources" / NAME / "encoder"
FROZEN = BUILD / "complete_soc" / PARENT
CHANNEL = (("[31:0] ", "ld_cmd_wdata_hi"), ("[11:0] ", "ld_input_committed"),
           ("[13:0] ", "ld_parameter_committed"))


def edit_wrappers(text):
    def ports(match):
        start = match[1]
        direction = match[2]
        end = match[3]
        inverse = "input" if direction == "output" else "output"
        return (start + "%s wire %s%s,\n" % (direction, *CHANNEL[0]) + start +
                "%s wire %s%s,\n" % (inverse, *CHANNEL[1]) + start +
                "%s wire %s%s" % (inverse, *CHANNEL[2]) + end)

    text = re.sub(r"(?m)^([ \t]*)(input|output) wire wb_valid,\n(?:[ \t]*(?:input|output) wire .*\n){4}"
                  r"[ \t]*(?:input|output) wire wb_ack_ready(,?)$", ports, text)
    text = re.sub(r"(?m)^wire wb_valid;\n(?:wire .*;\n){5}",
                  "".join("wire %s%s;\n" % signal for signal in CHANNEL), text)
    text = re.sub(r"(?m)^([ \t]*)\.wb_valid\(wb_valid\),\n(?:[ \t]*\.wb_.*\n){4}"
                  r"[ \t]*\.wb_ack_ready\(wb_ack_ready\)(,?)$",
                  lambda m: ",\n".join(m[1]+".%s(%s)" % (signal, signal) for _, signal in CHANNEL)+m[2], text)
    text = re.sub(r"(?m)^    assign ld_cmd_(?:read|wdata|wmask)=.*;\n", "", text)
    assert "wb_" not in text
    return text


def complete_bench(text):
    start = text.index("    wire source_fire=")
    end = text.index("    always @(posedge clk) if(rst_n)", start)
    text = text[:start] + """    wire dma_fire=dut.ld_cmd_valid&&dut.ld_cmd_ready;
    wire source_fire=dma_fire&&dut.ld_cmd_read;
    wire result_fire=dma_fire&&!dut.ld_cmd_read;
    reg write_response=0;
    always @(posedge clk) if(rst_n&&dma_fire) write_response<=!dut.ld_cmd_read;
    wire result_ack=dut.ld_rsp_valid&&dut.ld_rsp_ready&&write_response&&!dut.ld_rsp_err;
""" + text[end:]
    start = text.index("            result_index=int'(dut.wb_addr)")
    end = text.index("        if((activity_window||ld_dma_writes==12672)&&result_ack)", start)
    return (text[:start] + """            result_index=int'(dut.ld_cmd_addr[18:2])-16384;
            if(result_index<0||result_index>=12672||(result_index%2)!=0)
                $fatal(1,"PAIR_ADDRESS %h",dut.ld_cmd_addr);
            for(integer lane=0;lane<2;lane++) begin
                if(output_seen[result_index+lane]) $fatal(1,"RESULT_DUPLICATE %d",result_index+lane);
                if((lane==0?dut.ld_cmd_wdata:dut.ld_cmd_wdata_hi)!==
                    {expected[2*(result_index+lane)+1],expected[2*(result_index+lane)]})
                    $fatal(1,"PAIR_RESULT_DATA index=%0d lane=%0d",result_index,lane);
                output_seen[result_index+lane]=1;
            end
            ld_dma_writes=ld_dma_writes+2;
            last_write=cycles;
`ifndef KWT_UNIFIED_GATE
            if(!dut.shared_memory.pair_commit||dut.ld2_cmd_ready||dut.shared_memory.host_dual)
                $fatal(1,"PAIR_PHYSICAL_GRANT");
`endif
        end
""" + text[end:]).replace("result_acks=result_acks+1;", "result_acks=result_acks+2;")


def materialize():
    SOURCE.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HERE / "core.sv", SOURCE / "kwt_threebank_core.sv")
    for name in ("kwt_ffn_requantize.sv", "kwt_ffn_clock_gate.sv"):
        shutil.copyfile(BUILD / "rtl_sources" / PARENT / "encoder" / name, SOURCE / name)
    paths = list(FROZEN.iterdir()) + list((FROZEN / "eda").glob("*.tcl"))
    paths += list((FROZEN / "packed_inputs").glob("*.hex"))
    for path in paths:
        if not path.is_file() or path.suffix not in (".sv", ".v", ".svh", ".f", ".json", ".rcf", ".hex", ".tcl"):
            continue
        if path.name in ("gate_tb.sv", "gate_files.f", "profile_tb.sv", "sram_probes.svh"):
            continue
        data = path.read_text().replace(PARENT, NAME)
        if path.name == "kwt_shared_dma_icb_sm40.sv":
            data = (HERE / "shared.sv").read_text()
        elif path.name == "complete_soc_tb.sv":
            data = complete_bench(data)
        elif path.name in ("kwt_complete_soc.sv", "kwt_loading_dma_accelerator.sv", "kwt_loading_dma_endpoint.svh", "e203_subsys_main.v",
                           "e203_subsys_perips.v", "e203_subsys_top.v"):
            data = edit_wrappers(data)
        elif path.name == "configuration.json":
            config = json.loads(data)
            config.update(parent_variant="ffn_trb_4x32_fifo_entry_gate", paired_result_dma=True)
            data = json.dumps(config, indent=2) + "\n"
        target = SOC / path.relative_to(FROZEN)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")


if __name__ == "__main__":
    materialize()
