"""Derive two independent datapaths from the frozen shared-pair design."""
from pathlib import Path
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
PARENT = "ffn_trb_4x32_shared_pair"
VARIANTS = {"GQ": "ffn_trb_4x32_pair_gq", "QM": "ffn_trb_4x32_pair_qm"}
BUILD = ROOT / "build/optimization"
CORE = Path("encoder/kwt_threebank_core.sv")


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError("Frozen RTL anchor changed: " + old[:80])
    return text.replace(old, new, 1)


def gated_queues(text):
    text = replace_once(text, "    wire [1:0] returned=", """    for (genvar entry=0;entry<8;entry++) begin: ingress_entries
        wire write0=rst_n&&busy&&return_fire&&ingress_tail==3'(entry);
        wire write1=rst_n&&busy&&return_fire2&&3'(ingress_tail+3'd1)==3'(entry);
        wire entry_clk;
        wire [31:0] entry_data=({32{write0}} & ld_rsp_rdata) |
                               ({32{write1}} & ld2_rsp_rdata);
        kwt_ffn_clock_gate gate(.clk(clk),.enable(write0||write1),
            .test_enable(1'b0),.gated_clk(entry_clk));
        always @(posedge entry_clk) ingress[entry]<=entry_data;
    end
    wire [1:0] returned=""")
    text = replace_once(text, """            if(return_fire) ingress[ingress_tail]<=ld_rsp_rdata;
            if(return_fire2) ingress[3'(ingress_tail+3'd1)]<=ld2_rsp_rdata;
""", "")
    return replace_once(text, "    always @(posedge clk) if(emit_valid) begin",
        """    wire quant_clk;
    kwt_ffn_clock_gate quant_gate(.clk(clk),.enable(emit_valid),
        .test_enable(1'b0),.gated_clk(quant_clk));
    always @(posedge quant_clk) begin""")


def quant_mux(text):
    start = text.index("    reg emit_valid,emit_page,emit_tail;")
    stop = text.index("    for(genvar lane=0;lane<8;lane=lane+1) begin: requantizers", start)
    return text[:start] + """    localparam integer EMIT_BITS=313;
    wire [EMIT_BITS-1:0] emit_item [0:15];
    wire [EMIT_BITS-1:0] emit_group [0:3];
    wire [EMIT_BITS-1:0] emit_bundle=emit_group[0]|emit_group[1]|emit_group[2]|emit_group[3];
    wire emit_valid=|column_emit[15:0];
    wire emit_page,emit_tail;
    wire [2:0] emit_slot;
    wire [3:0] emit_col;
    wire signed [7:0] quant_shift [0:1];
    wire signed [35:0] quant_source [0:7];
    wire [15:0] rounded [0:7];
    for(genvar col=0;col<16;col=col+1) begin: emit_columns
        wire [287:0] values;
        for(genvar row=0;row<4;row=row+1) begin: emit_rows
            assign values[36*row+:36]=emit_acc[col][row];
            assign values[36*(row+4)+:36]=emit_acc[col+16][row];
        end
        assign emit_item[col]={EMIT_BITS{column_emit[col]}} &
            {tags[2+2*col].page,tags[2+2*col].tail,tags[2+2*col].slot,4'(col),
             emit_shift[col+16],emit_shift[col],values};
    end
    for(genvar group=0;group<4;group=group+1) begin: emit_groups
        assign emit_group[group]=emit_item[4*group]|emit_item[4*group+1]|
                                 emit_item[4*group+2]|emit_item[4*group+3];
    end
    assign {emit_page,emit_tail,emit_slot,emit_col,quant_shift[1],quant_shift[0]}=emit_bundle[312:288];
    for(genvar lane=0;lane<8;lane=lane+1) begin: emit_values
        assign quant_source[lane]=emit_bundle[36*lane+:36];
    end
""" + text[stop:]


def materialize(key):
    variant = VARIANTS[key]
    source = BUILD / "rtl_sources" / PARENT
    target = BUILD / "rtl_sources" / variant
    (target / "encoder").mkdir(parents=True, exist_ok=True)
    for path in (source / "encoder").iterdir():
        if path.is_file():
            shutil.copyfile(path, target / "encoder" / path.name)
    text = (source / CORE).read_text(encoding="utf-8")
    (target / CORE).write_text({"GQ": gated_queues, "QM": quant_mux}[key](text), encoding="utf-8")
    parent_soc = BUILD / "complete_soc" / PARENT
    soc = BUILD / "complete_soc" / variant
    for folder in (parent_soc, parent_soc / "eda", parent_soc / "packed_inputs"):
        for path in folder.iterdir():
            if not path.is_file() or path.suffix not in (".sv", ".v", ".svh", ".f", ".json", ".rcf", ".hex", ".tcl"):
                continue
            dest = soc / path.relative_to(parent_soc)
            dest.parent.mkdir(parents=True, exist_ok=True)
            frozen = path.read_bytes()
            if PARENT.encode() not in frozen:
                dest.write_bytes(frozen)
            else:
                dest.write_bytes(frozen.replace(PARENT.encode(), variant.encode()))
    configuration = soc / "configuration.json"
    config = json.loads(configuration.read_text())
    config.update(parent_variant=PARENT, experiment=key)
    configuration.write_text(json.dumps(config, indent=2) + "\n")
    print("MATERIALIZED", key, variant, flush=True)


if __name__ == "__main__":
    import sys
    for name in sys.argv[1:] or VARIANTS:
        materialize(name)

