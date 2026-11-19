"""Derive only the model winner from the byte-frozen Q8 platform."""
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
NAME, PARENT = 'ffn_q8_q16', 'ffn_r4f2_q8'
REPORT = ROOT / 'reports/optimization' / NAME
SOURCE = ROOT / 'build/optimization/rtl_sources' / NAME
SOC = ROOT / 'build/optimization/complete_soc' / NAME
RTL = ROOT / 'build/optimization/rtl' / NAME
CORE = 'dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core'
sys.path.insert(0, str(ROOT / 'scripts/r4f2_q8'))
import build_q8 as q8

replace = q8.replace


def encoder(text, pf2):
    text = text.replace('lane==14','lane==12').replace('lane<14','lane<12')
    text = replace(text, "if(lane<12)lane<=lane+4'd2;", "if(lane<12)lane<=lane+4'd4;")
    text = replace(text, "wire ap_er_first_request=(state==B_MAC)&&(inner==63)&&ap_er_has_next;",
                   "wire ap_er_first_request=(state==B_MAC)&&(inner==55)&&ap_er_has_next;")
    text = replace(text, "wire ap_er_next_request=ap_er_reseed&&jp_last_emit_row&&(lane<12);",
                   "wire ap_er_next_request=(state==B_MAC)&&(inner>=56)&&(inner<63)&&ap_er_has_next;")
    text = replace(text, "wire [2:0] ap_er_request_pair=ap_er_first_request?3'd0:lane[3:1]+3'd1;",
                   "wire [2:0] ap_er_request_pair=inner[2:0]+3'd1;")
    text = replace(text, '    wire [127:0] quant_words;', '''    wire q16_shadow_capture=(state==B_MAC)&&(inner>=56)&&ap_er_has_next;
    reg [79:0] q16_seed_shadow[0:7];
    generate for(genvar pair_id=0;pair_id<8;pair_id=pair_id+1)begin: q16_shadow_pairs
        wire write_shadow=q16_shadow_capture&&(inner[2:0]==3'(pair_id));
        wire shadow_clk;
        if(CLOCK_GATING) begin: gated
            kwt_ffn_clock_gate gate(.clk(clk),.enable(write_shadow),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(shadow_clk));
        end else assign shadow_clk=clk;
        always @(posedge shadow_clk) if(write_shadow)
            q16_seed_shadow[pair_id]<={jp_shift_return,bias_rdata};
    end endgenerate
    wire [255:0] quant_words;''')
    start = text.index('    generate for(genvar qr=0;')
    stop = text.index('    kwt_joint_output_queue',start)
    text = text[:start] + '''    generate for(genvar qr=0;qr<4;qr=qr+1)begin: quant_rows
        for(genvar qc=0;qc<4;qc=qc+1)begin: quant_columns
            wire active=jp_quant_commit&&(3'(qr)<block_rows);
            wire [35:0] value;
            wire [7:0] scale;
            wire [3:0] select_quartet;
            for(genvar q=0;q<4;q=q+1)begin: select_input
                assign select_quartet[q]=active&&(lane[3:2]==2'(q));
            end
            assign value=({36{select_quartet[0]}}&accumulator[qr*16+qc]) |
                         ({36{select_quartet[1]}}&accumulator[qr*16+qc+4]) |
                         ({36{select_quartet[2]}}&accumulator[qr*16+qc+8]) |
                         ({36{select_quartet[3]}}&accumulator[qr*16+qc+12]);
            assign scale=({8{select_quartet[0]}}&shifts[qr*16+qc]) |
                         ({8{select_quartet[1]}}&shifts[qr*16+qc+4]) |
                         ({8{select_quartet[2]}}&shifts[qr*16+qc+8]) |
                         ({8{select_quartet[3]}}&shifts[qr*16+qc+12]);
            kwt_ffn_requantize quantizer(.value({{28{value[35]}},value}),.shift(scale),
                .result(quant_words[(qr*4+qc)*16+:16]));
        end
    end endgenerate
''' + text[stop:]
    text = replace(text, '.write_address({tile,lane[3:1]})', '.write_address({tile,lane[3:2]})')
    text = text.replace("lane[3:1]==3'(jp_column/2)", "lane[3:2]==2'(jp_column/4)")
    text = replace(text, '        wire mac_update=(state==B_MAC)&&row_valid;', '''        wire signed [31:0] seed_bias=ap_er_reseed?
            q16_seed_shadow[jp_column/2][(jp_column%2)*32+:32]:bias_rdata[(jp_column%2)*32+:32];
        wire signed [7:0] seed_shift=ap_er_reseed?
            q16_seed_shadow[jp_column/2][64+(jp_column%2)*8+:8]:jp_shift_return[(jp_column%2)*8+:8];
        wire mac_update=(state==B_MAC)&&row_valid;''')
    text = replace(text, "36'($signed(bias_pair[(jp_column%2)*64+:64]))", "36'(seed_bias)")
    text = replace(text, "$signed(jp_shift_return[(jp_column%2)*8+:8])", "seed_shift")
    if pf2:
        text = replace(text, '    wire prefetch=(state==B_FILL)', '''    wire pf2_request=jp_quant_commit&&(tile<15)&&(lane>=8);
    wire pf2_capture=pf2_request&&(lane==12);
    wire prefetch=pf2_request||(state==B_FILL)''')
        text = replace(text, 'wire capture_operands=(state==B_FILL)', 'wire capture_operands=pf2_capture||(state==B_FILL)')
        text = replace(text, "wire [5:0] request_inner=(state==B_FILL)", "wire [5:0] request_inner=pf2_request?{5'd0,lane[2]}:(state==B_FILL)")
        text = replace(text, 'ap_gray6(request_inner),tile}', "ap_gray6(request_inner),(pf2_request?tile+4'd1:tile)}")
        text = replace(text, "else if(tile<15)begin tile<=tile+1'b1;inner<=0;chunk<=0;state<=A_REQ;end",
                             "else if(tile<15)begin tile<=tile+1'b1;inner<=0;chunk<=0;state<=B_MAC;end")
    else:
        text = replace(text, '    wire prefetch=', "    wire pf2_capture=1'b0;\n    wire prefetch=")
    return text


