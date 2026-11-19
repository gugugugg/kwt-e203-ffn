"""Generate the three-row core from frozen SR after the causal screen."""
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
NAME = 'ffn_sr_r3o'
REPORT = ROOT/'reports/optimization'/NAME
sys.path.insert(0,str(ROOT/'scripts/sr_pr1'))
from prepare import replace

CORE = Path('encoder/kwt_encoder.sv')
QUEUE = Path('encoder/kwt_joint_output_queue.sv')


def transform(text):
    edits = [
        ('MAC_LANES=32','MAC_LANES=48'),
        ('A_REQ=6,B_MAC=7,EMIT=8,ROW1_MAC=9,ADVANCE=14','A_REQ=6,B_MAC=7,EMIT=8,ROW1_MAC=9,B_FILL=10,ADVANCE=14'),
        ('    reg emit_row;','    reg [1:0] emit_row;\n    reg [1:0] input_write_row;\n    reg input_write_generation,input_read_generation;'),
        ("wire [2:0] block_rows=row==98?3'd1:3'd2;","wire [2:0] block_rows=3'd3;"),
        ('(row<98)||(tile<15)','(row<96)||(tile<15)'),
        ('    wire jp_next_row1=(tile==15)?(row<96):(row<98);\n',''),
        ('wire jp_last_emit_row=emit_row||(row==98);','wire jp_last_emit_row=emit_row==2;'),
        ("""    wire prefetch=(state==B_MAC)&&(inner<63);
    wire [5:0] request_inner=6'({1'b0,inner}+7'(prefetch));""","""    wire prefetch=(state==B_FILL)||((state==B_MAC)&&(inner<62));
    wire capture_operands=(state==B_FILL)||((state==B_MAC)&&(inner<63));
    wire [5:0] request_inner=(state==B_FILL)?6'd1:((state==B_MAC)?inner+6'd2:6'd0);"""),
        ("wire [4:0] jp_quant_lane={emit_row,lane};","wire [5:0] jp_quant_lane={emit_row,lane};"),
        ('{1\'b0,jp_quant_lane}+6\'d1','jp_quant_lane+6\'d1'),
        ('.push_row1(emit_row)','.push_row(emit_row)'),
        ("""        wire seed_update=(bias_capture&&(chunk==3'(jp_column/2))&&((jp_row==0)||(row<98)))||
            (ap_er_reseed&&(emit_row==1'(jp_row))&&(lane[3:1]==3'(jp_column/2))&&
             ((jp_row==0)||jp_next_row1));
        wire mac_update=(state==B_MAC)&&((jp_row==0)||(row<98));
        wire quant_commit=jp_quant_commit&&(emit_row==1'(jp_row))&&(lane[3:1]==3'(jp_column/2));""",
        """        wire seed_update=(bias_capture&&(chunk==3'(jp_column/2)))||
            (ap_er_reseed&&(emit_row==2'(jp_row))&&(lane[3:1]==3'(jp_column/2)));
        wire mac_update=state==B_MAC;
        wire quant_commit=jp_quant_commit&&(emit_row==2'(jp_row))&&(lane[3:1]==3'(jp_column/2));"""),
        ('weight_value=$signed(pm_rdata[jp_column*16+:16]);','weight_value=$signed(operand_weight[jp_column*16+:16]);'),
        ("14'd4)<<6","14'd6)<<6"),
        ('A_REQ:if(input_complete)state<=B_MAC;','A_REQ:if(input_complete)state<=B_FILL;\n                B_FILL:state<=B_MAC;'),
        ('if(!jp_last_emit_row)emit_row<=1;',"if(!jp_last_emit_row)emit_row<=emit_row+2'd1;"),
        ('ADVANCE:if(row==98)','ADVANCE:if(row==96)'),
        ("else begin row<=row+7'd2;tile<=0;lane<=0;state<=WAIT_INPUT;end",
         "else begin row<=row+7'd3;input_read_generation<=!input_read_generation;tile<=0;lane<=0;state<=WAIT_INPUT;end"),
        ('row<=0;tile<=0;lane<=0;inner<=0;chunk<=0;item<=0;emit_row<=0;',
         'row<=0;tile<=0;lane<=0;inner<=0;chunk<=0;item<=0;emit_row<=0;\n'
         '            input_write_row<=0;input_write_generation<=0;input_read_generation<=0;'),
        ('row<=0;tile<=0;item<=0;lane<=0;inner<=0;emit_row<=0;state<=WAIT_INPUT;',
         'row<=0;tile<=0;item<=0;lane<=0;inner<=0;emit_row<=0;state<=WAIT_INPUT;\n'
         '                    input_write_row<=0;input_write_generation<=0;input_read_generation<=0;'),
        ('0:if(load_addr==16\'(input_count)&&input_count<6336)input_count<=input_count+13\'(load_count);else error<=1;',
         """0:if(load_addr==16'(input_count)&&input_count<6336)begin
                    input_count<=input_count+13'(load_count);
                    if(load_addr[5:0]==6'd63)begin
                        if(input_write_row==2)begin
                            input_write_row<=0;input_write_generation<=!input_write_generation;
                        end else input_write_row<=input_write_row+2'd1;
                    end
                end else error<=1;"""),
    ]
    for old,new in edits:
        if old=="{1'b0,jp_quant_lane}+6'd1":
            if text.count(old)!=2:
                raise ValueError('Unexpected high quantizer selection')
            text=text.replace(old,new)
        else:
            text=replace(text,old,new)
    begin=text.index('    wire [31:0] ap_input_rdata;')
    end=text.index('    reg [15:0] jp_shift_return;',begin)
    return text[:begin]+"""    wire [47:0] ap_input_rdata;
    reg [95:0] jp_input_return;
    reg [16*LANES-1:0] operand_weight;
    wire operand_weight_clk;
    kwt_ffn_clock_gate weight_stage_gate(.clk(clk),.enable(capture_operands),
        .test_enable(clock_test_enable||!rst_n),.gated_clk(operand_weight_clk));
    always @(posedge operand_weight_clk)if(capture_operands)operand_weight<=pm_rdata;
    generate for(genvar ap_row=0;ap_row<3;ap_row=ap_row+1)begin: ap_input_rows
        wire write_enable=input_loading&&(input_write_row==2'(ap_row));
        wire read_enable=ap_input_read;
        wire memory_enable=write_enable||read_enable;
        wire [6:0] memory_addr=write_enable?{input_write_generation,load_addr[5:0]}:
                                            {input_read_generation,request_inner};
        for(genvar cp_copy=0;cp_copy<2;cp_copy=cp_copy+1)begin: return_copies
            wire lp_return_clock;
            kwt_ffn_clock_gate return_gate(.clk(clk),.enable(capture_operands),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(lp_return_clock));
            always @(posedge lp_return_clock)if(capture_operands)
                jp_input_return[(ap_row*2+cp_copy)*16+:16]<=ap_input_rdata[ap_row*16+:16];
        end
        wire memory_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(memory_enable),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(memory_enable),.we(write_enable),
            .addr(memory_addr),.wdata(load_data),.rdata(ap_input_rdata[ap_row*16+:16]));
    end endgenerate
"""+text[end:]


def main():
    model=json.loads((REPORT/'model-results.json').read_text())
    cfg=json.loads((ROOT/'constraints/ffn_selected.json').read_text())
    if not model['model_passed'] or cfg['variant']!='ffn_ara_SR':
        raise RuntimeError('R3O model or frozen SR selection differs')
    old=ROOT/cfg['source_snapshot']
    new=old.with_name(NAME)
    if not new.exists():
        shutil.copytree(str(old),str(new))
    for relative,data in ((CORE,transform((old/CORE).read_text()).encode('ascii')),
                          (QUEUE,(Path(__file__).with_name(QUEUE.name)).read_bytes())):
        (new/relative).write_bytes(data)
        (REPORT/relative.name).write_bytes(data)

if __name__=='__main__':
    main()
