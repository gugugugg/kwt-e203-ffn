"""Materialize the sole hardware candidate after the model screen."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
NAME, PARENT = 'ffn_r4f2_q8', 'ffn_m3_retire'
REPORT = ROOT / 'reports/optimization' / NAME
SOURCE = ROOT / 'build/optimization/rtl_sources' / NAME
SOC = ROOT / 'build/optimization/complete_soc' / NAME
RTL_TEST = ROOT / 'build/optimization/rtl' / NAME
FIRMWARE = ROOT / 'build/optimization/firmware' / NAME
sys.path.insert(0,str(ROOT/'scripts/r3o_stream'))
import build_candidate as stream
from prepare import replace


def group_queue(text):
    """Retain the four-word register return and replace the five old stash banks."""
    text = replace(text, """    input wire push_valid,
    input wire [1:0] push_row,
    input wire [15:0] push_low,push_high,
    output wire push_ready,""", """    input wire reserve,compute_generation,group_done,commit,
    input wire [2:0] valid_rows,
    input wire [6:0] write_address,
    input wire [127:0] write_words,
    output wire generation_empty,""")
    text = replace(text, '''    output wire [1:0] pop_count,
    output reg [4:0] fifo_count''', '''    output wire [1:0] pop_count''')
    start = text.index('    reg [15:0] fifo')
    stop = text.index('    reg [15:0] held_data',start)
    text = text[:start] + '''    localparam [1:0] EMPTY=2'd0,FILL=2'd1,READY=2'd2;
    reg [1:0] generation_state[0:1];
    reg [2:0] held_count;
    reg [1:0] pending_count,pending_row;
    reg pending_generation,pending_parity;
    assign generation_empty=generation_state[compute_generation]==EMPTY;
''' + text[stop:]
    start = text.index('    function automatic [1:0] following_row')
    stop = text.index('    generate for(genvar slot=',start)
    text = text[:start] + '''    wire [2:0] space=3'd4-held_count-3'(pending_count)+3'(pop_count);
    wire [15:0] next_item={1'b0,item}+16'(held_count)+16'(pending_count);
    wire [15:0] retired_end={1'b0,item}+16'(pop_count);
    wire retire_group=(pop_count!=0)&&((retired_end[10]!=item[10])||(retired_end==16'd25344));
    wire issue_generation=next_item[10];
    wire [1:0] issue_row=next_item[9:8];
    wire issue=space!=0&&(next_item<16'd25344)&&(generation_state[issue_generation]==READY);
    wire issue_pair=issue&&(space>=2)&&(next_item[7:0]!=8'hff);
    wire [1:0] issue_count=issue_pair?2'd2:(issue?2'd1:2'd0);

    wire [255:0] memory_data;
    generate for(genvar bank=0;bank<16;bank=bank+1)begin: row_stash
        localparam integer GEN=bank/8, ROW=(bank/2)%4, PARITY=bank%2;
        wire write_en=commit&&(compute_generation==1'(GEN))&&(3'(ROW)<valid_rows);
        wire read_en=issue&&(issue_generation==1'(GEN))&&(issue_row==2'(ROW))&&
                     (issue_pair||(next_item[0]==1'(PARITY)));
        wire [6:0] read_address=next_item[7:1]+7'(issue_pair&&next_item[0]&&(PARITY==0));
        wire [6:0] address=write_en?write_address:read_address;
        wire memory_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(write_en||read_en),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(write_en||read_en),.we(write_en),
            .addr(address),.wdata(write_words[(ROW*2+PARITY)*16+:16]),.rdata(memory_data[bank*16+:16]));
    end endgenerate

    wire [2:0] returned_bank={pending_generation,pending_row};
    wire [31:0] returned_pair=memory_data[returned_bank*32+:32];
    wire [1:0] fill_count=pending_count;
    wire [15:0] fill_low=pending_parity?returned_pair[31:16]:returned_pair[15:0];
    wire [15:0] fill_high=pending_parity?returned_pair[15:0]:returned_pair[31:16];
''' + text[stop:]
    start = text.index('    integer row_index;')
    return text[:start] + '''    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            generation_state[0]<=EMPTY;generation_state[1]<=EMPTY;
            held_count<=0;pending_count<=0;held_head<=0;held_tail<=0;
            pending_generation<=0;pending_row<=0;pending_parity<=0;
        end else if(restart)begin
            generation_state[0]<=EMPTY;generation_state[1]<=EMPTY;
            held_count<=0;pending_count<=0;held_head<=0;held_tail<=0;
        end else begin
            if(retire_group)generation_state[item[10]]<=EMPTY;
            if(reserve)generation_state[compute_generation]<=FILL;
            if(group_done)generation_state[compute_generation]<=READY;
            held_head<=held_head+pop_count;
            held_tail<=held_tail+fill_count;
            held_count<=held_count-3'(pop_count)+3'(fill_count);
            pending_count<=issue_count;
            pending_generation<=issue_generation;
            pending_row<=issue_row;
            pending_parity<=next_item[0];
        end
    end
endmodule
'''


def encoder(text):
    text = replace(text,'MAC_LANES=48','MAC_LANES=64')
    text = replace(text,'    reg [1:0] emit_row;\n','')
    text = replace(text,'    // Packed and scalar PIO writes follow the same k-major three-row order.','    // Full input groups pack four rows; the last group packs three.')
    text = replace(text,'advance_input_cursor(input [8:0] cursor);','advance_input_cursor(input [8:0] cursor,input tail);')
    text = replace(text,"if(cursor[1:0]==2'd2)", "if(cursor[1:0]==(tail?2'd2:2'd3))")
    text = replace(text,'advance_input_cursor(input_write_cursor);','advance_input_cursor(input_write_cursor,input_count>=13\'d6144);')
    text = replace(text,"+14'd6)<<6","+14'd8)<<6")
    text = replace(text,"wire [2:0] block_rows=3'd3;", "wire [2:0] block_rows=(row==7'd96)?3'd3:3'd4;")
    text = replace(text,'''    wire [4:0] fifo_count;
    wire [1:0] pop_count;
    wire emission=state==EMIT;
    wire jp_quant_ready;
    wire jp_quant_commit=emission&&jp_quant_ready;
    wire fifo_push=jp_quant_commit&&!emit_row;
    wire [1:0] tp_push_count=fifo_push?2'd2:2'd0;''','''    wire [1:0] pop_count;
    wire emission=state==EMIT;
    wire jp_quant_commit=emission;
    wire fifo_push=jp_quant_commit;
    wire output_generation_empty;
    wire output_reserve=(state==WAIT_INPUT)&&input_complete&&output_generation_empty;
    wire output_group_done=jp_quant_commit&&(tile==15)&&(lane==14);''')
    text = replace(text,"wire jp_last_emit_row=emit_row==2;", "wire jp_last_emit_row=1'b1;")
    text = replace(text,'wire [47:0] ap_input_rdata;\n    reg [95:0] jp_input_return;',
                   'wire [63:0] ap_input_rdata;\n    reg [127:0] jp_input_return;')
    start = text.index('    generate for(genvar ap_row=0;')
    stop = text.index('    reg [15:0] jp_shift_return;',start)
    text = text[:start] + '''    generate for(genvar ap_row=0;ap_row<4;ap_row=ap_row+1)begin: ap_input_rows
        wire [31:0] generation_data;
        wire row_valid=3'(ap_row)<block_rows;
        assign ap_input_rdata[ap_row*16+:16]=generation_data[input_read_generation*16+:16];
        for(genvar gen=0;gen<2;gen=gen+1)begin: generations
            wire low_write=input_loading&&(input_write_cursor[8]==1'(gen))&&(input_write_cursor[1:0]==2'(ap_row));
            wire high_write=input_loading&&(load_count==2)&&(input_high_cursor[8]==1'(gen))&&(input_high_cursor[1:0]==2'(ap_row));
            wire write_enable=low_write||high_write;
            wire read_enable=ap_input_read&&row_valid&&(input_read_generation==1'(gen));
            wire memory_enable=write_enable||read_enable;
            wire [5:0] offset=write_enable?(high_write?input_high_cursor[7:2]:input_write_cursor[7:2]):request_inner;
            wire memory_clk;
            kwt_ffn_clock_gate gate(.clk(clk),.enable(memory_enable),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
            kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(memory_enable),.we(write_enable),
                .addr({1'b0,offset}),.wdata(high_write?load_high:load_data),.rdata(generation_data[gen*16+:16]));
        end
        for(genvar cp_copy=0;cp_copy<2;cp_copy=cp_copy+1)begin: return_copies
            wire lp_return_clock;
            wire capture_row=capture_operands&&row_valid;
            kwt_ffn_clock_gate return_gate(.clk(clk),.enable(capture_row),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(lp_return_clock));
            always @(posedge lp_return_clock)if(capture_row)
                jp_input_return[(ap_row*2+cp_copy)*16+:16]<=ap_input_rdata[ap_row*16+:16];
        end
    end endgenerate
''' + text[stop:]
    start = text.index('    wire [5:0] jp_quant_lane')
    stop = text.index('    generate for(genvar jp_lane=',start)
    text = text[:start] + '''    wire [127:0] quant_words;
    generate for(genvar qr=0;qr<4;qr=qr+1)begin: quant_rows
        wire [5:0] low_index={2'(qr),lane};
        wire [5:0] high_index=low_index+6'd1;
        wire [35:0] low_value=accumulator[low_index],high_value=accumulator[high_index];
        kwt_ffn_requantize quantizer(.value({{28{low_value[35]}},low_value}),.shift(shifts[low_index]),
            .result(quant_words[qr*32+:16]));
        kwt_ffn_requantize high_quantizer(.value({{28{high_value[35]}},high_value}),.shift(shifts[high_index]),
            .result(quant_words[qr*32+16+:16]));
    end endgenerate
    kwt_joint_output_queue output_queue(.clk(clk),.rst_n(rst_n),.clock_test_enable(clock_test_enable),
        .restart(layer_start_valid&&layer_start_ready),.reserve(output_reserve),.compute_generation(input_read_generation),
        .group_done(output_group_done),.commit(jp_quant_commit),.valid_rows(block_rows),
        .write_address({tile,lane[3:1]}),.write_words(quant_words),.generation_empty(output_generation_empty),
        .item(item),.out_ready(out_ready),.out_pair_ready(out_pair_ready),.out_valid(out_valid),
        .out_pair_valid(out_pair_valid),.out_data(out_data),.out_high(out_high),.pop_count(pop_count));
''' + text[stop:]
    text = replace(text,'''        wire seed_update=(bias_capture&&(chunk==3'(jp_column/2)))||
            (ap_er_reseed&&(emit_row==2'(jp_row))&&(lane[3:1]==3'(jp_column/2)));
        wire mac_update=state==B_MAC;
        wire quant_commit=jp_quant_commit&&(emit_row==2'(jp_row))&&(lane[3:1]==3'(jp_column/2));''','''        wire row_valid=3'(jp_row)<block_rows;
        wire next_row_valid=(jp_row!=3)||((tile==15)?(row<7'd92):row_valid);
        wire seed_update=(row_valid&&bias_capture&&(chunk==3'(jp_column/2)))||
            (next_row_valid&&ap_er_reseed&&(lane[3:1]==3'(jp_column/2)));
        wire mac_update=(state==B_MAC)&&row_valid;
        wire quant_commit=jp_quant_commit&&row_valid&&(lane[3:1]==3'(jp_column/2));''')
    text = replace(text,'<input_window_limit)&&!ap_input_read','<input_window_limit)')
    text = text.replace('emit_row<=0;','')
    text = replace(text,'advance_input_cursor(input_high_cursor):input_high_cursor;',
                   "advance_input_cursor(input_high_cursor,input_count>=13'd6143):input_high_cursor;")
    text = replace(text,'WAIT_INPUT:if(input_complete)state<=MAC_INIT;', 'WAIT_INPUT:if(output_reserve)state<=MAC_INIT;')
    start = text.index('                EMIT:if(jp_quant_commit)')
    stop = text.index('                ADVANCE:',start)
    text = text[:start] + """                EMIT:if(jp_quant_commit)begin
                    if(lane<14)lane<=lane+4'd2;
                    else if(tile<15)begin tile<=tile+1'b1;inner<=0;chunk<=0;state<=A_REQ;end
                    else state<=ADVANCE;
                end
