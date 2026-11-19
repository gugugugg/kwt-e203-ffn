"""Derive the 32-bit single-access candidate from the frozen shared-pair SoC."""

import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/optimization"
NAME = "ffn_trb_4x32_serial32"
PARENT = "ffn_trb_4x32_shared_pair"
REPORT = ROOT / "reports/optimization" / NAME
SOC = BUILD / "complete_soc" / NAME
FROZEN = BUILD / "complete_soc" / PARENT
SOURCE = BUILD / "rtl_sources" / NAME / "encoder"
HERE = Path(__file__).resolve().parent
REMOVED = r"\b(?:host2_\w+|ld2_\w+|ld_cmd_wdata_hi)\b"


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Expected one frozen source match: " + old)
    return text.replace(old, new)


def core(text):
    text = replace(text, "output wire [31:0] ld_cmd_wdata, ld_cmd_wdata_hi,",
                   "output wire [31:0] ld_cmd_wdata,")
    for line in (
        "wire source_input_pair=", "wire source_pair=", "wire source_fire2=",
        "wire return_fire2=", "assign ld2_cmd_valid=", "assign ld_cmd_wdata_hi=",
        "held_pair<=ld2_cmd_valid;", "if(return_fire2) ingress",
        "output wire ld2_cmd_valid,", "input wire ld2_rsp_valid,",
    ):
        text, count = re.subn(r"(?m)^ +"+re.escape(line)+r".*\n", "", text)
        assert count == 1, line
    changes = (
        ("wire [1:0] accepted={1'b0,source_fire}+{1'b0,source_fire2};", "wire accepted=source_fire;"),
        ("wire [1:0] returned={1'b0,return_fire}+{1'b0,return_fire2};", "wire returned=return_fire;"),
        ("6'd46:6'd62", "6'd47:6'd63"),
        ("wire result_ready=out_count>=2;", "wire result_ready=out_count!=0;"),
        ("reg drain, held_command, held_read, held_pair;", "reg drain, held_command, held_read;"),
        ("assign ld_cmd_wdata=ld_cmd_read?32'b0:out_word[out_head][31:0];",
         "assign ld_cmd_wdata=ld_cmd_read?32'b0:\n"
         "        (retire_index[0]?out_word[out_head][63:32]:out_word[out_head][31:0]);"),
        ("(output_credit<=32||result_fire)", "(output_credit<=32||(output_credit==33&&result_fire))"),
        ("held_read<=0;held_pair<=0;", "held_read<=0;"),
        ("ack_count==14'd12670", "ack_count==14'd12671"),
        ("                out_head<=out_head==16?5'd0:out_head+5'd1;",
         "                if(retire_index[0]) out_head<=out_head==16?5'd0:out_head+5'd1;"),
        ("retire_index+6'd2", "retire_index+6'd1"),
        ("-{4'b0,result_fire,1'b0}", "-6'(result_fire)"),
        ("ack_count<=ack_count+14'd2", "ack_count<=ack_count+14'd1"),
    )
    for old, new in changes:
        text = replace(text, old, new)
    return text


def wrapper(text):
    lines = [line for line in text.splitlines(keepends=True) if not re.search(REMOVED, line)]
    return "".join(lines)


def host_bench(text):
    text = re.sub(r"(?m)^.*(?:\bhost2_\w+|\bld2_\w+).*$\n",
                  lambda m: m[0].replace(";host2_valid=0", "").replace("+int'(host2_valid&&host2_ready)", "")
                  if ("host_cmd_valid=0" in m[0] or "i=i+1" in m[0]) else "", text)
    return text


def complete_bench(text):
    text = host_bench(text)
    start = text.index("            result_index=int'(dut.ld_cmd_addr")
    end = text.index("        if((activity_window||ld_dma_writes==12672)&&result_ack)", start)
    text = text[:start] + """            result_index=int'(dut.ld_cmd_addr[18:2])-16384;
            if(result_index<0||result_index>=12672)
                $fatal(1,"SERIAL32_ADDRESS %h",dut.ld_cmd_addr);
            if(output_seen[result_index]||
                dut.ld_cmd_wdata!=={expected[2*result_index+1],expected[2*result_index]})
                $fatal(1,"SERIAL32_RESULT_DATA index=%0d",result_index);
            output_seen[result_index]=1;
            ld_dma_writes=ld_dma_writes+1;
            last_write=cycles;
`ifndef KWT_UNIFIED_GATE
            if(!dut.shared_memory.physical_accept||!dut.shared_memory.live_we||
                dut.shared_memory.host_fire||dut.shared_memory.live_addr!==dut.ld_cmd_addr[18:2]||
                dut.shared_memory.live_wdata!==dut.ld_cmd_wdata)
                $fatal(1,"SERIAL32_PHYSICAL_GRANT");
`endif
        end
""" + text[end:]
    return replace(text, "result_acks=result_acks+2;", "result_acks=result_acks+1;")


def main():
    REPORT.mkdir(parents=True, exist_ok=True)
    SOURCE.mkdir(parents=True, exist_ok=True)
    frozen_source = BUILD / "rtl_sources" / PARENT / "encoder"
    filename = "kwt_threebank_core.sv"
    (SOURCE / filename).write_text(core((frozen_source / filename).read_text()), encoding="utf-8")
    for name in ("kwt_ffn_requantize.sv", "kwt_ffn_clock_gate.sv"):
        shutil.copyfile(frozen_source / name, SOURCE / name)
    inputs = list(FROZEN.iterdir()) + list((FROZEN / "eda").glob("*.tcl"))
    inputs += list((FROZEN / "packed_inputs").glob("*.hex"))
    for path in inputs:
        if not path.is_file() or path.suffix not in (".sv", ".v", ".svh", ".f", ".json", ".hex", ".tcl", ".rcf"):
            continue
        if path.name in ("gate_tb.sv", "gate_files.f", "profile_tb.sv", "sram_probes.svh"):
            continue
        data = path.read_text().replace(PARENT, NAME)
        if path.name == "kwt_shared_dma_icb_sm40.sv":
            begin = data.index("module kwt_tp_shared_read_arbiter")
            end = data.index("module kwt_bank_overlap_sram", begin)
            arbiter = re.sub(r"(?m)^.*\b[bs]_cmd_wdata_hi\b.*\n", "", data[begin:end])
            data = (HERE / "shared.sv").read_text() + "\n" + arbiter
        elif path.name == "complete_soc_tb.sv":
            data = complete_bench(data)
        elif path.suffix in (".sv", ".svh", ".v"):
            data = wrapper(data)
        elif path.name == "configuration.json":
            config = json.loads(data)
            config.pop("paired_result_dma")
            config.update(parent_variant=PARENT, shared_access_data_bits=32,
                          shared_accesses_per_cycle=1, output_fifo="17x64")
            data = json.dumps(config, indent=2) + "\n"
        if path.suffix in (".sv", ".svh", ".v"):
            assert not re.search(REMOVED, data), path
        target = SOC / path.relative_to(FROZEN)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")


if __name__ == "__main__":
    main()
