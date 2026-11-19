"""Generate the selected four-quartet implementation from the accepted I snapshot."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/s1_bank_overlap'))
from build_overlap import copy_tree, replace, write_text

PARENT = 'ffn_s1_bank_I'
EXPERIMENT = ROOT / 'reports/optimization/ffn_i_wavefront'


def name(mode):
    return 'ffn_iw_' + mode


def compute(source, fused):
    source = replace(source, '    reg [3:0] tile;\n    reg [3:0] lane;\n', '')
    source = replace(source, '    reg [5:0] inner;\n', '')
    a = source.index('    wire emission=state==EMIT;')
    b = source.index('    wire [15:0] bias_address=', a)
    source = source[:a] + '''    localparam IW_FUSED=@FUSED@;
    // Command fields are MAC valid, emit valid, tile and inner. The four
    // quartets see the same schedule, one edge apart. Read -> capture -> MAC.
    reg [3:0] iw_request_tile;
    reg [6:0] iw_request_inner;
    reg iw_request_done;
    reg [11:0] iw_pipe[0:4];
    wire iw_first=(state==A_REQ)&&input_complete;
    wire iw_second=state==B_FILL;
    wire iw_run=(state==B_MAC)&&!iw_request_done;
    wire iw_issue_mac=iw_first||iw_second||(iw_run&&iw_request_inner<64);
    wire iw_issue_emit=iw_run&&(iw_request_inner==64||
        (IW_FUSED&&iw_request_inner==0&&iw_request_tile!=0));
    wire [3:0] iw_issue_tile=(iw_first||iw_second)?4'd0:iw_request_tile;
    wire [5:0] request_inner=iw_first?6'd0:iw_second?6'd1:iw_request_inner[5:0];
    wire [11:0] iw_issue={iw_issue_mac,iw_issue_emit,iw_issue_tile,request_inner};
    wire [3:0] iw_mac_valid,iw_emit_valid,iw_capture;
    wire [3:0] iw_mac_tile[0:3],iw_emit_tile[0:3];
    wire [5:0] iw_mac_inner[0:3];
    wire [3:0] iw_weight_read;
    wire [12:0] iw_weight_address[0:3];
    wire [5:0] inner=iw_mac_inner[0];
    wire [3:0] tile=iw_emit_valid[0]?iw_emit_tile[0]:iw_emit_valid[1]?iw_emit_tile[1]:
                    iw_emit_valid[2]?iw_emit_tile[2]:iw_emit_valid[3]?iw_emit_tile[3]:iw_mac_tile[0];
    wire [3:0] lane={iw_emit_valid[3]||iw_emit_valid[2],iw_emit_valid[3]||iw_emit_valid[1],2'b00};
    wire emission=|iw_emit_valid;
    wire jp_quant_commit=emission;
    wire fifo_push=jp_quant_commit;
    wire output_generation_empty;
    wire output_reserve=(state==WAIT_INPUT)&&input_complete&&output_generation_empty;
    wire output_group_done=iw_emit_valid[3]&&(iw_emit_tile[3]==15);
    reg ap_er_next_seed_ready;
    wire ap_er_seed_wait=(state==MAC_INIT)&&ap_er_next_seed_ready;
    wire ap_er_has_next=(row<96)||(iw_mac_tile[0]<15);
    wire ap_er_first_request=iw_mac_valid[0]&&(inner==55)&&ap_er_has_next;
    wire ap_er_next_request=iw_mac_valid[0]&&(inner>=56)&&(inner<63)&&ap_er_has_next;
    wire ap_er_request=ap_er_first_request||ap_er_next_request;
    wire ap_er_reseed=jp_quant_commit&&((row<96)||(tile<15));
    wire [3:0] ap_er_target_tile=ap_er_reseed?tile+4'd1:iw_mac_tile[0]+4'd1;
    wire [2:0] ap_er_request_pair=inner[2:0]+3'd1;
    wire [3:0] ap_bias_tile=ap_er_request?ap_er_target_tile:4'd0;
    wire [2:0] ap_bias_pair=ap_er_request?ap_er_request_pair:chunk;
    wire bias_request=(state==BIAS_REQ)||ap_er_request;
    wire bias_capture=state==BIAS_CAP;
    wire pf2_capture=iw_emit_valid[3]&&(iw_emit_tile[3]<15);
    wire [MAC_LANES-1:0] jp_seed_mask,jp_mac_mask,jp_quant_mask;
    function automatic [5:0] ap_gray6(input [5:0] value);
        begin ap_gray6=value^(value>>1);end
    endfunction
    genvar wave_q;
    generate for(wave_q=0;wave_q<4;wave_q=wave_q+1)begin: wave_schedule
        wire [11:0] req;
        if(wave_q==0)assign req=iw_issue;
        else assign req=iw_pipe[wave_q-1];
        wire [11:0] execute=iw_pipe[wave_q+1];
        assign iw_weight_read[wave_q]=req[11];
        assign iw_weight_address[wave_q]={3'b000,ap_gray6(req[5:0]),req[9:6]};
        assign iw_capture[wave_q]=iw_pipe[wave_q][11];
        assign iw_mac_valid[wave_q]=execute[11];
        assign iw_emit_valid[wave_q]=execute[10];
        assign iw_mac_tile[wave_q]=execute[9:6];
        assign iw_mac_inner[wave_q]=execute[5:0];
        assign iw_emit_tile[wave_q]=execute[11]?execute[9:6]-4'd1:execute[9:6];
    end endgenerate
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            iw_request_tile<=0;iw_request_inner<=0;iw_request_done<=0;
            ap_er_next_seed_ready<=0;
            for(integer d=0;d<5;d=d+1)iw_pipe[d]<=0;
        end else begin
            iw_pipe[0]<=iw_issue;
            for(integer d=1;d<5;d=d+1)iw_pipe[d]<=iw_pipe[d-1];
            if(layer_start_valid&&layer_start_ready)ap_er_next_seed_ready<=0;
            else if(ap_er_seed_wait)ap_er_next_seed_ready<=0;
            else if(output_group_done&&row<96)ap_er_next_seed_ready<=1;
            if(iw_second)begin
                iw_request_tile<=0;iw_request_inner<=2;iw_request_done<=0;
            end else if(iw_run)begin
                if(iw_request_inner==64)begin
                    if(iw_request_tile==15)iw_request_done<=1;
                    else begin iw_request_tile<=iw_request_tile+4'd1;iw_request_inner<=0;end
                end else if(IW_FUSED&&iw_request_inner==63&&iw_request_tile<15)begin
                    iw_request_tile<=iw_request_tile+4'd1;iw_request_inner<=0;
                end else iw_request_inner<=iw_request_inner+7'd1;
            end
        end
    end
'''.replace('@FUSED@', "1'b1" if fused else "1'b0") + source[b:]
    a = source.index('    wire ap_input_read=')
    b = source.index('    generate for(genvar ap_row=', a)
    source = source[:a] + '''    wire ap_input_read=iw_issue_mac;
    wire [63:0] ap_input_rdata;
    reg [255:0] jp_input_return;
    reg [16*LANES-1:0] operand_weight;
    generate for(genvar qw=0;qw<4;qw=qw+1)begin: wave_weight_stage
        wire operand_weight_clk;
        kwt_ffn_clock_gate weight_stage_gate(.clk(clk),.enable(iw_capture[qw]),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(operand_weight_clk));
        always @(posedge operand_weight_clk)if(iw_capture[qw])operand_weight[qw*64+:64]<=pm_rdata[qw*64+:64];
    end endgenerate
''' + source[b:]
    source = replace(source, 'cp_copy<2;', 'cp_copy<4;')
    source = replace(source, 'wire capture_row=capture_operands&&row_valid;', '''wire capture_row=iw_capture[cp_copy]&&row_valid;
            wire [15:0] capture_value;
            if(cp_copy==0)assign capture_value=ap_input_rdata[ap_row*16+:16];
            else assign capture_value=jp_input_return[(ap_row*4+cp_copy-1)*16+:16];''')
    source = replace(source, 'jp_input_return[(ap_row*2+cp_copy)*16+:16]<=ap_input_rdata[ap_row*16+:16];',
                     'jp_input_return[(ap_row*4+cp_copy)*16+:16]<=capture_value;')
    source = replace(source, 'q16_shadow_capture=(state==B_MAC)', 'q16_shadow_capture=iw_mac_valid[0]')
    source = replace(source, 'wire mac_update=(state==B_MAC)&&row_valid;',
                     'wire mac_update=iw_mac_valid[jp_column/4]&&row_valid;')
    source = replace(source, '(jp_row*2+jp_column/8)*16', '(jp_row*4+jp_column/4)*16')
    source = replace(source, '''            if(seed_update)accumulator[jp_lane]<=36'(seed_bias);
            else if(mac_update)accumulator[jp_lane]<=accumulator[jp_lane]+36'(activation*weight_value);''',
                     '''            if(mac_update)accumulator[jp_lane]<=
                (seed_update?36'(seed_bias):accumulator[jp_lane])+36'(activation*weight_value);
            else if(seed_update)accumulator[jp_lane]<=36'(seed_bias);''' if fused else
                     '''            if(seed_update)accumulator[jp_lane]<=36'(seed_bias);
            else if(mac_update)accumulator[jp_lane]<=accumulator[jp_lane]+36'(activation*weight_value);''')
    a = source.index('        if(!USE_ROW_CACHE&&((state==A_REQ)')
    b = source.index('        if(bias_request) begin', a)
    source = source[:a] + '''        for(b=0;b<LANES;b=b+1)if(iw_weight_read[b/4])begin
            pm_en[b]=1;pm_addr[b*13+:13]=iw_weight_address[b/4];
        end
''' + source[b:]
    source = replace(source, 'row<=0;tile<=0;lane<=0;inner<=0;chunk<=0;item<=0;', 'row<=0;chunk<=0;item<=0;')
    source = replace(source, 'row<=0;tile<=0;item<=0;lane<=0;inner<=0;state<=WAIT_INPUT;',
                     'row<=0;item<=0;state<=WAIT_INPUT;')
    source = replace(source, 'if(ap_er_next_seed_ready)begin inner<=0;state<=A_REQ;end else',
                     'if(ap_er_next_seed_ready)state<=A_REQ;else')
    source = replace(source, 'if(chunk==7)begin inner<=0;state<=A_REQ;end else', 'if(chunk==7)state<=A_REQ;else')
    a = source.index('                B_MAC:if(inner==63)')
    b = source.index('                ADVANCE:', a)
    source = source[:a] + '                B_MAC:if(output_group_done)state<=ADVANCE;\n' + source[b:]
    source = replace(source, 'tile<=0;lane<=0;state<=WAIT_INPUT;', 'state<=WAIT_INPUT;')
    return source


def tail(source):
    source = replace(source, '    wire want_issue=space!=0&&(next_item<16\'d25344)&&(generation_state[issue_generation]==READY);',
                     '''    reg [6:0] iw_committed_quartets;
    wire iw_tail_fill=(next_item[14:10]==5'd24)&&(issue_row==0)&&(generation_state[0]==FILL);
    wire [8:0] iw_committed_columns={iw_committed_quartets,2'b00};
    wire iw_tail_available=iw_tail_fill&&({1'b0,next_item[7:0]}<iw_committed_columns);
    wire iw_tail_pair=({1'b0,next_item[7:0]}+9'd1)<iw_committed_columns;
    wire want_issue=space!=0&&(next_item<16'd25344)&&
        ((generation_state[issue_generation]==READY)||iw_tail_available);
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)iw_committed_quartets<=0;
        else if(restart||reserve)iw_committed_quartets<=0;
        else if(commit&&valid_rows==3)iw_committed_quartets<={1'b0,write_address}+7'd1;
    end''')
    return replace(source, "issue_pair=issue&&(space>=2)&&(next_item[7:0]!=8'hff);",
                   "issue_pair=issue&&(space>=2)&&(next_item[7:0]!=8'hff)&&(!iw_tail_fill||iw_tail_pair);")


def observers(source, core):
    # The old broadcast observer becomes a four-stage tap observer.
    a = source.index('    generate for(genvar cp_row=0;cp_row<4;cp_row=cp_row+1)begin: r3o_operands')
    b = source.index('    end endgenerate', a)+len('    end endgenerate')
    source = source[:a] + '''    generate for(genvar cp_row=0;cp_row<4;cp_row=cp_row+1)begin: wave_operand_row
        for(genvar cp_copy=0;cp_copy<4;cp_copy=cp_copy+1)begin: wave_operand_tap
            reg captured=0;
            reg [15:0] expected_operand;
            wire [15:0] value_before;
            if(cp_copy==0)assign value_before=@CORE@.ap_input_rdata[cp_row*16+:16];
            else assign value_before=@CORE@.jp_input_return[(cp_row*4+cp_copy-1)*16+:16];
            always @(posedge @CORE@.clk)begin
                captured<=@CORE@.rst_n&&@CORE@.iw_capture[cp_copy]&&(3'(cp_row)<@CORE@.block_rows);
                if(@CORE@.iw_capture[cp_copy])expected_operand<=value_before;
            end
            always @(negedge @CORE@.clk)if(@CORE@.rst_n&&captured)
                if(@CORE@.jp_input_return[(cp_row*4+cp_copy)*16+:16]!==expected_operand)
                    $fatal(1,"WAVEFRONT registered operand differs");
        end
    end endgenerate'''.replace('@CORE@',core) + source[b:]
    source = replace(source, 'begin seeded=1;macs=0;end',
                     'begin seeded=1;macs=int\'(' + core + '.jp_mac_mask[car_lane]);end')
    source = source.replace('('+core+'.state==7)||('+core+'.state==9)', '(|'+core+'.iw_mac_valid)')
    source = source.replace(core+'.state==7||'+core+'.state==9', '(|'+core+'.iw_mac_valid)')
    return source


def materialize(mode, local_bench=True):
    variant = name(mode)
    report = ROOT / 'reports/optimization' / variant
    report.mkdir(parents=True, exist_ok=True)
    selected = ROOT / 'constraints/ffn_selected.json'
    config = json.loads(selected.read_text())
    assert config['variant'] == PARENT
    (report/'baseline-selected.json').write_bytes(selected.read_bytes())
    root = ROOT / 'build/optimization'
    source = root / 'rtl_sources' / variant
    out = root / 'complete_soc' / variant
    out.mkdir(parents=True, exist_ok=True)
    copy_tree(ROOT / config['source_snapshot'], source)
    core = source/'encoder/kwt_encoder.sv'
    write_text(core, compute(core.read_text(), mode!='W4'))
    if mode=='W4Z_FT':
        queue = source/'encoder/kwt_joint_output_queue.sv'
        write_text(queue, tail(queue.read_text()))
    baseline = root/'complete_soc'/PARENT
    for p in baseline.iterdir():
        if not p.is_file() or p.suffix not in ('.sv','.v','.svh','.f','.json','.sh'):
            continue
        if p.name in ('gate_tb.sv','gate_files.f','compile_gate.sh'):
            continue
        text = p.read_text().replace(PARENT,variant)
        if p.name=='complete_soc_tb.sv':
            text = observers(text,config['core_path'])
        elif p.name=='configuration.json':
            metadata = json.loads(text)
            metadata['wavefront'] = mode
            text = json.dumps(metadata,indent=2)+'\n'
        write_text(out/p.name,text)
    (out/'eda').mkdir(exist_ok=True)
    for p in (baseline/'eda').glob('*.tcl'):
        if p.name!='pr1_assessment.tcl':
            write_text(out/'eda'/p.name,p.read_text().replace(PARENT,variant))
    copy_tree(baseline/'packed_inputs',out/'packed_inputs')
    manifest=json.loads((ROOT/config['adaptive_manifest']).read_text())
    manifest.update(variant=variant,parent_variant=PARENT,purpose='experiment',selected_model=mode,
                    parent=dict(variant=PARENT,configuration=config,firmware=config['firmware'],
                                source_snapshot=config['source_snapshot'],profile=config['implementation']))
    manifest['changes'].update(wavefront=mode)
    manifest['hardware'].append(mode)
    folder=ROOT/'constraints'/variant/'candidates'
    folder.mkdir(parents=True,exist_ok=True)
    write_text(folder/(variant+'.json'),json.dumps(manifest,indent=2)+'\n')
    rtl = root/'rtl'/variant
    rtl.mkdir(parents=True,exist_ok=True)
    if local_bench:
        tb=(root/'rtl/ffn_q16_staged/loading_dma_tb.sv').read_text()
        write_text(rtl/'loading_dma_tb.sv',observers(tb,'dut.core'))
    return source, rtl, report


def develop(mode):
    sys.path.insert(0,str(ROOT/'scripts/r4f2_q8'))
    import build_q8
    variant=name(mode)
    build_q8.SOURCE=ROOT/'build/optimization/rtl_sources'/variant
    build_q8.RTL_TEST=ROOT/'build/optimization/rtl'/variant
    build_q8.REPORT=ROOT/'reports/optimization'/variant
    build_q8.develop()
    path=build_q8.REPORT/'local-acceptance.json'
    result=json.loads(path.read_text())
    soc=ROOT/'build/optimization/complete_soc'
    shared='kwt_shared_dma_icb_sm40.sv'
    assert (soc/variant/shared).read_bytes() == (soc/PARENT/shared).read_bytes()
    prior=ROOT/'reports/optimization'/PARENT/'local-acceptance.json'
    assert json.loads(prior.read_text())['shared_protocol_passed']
    result.update(output_requantizers=16,wavefront=mode,shared_protocol_passed=True,
                  shared_protocol_reused_from=PARENT)
    write_text(path,json.dumps(result,indent=2)+'\n')


if __name__=='__main__':
    action=sys.argv[1]
    mode=sys.argv[2] if len(sys.argv)>2 else json.loads((EXPERIMENT/'model-selection.json').read_text())['winner']
    assert mode in ('W4','W4Z','W4Z_FT')
    {'materialize':materialize,'develop':develop,
     'native_materialize':lambda m:materialize(m,False)}[action](mode)
