"""Derive only independent SS and model-selected O1 from published C bytes."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2];BUILD=ROOT/'build/optimization/ffn_c_final_energy';REPORT=ROOT/'reports/optimization/ffn_c_final_energy'

def variants():return ['ffn_cfe_'+name for name in json.loads((REPORT/'models/selection.json').read_text())['candidates']]

def shared_shift(text):
    text=text.replace('reg signed [7:0] shifts[0:MAC_LANES-1];','reg signed [7:0] shifts[0:MAC_COLUMNS-1];')
    text=text.replace('.shift(shifts[jp_quant_lane])','.shift(shifts[lane])').replace(".shift(shifts[{1'b0,jp_quant_lane}+6'd1])",".shift(shifts[{1'b0,lane}+5'd1])")
    text=text.replace('wire accumulator_clk,shift_register_clk;','wire accumulator_clk;')
    text=text.replace('''            kwt_ffn_clock_gate shift_gate(.clk(clk),.enable(seed_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(shift_register_clk));
''','')
    text=text.replace('            assign shift_register_clk=jp_mac_lanes[jp_lane-1].shift_register_clk;\n','')
    old='''        always @(posedge shift_register_clk or negedge rst_n)begin
            if(!rst_n)shifts[jp_lane]<=0;
            else if(seed_update)shifts[jp_lane]<=$signed(jp_shift_return[(jp_column%2)*8+:8]);
        end
'''
    if text.count(old)!=1:raise RuntimeError('Read original shift state block')
    text=text.replace(old,'',1)
    block='''    generate for(genvar ss_column=0;ss_column<MAC_COLUMNS;ss_column=ss_column+1)begin: ss_shift_columns
        wire shift_update=(bias_capture&&(chunk==3'(ss_column/2)))||
            (ap_er_reseed&&jp_last_emit_row&&(lane[3:1]==3'(ss_column/2)));
        wire shift_register_clk;
        if(ss_column%2==0)begin: pair_gate
            kwt_ffn_clock_gate shift_gate(.clk(clk),.enable(shift_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(shift_register_clk));
        end else assign shift_register_clk=ss_shift_columns[ss_column-1].shift_register_clk;
        always @(posedge shift_register_clk or negedge rst_n)begin
            if(!rst_n)shifts[ss_column]<=0;
            else if(shift_update)shifts[ss_column]<=$signed(jp_shift_return[(ss_column%2)*8+:8]);
        end
    end endgenerate
'''
    return text.replace('    assign start_ready=state==IDLE;',block+'    assign start_ready=state==IDLE;',1)

def output_bypass(text):
    text=text.replace('    wire drain0=(fifo_count!=0)&&(row0_count<128)&&!read0;',"    wire bypass=(fifo_count!=0)&&(space!=0)&&(next_item<16'd25344)&&!next_row1&&(row0_count==8'(capture0));\n    wire drain0=(fifo_count!=0)&&(row0_count<128)&&!read0&&!bypass;\n    wire fifo_take=drain0||bypass;\n    wire [15:0] fifo_head=fifo[fifo_read];")
    text=text.replace("6'(drain0)","6'(fifo_take)").replace('assign data=fifo[fifo_read];','assign data=fifo_head;')
    text=text.replace("if(drain0)begin fifo_read<=fifo_read+1'b1;row0_write<=row0_write+1'b1;end","if(fifo_take)fifo_read<=fifo_read+1'b1;\n            if(drain0)row0_write<=row0_write+1'b1;")
    text=text.replace("-5'(drain0)","-5'(fifo_take)")
    text=text.replace('            held_count<=remaining+pending_count;','''            if(bypass)begin
                if(remaining+pending_count==0)held_low<=fifo_head;
                else held_high<=fifo_head;
            end
            held_count<=remaining+pending_count+2'(bypass);''')
    return text

def prepare(name):
    if name not in variants():raise ValueError('Unselected final C energy candidate '+name)
    kind=name[len('ffn_cfe_'):];parent=json.loads((BUILD/'frozen/parent.json').read_text());source=BUILD/'frozen/rtl_sources';target=ROOT/'build/optimization/rtl_sources'/name;changes=[]
    for p in source.rglob('*'):
        if not p.is_file():continue
        value=p.read_bytes();text=value.decode() if p.suffix in ['.sv','.svh'] else None
        if kind=='SS' and p.name=='kwt_encoder.sv':value=shared_shift(text).encode()
        elif kind=='O1' and p.name=='kwt_joint_output_queue.sv':value=output_bypass(text).encode()
        if value!=p.read_bytes():changes.append(dict(path=p.relative_to(source).as_posix(),mechanism=kind))
        t=target/p.relative_to(source);t.parent.mkdir(parents=True,exist_ok=True)
        if not t.exists() or t.read_bytes()!=value:t.write_bytes(value)
    manifest={k:v for k,v in parent.items() if k not in ['state','profile','firmware','source_snapshot','configuration','program']}
    manifest.update(variant=name,parent_variant='ffn_wen_C',parent=parent,hardware=list(parent['hardware'])+[kind],c_final_energy_hardware=[kind],effective_changes=dict(parent['effective_changes'],c_final_energy_hardware=[kind]),purpose='experiment',objective=['energy_below_C','area_within_authorized_budget','throughput_at_least_1000'],automatic_release_switch=False)
    d=ROOT/'constraints/ffn_c_final_energy/candidates';d.mkdir(parents=True,exist_ok=True);(d/(name+'.json')).write_text(json.dumps(manifest,indent=2));(REPORT/(name+'-source-changes.json')).write_text(json.dumps(dict(parent='ffn_wen_C',changes=changes,other_files_byte_equal=True,combined=False),indent=2));return manifest,target

if __name__=='__main__':
    for name in variants():prepare(name)