def queue(text):
    text = replace(text, 'input wire [6:0] write_address', 'input wire [5:0] write_address')
    text = replace(text, 'input wire [127:0] write_words', 'input wire [255:0] write_words')
    text = replace(text, '    reg pending_generation,pending_parity;', '    reg [1:0] pending_column;')
    text = replace(text, '    wire issue=space!=0&&(next_item<16\'d25344)&&(generation_state[issue_generation]==READY);',
                   """    wire want_issue=space!=0&&(next_item<16'd25344)&&(generation_state[issue_generation]==READY);
    wire blocked_read=want_issue&&commit&&(3'(issue_row)<valid_rows);
    wire issue=want_issue&&!blocked_read;""")
    start = text.index('    wire [255:0] memory_data;')
    stop = text.index('    generate for(genvar slot=',start)
    text = text[:start] + '''    wire [255:0] memory_data;
    wire [1:0] next_column=next_item[1:0]+2'd1;
    generate for(genvar bank=0;bank<16;bank=bank+1)begin: row_stash
        localparam integer ROW=bank/4, COLUMN=bank%4;
        wire write_en=commit&&(3'(ROW)<valid_rows);
        wire read_en=issue&&(issue_row==2'(ROW))&&
                     ((next_item[1:0]==2'(COLUMN))||(issue_pair&&(next_column==2'(COLUMN))));
        wire wrap=issue_pair&&(next_item[1:0]==2'd3)&&(COLUMN==0);
        wire [5:0] read_quartet=next_item[7:2]+6'(wrap);
        wire [6:0] address=write_en?{compute_generation,write_address}:{issue_generation,read_quartet};
        wire memory_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(write_en||read_en),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(write_en||read_en),.we(write_en),
            .addr(address),.wdata(write_words[bank*16+:16]),.rdata(memory_data[bank*16+:16]));
    end endgenerate

    wire [63:0] returned_row=memory_data[pending_row*64+:64];
    wire [1:0] pending_high_column=pending_column+2'd1;
    wire [1:0] fill_count=pending_count;
    wire [15:0] fill_low=returned_row[pending_column*16+:16];
    wire [15:0] fill_high=returned_row[pending_high_column*16+:16];
''' + text[stop:]
    text = replace(text, 'pending_generation<=0;pending_row<=0;pending_parity<=0;', 'pending_row<=0;pending_column<=0;')
    text = replace(text, '            pending_generation<=issue_generation;\n', '')
    return replace(text, 'pending_parity<=next_item[0];', 'pending_column<=next_item[1:0];')