""" + text[stop:]
    return replace(text,"row<=row+7'd3","row<=row+7'd4")


def bench_common(text, core):
    text = re.sub(r'for\(genvar (jp_lane|car_lane|lane_id)=0;\1<48;',
                  lambda m:m[0].replace('<48','<64'),text)
    text = replace(text,'cp_row<3;cp_row=', 'cp_row<4;cp_row=')
    text = replace(text,'&&'+core+'.capture_operands;',
                   '&&'+core+'.capture_operands&&(3\'(cp_row)<'+core+'.block_rows);')
    text = replace(text,'ap_push_words=ap_push_words+2;',
                   "ap_push_words=ap_push_words+2*int'("+core+'.block_rows);')
    text = replace(text,'ap_pair_pushes=ap_pair_pushes+1;',
                   "ap_pair_pushes=ap_pair_pushes+int'("+core+'.block_rows);')
    return text


def local_bench(text):
    text = bench_common(text,'dut.core')
    text = replace(text,'''        integer base, offset;
        begin
            base=(at/192)*192;
            offset=at%192;
            input_stream_word=inputs[base+(offset%3)*64+offset/3];''',
        '''        integer base, offset, rows;
        begin
            base=(at/256)*256;
            offset=at%256;
            rows=(base==6144)?3:4;
            input_stream_word=inputs[base+(offset%rows)*64+offset/rows];''')
    text = replace(text,'at%17==0||at==190','(at%17==0&&at!=255)||at==254')
    text = replace(text,'input_count==191','input_count==255')
    text = replace(text,'            active=0;trace_count=0;',
        '''            active=0;trace_count=0;
            if(mixed_access&&layer==1)begin
                @(negedge clk);rst_n=0;repeat(4)@(negedge clk);rst_n=1;
            end''')
    return text


def probes(text):
    core='dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core'
    kept=[line for line in text.splitlines()
          if not any(token in line for token in ('ap_input_rows','output_queue','[28:0]'))]
    prefix='wire [44:0] ram_en,ram_we;'
    for index in range(8):
        path=core+'.ap_input_rows[%d].generations[%d].memory'%(index//2,index%2)
        pin=index if index<2 else 21+index
        kept.append('assign ram_en[%d]=%s.en;assign ram_we[%d]=%s.we;'%(pin,path,pin,path))
    for bank in range(16):
        path=core+'.output_queue.row_stash[%d].memory'%bank
        kept.append('assign ram_en[%d]=%s.en;assign ram_we[%d]=%s.we;'%(29+bank,path,29+bank,path))
    return prefix+'\n'+'\n'.join(kept)+'\n'


def native_bench(text):
    core='dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core'
    text=bench_common(text,core)
    text=re.sub(r'(?m)^.*\.output_queue\.bypass_count.*\n','',text)
    text=text.replace('M3_RETIRE_COUNTS','Q8_RETIRE_COUNTS').replace('direct_words=%0d ','').replace('retire_direct,\n','\n')
    text=text.replace(core+'.emit_row', "2'd0")
    text=text.replace(core+'.fifo_count', core+'.output_queue.held_count')
    for group, indices in [('input',(0,1,23,24,25,26,27,28)),('stash',range(29,45))]:
        for kind in ('reads','writes'):
            mask='!' if kind=='reads' else ''
            field='res_%s_%s'%(group,kind)
            expression='+'.join("int'(ram_en[%d]&&%sram_we[%d])"%(i,mask,i) for i in indices)
            text=re.sub(r'(?m)^(integer '+field+r'=0;.*?\b'+field+r'=).*?;$',
                        lambda m:m[1]+field+'+'+expression+';',text)
    return text


def materialize():
    selection=json.loads((REPORT/'model-selection.json').read_text())
    if not selection['passed'] or selection['selected']!='Q8':
        raise RuntimeError('Q8 did not qualify from the model screen')
    previous=ROOT/'constraints/ffn_selected.json'
    cfg=json.loads(previous.read_text())
    assert cfg['variant']==PARENT
    (REPORT/'baseline-selected.json').write_bytes(previous.read_bytes())
    old_source=ROOT/cfg['source_snapshot']
    shutil.copytree(old_source,SOURCE,dirs_exist_ok=True)
    for name,transform in [('kwt_encoder.sv',encoder),('kwt_joint_output_queue.sv',group_queue)]:
        rel=Path('encoder')/name
        (SOURCE/rel).write_text(transform((old_source/rel).read_text()),newline='\n')
    old=SOC.with_name(PARENT)
    SOC.mkdir(exist_ok=True)
    for path in old.iterdir():
        if not path.is_file() or path.suffix not in ('.sv','.v','.svh','.f','.json','.sh'):
            continue
        text=path.read_text().replace(PARENT,NAME).replace(cfg['firmware'],FIRMWARE.relative_to(ROOT).as_posix())
        if path.name=='complete_soc_tb.sv':
            text=native_bench(text)
        elif path.name=='sram_probes.svh':
            text=probes(text)
        elif path.name=='boot_count.svh':
            count=json.loads((FIRMWARE/'firmware.json').read_text())['boot_words']
            text='localparam BOOT_WORDS=%d;\n'%count
        elif path.name=='configuration.json':
            data=json.loads(text)
            data.update(row_group=4,input_layout='group4_inner_major_tail3',compute_mac_count=64,requantizers=8)
            data.pop('retirement',None)
            text=json.dumps(data,indent=2)+'\n'
        (SOC/path.name).write_text(text,newline='\n')
    eda=SOC/'eda'
    eda.mkdir(exist_ok=True)
    for path in (old/'eda').glob('*.tcl'):
        (eda/path.name).write_text(path.read_text().replace(PARENT,NAME),newline='\n')
    images=SOC/'packed_inputs';images.mkdir(exist_ok=True)
    base=ROOT/cfg['linear_images']
    for case in range(1,24,2):
        old_words=(base/('task_%02d_shared.hex'%case)).read_text().splitlines()[:3168]
        samples=[half for word in map(lambda s:int(s,16),old_words) for half in (word&65535,word>>16)]
        packed=[samples[r*64+k] for row in range(0,99,4) for k in range(64) for r in range(row,min(99,row+4))]
        data=[low|high<<16 for low,high in zip(packed[::2],packed[1::2])]
        (images/('task_%02d_packed.hex'%case)).write_text(''.join('%08x\n'%w for w in data))
    manifest=json.loads((ROOT/cfg['adaptive_manifest']).read_text())
    manifest.update(variant=NAME,parent_variant=PARENT,purpose='experiment',input_layout='group4_inner_major_tail3')
    manifest['changes'].update(row_group=4,compute_mac_count=64,requantizers=8)
    manifest['hardware']+=['Q8','physical_dual_generation']
    manifest['parent']=dict(variant=PARENT,configuration=cfg,firmware=cfg['firmware'],
                            source_snapshot=cfg['source_snapshot'],profile=cfg['implementation'])
    folder=ROOT/'constraints'/NAME/'candidates';folder.mkdir(parents=True,exist_ok=True)
    (folder/(NAME+'.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    RTL_TEST.mkdir(exist_ok=True)
    (RTL_TEST/'loading_dma_tb.sv').write_text(local_bench(
        (RTL_TEST.with_name('ffn_r3o_stream')/'loading_dma_tb.sv').read_text()))


def develop():
    stream.SOURCE,stream.RTL_TEST,stream.REPORT=SOURCE,RTL_TEST,REPORT
    run=stream.run
    def run_case(args,log):
        if log.name=='local-actual12.log' and log.is_file():
            previous=log.read_text()
            if previous.count('FFN_NEXT_RTL_PASS layer=')==12 and 'FFN_NEXT_RTL_ALL_PASS' in previous:
                return
        run([('+ROW_GROUP=4' if a=='+ROW_GROUP=3' else a) for a in args],log)
    stream.run=run_case
    stream.develop()
    path=REPORT/'local-acceptance.json'
    data=json.loads(path.read_text());data.update(lanes=64,output_requantizers=8)
    path.write_text(json.dumps(data,indent=2)+'\n')


if __name__=='__main__':
    {'materialize':materialize,'develop':develop}[sys.argv[1]]()
