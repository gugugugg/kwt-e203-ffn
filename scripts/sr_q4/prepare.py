"""Generate the sole Q4 candidate after the calibrated model has passed."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VARIANT = 'ffn_sr_q4'
REPORT = ROOT/'reports/optimization'/VARIANT
BUILD = ROOT/'build/optimization'/VARIANT
CORE = Path('encoder/kwt_encoder.sv')
QUEUE = Path('encoder/kwt_joint_output_queue.sv')


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')


def edit(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Expected one frozen source match: '+old)
    return text.replace(old, new, 1)


def core_rtl(text):
    text = edit(text, """    wire jp_quant_ready;
    wire jp_quant_commit=emission&&jp_quant_ready;
    wire fifo_push=jp_quant_commit&&!emit_row;""", """    wire q4_row0_room,q4_row1_room;
    wire q4_row0_valid=emission&&!emit_row;
    wire q4_row0_fire=q4_row0_valid&&q4_row0_room;
    wire q4_two_rows=row<98;
    wire q4_row1_valid=emission&&q4_two_rows&&(emit_row||q4_row0_fire);
    wire q4_row1_fire=q4_row1_valid&&q4_row1_room;
    wire jp_quant_commit=q4_row0_fire||q4_row1_fire;
    wire fifo_push=q4_row0_fire;""")
    text = edit(text, 'wire jp_last_emit_row=emit_row||(row==98);',
                'wire jp_last_emit_row=q4_row1_fire||(!q4_two_rows&&q4_row0_fire);')
    start = text.index('    wire [4:0] jp_quant_lane=')
    end = text.index('    generate for(genvar jp_lane=', start)
    text = text[:start] + """    wire [15:0] q4_result[0:3];
    generate for(genvar q4_output=0;q4_output<4;q4_output=q4_output+1)begin: q4_quantizers
        wire [4:0] index=5'(16*(q4_output/2))+5'(lane)+5'(q4_output%2);
        wire enabled=(q4_output<2)||(emission&&q4_two_rows);
        wire [35:0] bits=enabled?accumulator[index]:36'd0;
        wire signed [7:0] shift_value=enabled?shifts[index]:8'sd0;
        kwt_ffn_requantize quantizer(.value({{28{bits[35]}},bits}),
            .shift(shift_value),.result(q4_result[q4_output]));
    end endgenerate
    kwt_joint_output_queue output_queue(.clk(clk),.rst_n(rst_n),.clock_test_enable(clock_test_enable),
        .restart(layer_start_valid&&layer_start_ready),
        .row0_valid(q4_row0_valid),.row1_valid(q4_row1_valid),
        .row0_low(q4_result[0]),.row0_high(q4_result[1]),
        .row1_low(q4_result[2]),.row1_high(q4_result[3]),
        .row0_room(q4_row0_room),.row1_room(q4_row1_room),.item(item),
        .out_ready(out_ready),.out_pair_ready(out_pair_ready),.out_valid(out_valid),.out_pair_valid(out_pair_valid),
        .out_data(out_data),.out_high(out_high),.pop_count(pop_count),.fifo_count(fifo_count));
""" + text[end:]
    text = edit(text, """        wire seed_update=(bias_capture&&(chunk==3'(jp_column/2))&&((jp_row==0)||(row<98)))||
            (ap_er_reseed&&(emit_row==1'(jp_row))&&(lane[3:1]==3'(jp_column/2))&&
             ((jp_row==0)||jp_next_row1));
        wire mac_update=(state==B_MAC)&&((jp_row==0)||(row<98));
        wire quant_commit=jp_quant_commit&&(emit_row==1'(jp_row))&&(lane[3:1]==3'(jp_column/2));""",
                """        wire row_fire=(jp_row==0)?q4_row0_fire:q4_row1_fire;
        wire seed_update=(bias_capture&&(chunk==3'(jp_column/2))&&((jp_row==0)||(row<98)))||
            (row_fire&&ap_er_has_next&&(lane[3:1]==3'(jp_column/2))&&
             ((jp_row==0)||jp_next_row1));
        wire mac_update=(state==B_MAC)&&((jp_row==0)||(row<98));
        wire quant_commit=row_fire&&(lane[3:1]==3'(jp_column/2));""")
    return text


def queue_rtl(text):
    text = edit(text, """    input wire push_valid,push_row1,
    input wire [15:0] push_low,push_high,
    output wire push_ready,""", """    input wire row0_valid,row1_valid,
    input wire [15:0] row0_low,row0_high,row1_low,row1_high,
    output wire row0_room,row1_room,""")
    text = edit(text, "wire row1_room=", "assign row1_room=")
    text = edit(text, "wire row0_room=", "assign row0_room=")
    text = edit(text, "push_valid&&push_row1&&row1_room", "row1_valid&&row1_room")
    text = edit(text, "push_valid&&!push_row1&&row0_room", "row0_valid&&row0_room")
    text = edit(text, "    assign push_ready=push_row1?row1_room:row0_room;\n", "")
    text = edit(text, "bank==0?push_low:push_high", "bank==0?row1_low:row1_high")
    return edit(text, "half==0?push_low:push_high", "half==0?row0_low:row0_high")


def prepare():
    model = json.loads((REPORT/'model-results.json').read_text())
    if not (model['calibrated'] and model['functional_passed'] and model['timing_eligible']):
        raise RuntimeError('The Q4 cold model has not passed the release criterion')
    selected = ROOT/'constraints/ffn_selected.json'
    base = json.loads(selected.read_text())
    receipt = ROOT/'reports/submission/ara-SR-release-20261105/completion.json'
    release = json.loads(receipt.read_text())
    if base['variant'] != 'ffn_ara_SR' or not release['complete']:
        raise RuntimeError('Expected frozen SR release')
    source = ROOT/base['source_snapshot']
    candidate = ROOT/'build/optimization/rtl_sources'/VARIANT
    shutil.copytree(source, candidate, dirs_exist_ok=True)
    for relative, generator in [(CORE,core_rtl),(QUEUE,queue_rtl)]:
        text = generator((source/relative).read_text())
        path = REPORT/'candidate-rtl'/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
        shutil.copyfile(path,candidate/relative)
    shutil.copyfile(selected,REPORT/'baseline-selected.json')
    shutil.copyfile(receipt,REPORT/'baseline-release.json')
    dump(REPORT/'objective.json',dict(variant=VARIANT, baseline='ffn_ara_SR',
        maximum_cycles_exclusive=sum(release['cycles']), maximum_area_exclusive_mm2=0.300,
        maximum_mean_energy_j=release['mean_energy_j'], publication_changed=False))
    return json.loads((ROOT/base['adaptive_manifest']).read_text()), source, candidate