def bench(text, core):
    text = replace(text, 'ap_push_words=ap_push_words+2*', 'ap_push_words=ap_push_words+4*')
    text = replace(text, "ap_pair_pushes=ap_pair_pushes+int'(", "ap_pair_pushes=ap_pair_pushes+2*int'(")
    text = replace(text, 'ap_reseed_pairs=ap_reseed_pairs+1;', 'ap_reseed_pairs=ap_reseed_pairs+2;')
    text = replace(text, "if(1'b0)ap_shadow_captures=ap_shadow_captures+1;",
                   'if('+core+'.q16_shadow_capture)ap_shadow_captures=ap_shadow_captures+1;')
    start=text.index('    integer jp_return_tile=')
    stop=text.index('`endif',start)
    next_monitor=text.index('    integer wen_root_edges=',start)
    stop=min(stop,next_monitor)
    text=text[:start]+'''
    reg [7:0] q16_observed_mask=0;
    reg [79:0] q16_observed_return[0:7];
    reg [3:0] q16_observed_tile[0:7];
    reg q16_return_valid=0;
    reg [3:0] q16_return_tile;
    reg [2:0] q16_return_pair;
    wire [2:0] q16_consume_pair={@C@.lane[3:2],1'b0};
    always @(posedge @C@.clk or negedge @C@.rst_n)begin
        if(!@C@.rst_n)begin q16_observed_mask=0;q16_return_valid=0;end
        else if(@C@.layer_start_valid&&@C@.layer_start_ready)begin
            q16_observed_mask=0;q16_return_valid=0;
        end else begin
            if(@C@.q16_shadow_capture)begin
                if(!q16_return_valid||q16_return_pair!=@C@.inner[2:0]||q16_observed_mask[q16_return_pair])
                    $fatal(1,"Q16_SHADOW_CAPTURE_IDENTITY");
                q16_observed_return[q16_return_pair]={@C@.jp_shift_return,@C@.bias_rdata};
                q16_observed_tile[q16_return_pair]=q16_return_tile;
                q16_observed_mask[q16_return_pair]=1;
            end
            q16_return_valid=@C@.ap_er_request;
            if(@C@.ap_er_request)begin
                q16_return_pair=@C@.ap_er_request_pair;
                q16_return_tile=@C@.ap_er_target_tile;
            end
            if(@C@.ap_er_reseed)begin
                for(integer q16_i=0;q16_i<2;q16_i=q16_i+1)begin
                    if(!q16_observed_mask[q16_consume_pair+q16_i]||
                        q16_observed_tile[q16_consume_pair+q16_i]!=@C@.ap_er_target_tile||
                        @C@.q16_seed_shadow[q16_consume_pair+q16_i]!==q16_observed_return[q16_consume_pair+q16_i])
                        $fatal(1,"Q16_SHADOW_SEED_IDENTITY");
                    q16_observed_mask[q16_consume_pair+q16_i]=0;
                end
            end
        end
    end
'''.replace('@C@',core)+text[stop:]
    original='shift_at_seed=$signed('+core+'.jp_shift_return[(lane_id%2)*8+:8]);'
    text=replace(text,original,'shift_at_seed='+core+'.ap_er_reseed?'
        '$signed(q16_observed_return[(lane_id%16)/2][64+(lane_id%2)*8+:8]):'
        '$signed('+core+'.jp_shift_return[(lane_id%2)*8+:8]);')
    marker = '    integer ap_push_cycles=0,'
    index = text.index(marker)
    monitor = '''
    integer q16_wrap_pairs=0,q16_read_pauses=0,q16_pf2_handoffs=0;
    always @(posedge system_clk) begin
        if(!rst_n || (@C@.layer_start_valid&&@C@.layer_start_ready)) begin
            q16_wrap_pairs=0;q16_read_pauses=0;q16_pf2_handoffs=0;
        end else begin
            if(@C@.output_queue.issue_pair&&@C@.output_queue.next_item[1:0]==3)
                q16_wrap_pairs=q16_wrap_pairs+1;
            if(@C@.output_queue.blocked_read)q16_read_pauses=q16_read_pauses+1;
            if(@C@.pf2_capture)q16_pf2_handoffs=q16_pf2_handoffs+1;
        end
    end
'''.replace('@C@',core)
    if core=='dut.core':
        monitor=monitor.replace('system_clk','clk')
    text=text[:index]+monitor+text[index:]
    index=text.index('$display("LOGIC_POWER_COMPUTE_COUNTS')
    text=text[:index]+'''$display("Q16_COUNTS wrap_pairs=%0d read_pauses=%0d pf2_handoffs=%0d",q16_wrap_pairs,q16_read_pauses,q16_pf2_handoffs);
        '''+text[index:]
    return text


def materialize():
    selection = json.loads((REPORT/'model-selection.json').read_text())
    mode = selection['selected']
    if not selection['passed'] or mode not in ('Q16','Q16+PF2'):
        raise RuntimeError('No model winner eligible for hardware')
    baseline = ROOT/'constraints/ffn_selected.json'
    cfg = json.loads(baseline.read_text())
    assert cfg['variant'] == PARENT
    (REPORT/'baseline-selected.json').write_bytes(baseline.read_bytes())
    parent = ROOT/cfg['source_snapshot']
    shutil.copytree(parent,SOURCE,dirs_exist_ok=True)
    for file, fn in [('kwt_encoder.sv',lambda text: encoder(text,mode=='Q16+PF2')),
                     ('kwt_joint_output_queue.sv',queue)]:
        path=Path('encoder')/file
        (SOURCE/path).write_text(fn((parent/path).read_text()),newline='\n')
    old = SOC.with_name(PARENT)
    SOC.mkdir(exist_ok=True)
    def specialize(text):
        return text.replace(cfg['firmware'],'@FROZEN_FIRMWARE@').replace(PARENT,NAME).replace('@FROZEN_FIRMWARE@',cfg['firmware'])
    for path in old.iterdir():
        if not path.is_file() or path.suffix not in ('.sv','.v','.svh','.f','.json','.sh'):
            continue
        if path.name in ('gate_tb.sv','gate_files.f','compile_gate.sh'):
            continue
        text=specialize(path.read_text())
        if path.name=='complete_soc_tb.sv':
            text=bench(text,CORE)
        elif path.name=='configuration.json':
            data=json.loads(text)
            data.update(requantizers=16,retirement=mode)
            text=json.dumps(data,indent=2)+'\n'
        (SOC/path.name).write_text(text,newline='\n')
    eda=SOC/'eda'
    eda.mkdir(exist_ok=True)
    for path in (old/'eda').glob('*.tcl'):
        if path.name!='pr1_assessment.tcl':
            (eda/path.name).write_text(specialize(path.read_text()),newline='\n')
    shutil.copytree(old/'packed_inputs',SOC/'packed_inputs',dirs_exist_ok=True)
    manifest=json.loads((ROOT/cfg['adaptive_manifest']).read_text())
    manifest.update(variant=NAME,parent_variant=PARENT,purpose='experiment',retirement=mode,
                    parent=dict(variant=PARENT,configuration=cfg,firmware=cfg['firmware'],
                                source_snapshot=cfg['source_snapshot'],profile=cfg['implementation']))
    manifest['changes'].update(requantizers=16,pf2=mode=='Q16+PF2')
    manifest['hardware']+=['Q16']+(['PF2'] if mode=='Q16+PF2' else [])
    folder=ROOT/'constraints'/NAME/'candidates'
    folder.mkdir(parents=True,exist_ok=True)
    (folder/(NAME+'.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    RTL.mkdir(exist_ok=True)
    previous=(RTL.with_name(PARENT)/'loading_dma_tb.sv').read_text()
    (RTL/'loading_dma_tb.sv').write_text(bench(previous,'dut.core'),newline='\n')


def develop():
    import re
    q8.SOURCE,q8.RTL_TEST,q8.REPORT=SOURCE,RTL,REPORT
    q8.develop()
    selection=json.loads((REPORT/'model-selection.json').read_text())
    want_pf2=375 if selection['selected']=='Q16+PF2' else 0
    scenarios=('actual12','mixed_paused','single')
    coverage={}
    for scenario in scenarios:
        log=(REPORT/('local-'+scenario+'.log')).read_text()
        counts=[list(map(int,row)) for row in re.findall(r'Q16_COUNTS wrap_pairs=(\d+) read_pauses=(\d+) pf2_handoffs=(\d+)',log)]
        assert len(counts)==12 and all(row[2]==want_pf2 for row in counts)
        coverage[scenario]=counts
    assert all(row[0]>0 for row in coverage['mixed_paused'])
    path=REPORT/'local-acceptance.json'
    result=json.loads(path.read_text())
    result.update(output_requantizers=16,counters=coverage,selected_model=selection['selected'])
    path.write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':
    {'materialize':materialize,'develop':develop}[sys.argv[1]]()
