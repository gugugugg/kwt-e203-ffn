"""Materialize the sole model-selected K8-3 implementation on frozen T+R+B."""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
NAME, PARENT = 'ffn_trb_k8', 'ffn_sg_reuse'
REPORT = EXPERIMENT = ROOT / 'reports/optimization' / NAME
BUILD = ROOT / 'build/optimization'
SOURCE = BUILD / 'rtl_sources' / NAME
SOC = BUILD / 'complete_soc' / NAME
RTL_TEST = BUILD / 'rtl' / NAME
spec = importlib.util.spec_from_file_location('trb_builder', ROOT / 'scripts/sg_reuse/build.py')
trb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trb)
copy_tree, replace, write_text = trb.copy_tree, trb.replace, trb.write_text


def compute(src):
    src = replace(src, '    reg signed [7:0] shifts[0:MAC_LANES-1];', '''    reg signed [7:0] column_shift[0:MAC_COLUMNS-1];
    wire signed [7:0] shifts[0:MAC_LANES-1];''')
    src = replace(src, '    reg [13:0] iw_pipe[0:4];', '    reg [14:0] iw_pipe[0:4];')
    src = replace(src, '    wire wp_capture=wp_capture_token[13];', '''    function automatic k8_tile(input [3:0] t);
        k8_tile=(t>=7)&&(t<=14);
    endfunction
    wire wp_capture=wp_capture_token[13];
    wire k8_read=wp_issue&&wp_generation&&k8_tile(wp_tile);
    wire k8_capture=wp_capture&&wp_capture_token[6]&&k8_tile(wp_capture_token[12:9]);
    wire k8_mac=wp_execute_token[13]&&wp_execute_token[6]&&k8_tile(wp_execute_token[12:9]);
    reg k8_write;
    reg [1:0] k8_row,k8_quartet;
    reg [3:0] k8_write_tile;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin k8_write<=0;k8_row<=0;k8_quartet<=0;k8_write_tile<=0;end
        else if(!wp_boot)k8_write<=0;
        else if(wp_emit_token[7]&&wp_emit_token[6]&&k8_tile(wp_emit_token[5:2]))begin
            k8_write<=1;k8_row<=0;k8_quartet<=wp_emit_token[1:0];k8_write_tile<=wp_emit_token[5:2];
        end else if(k8_write)begin
            if(k8_row==3)k8_write<=0;
            else k8_row<=k8_row+1'b1;
        end
    end''')
    src = replace(src, '    wire [3:0] retire_tile=(iw_request_inner==64)?iw_request_tile:iw_request_tile-4\'d1;', '''    wire [6:0] request_row=row+(iw_join_inflight?7'd4:7'd0);
    wire k8_skip=(request_row==8)&&(iw_request_tile==6);
    wire k8_emit_skip=(request_row==8)&&(iw_request_tile==15)&&(iw_request_inner==0);
    wire [3:0] retire_tile=k8_emit_skip?4'd6:
        (iw_request_inner==64)?iw_request_tile:iw_request_tile-4'd1;''')
    src = replace(src, '    wire [13:0] iw_issue={iw_request_tail,iw_request_generation,',
                  '    wire [14:0] iw_issue={k8_emit_skip,iw_request_tail,iw_request_generation,')
    src = replace(src, '    wire [3:0] ap_er_target_tile=ap_er_reseed?tile+4\'d1:iw_mac_tile[0]+4\'d1;', '''    wire [3:0] ap_er_target_tile=ap_er_reseed?
        ((row==8&&tile==6)?4'd15:tile+4'd1):
        ((row==8&&iw_mac_tile[0]==6)?4'd15:iw_mac_tile[0]+4'd1);''')
    src = replace(src, '        wire [13:0] req;', '        wire [14:0] req;')
    src = replace(src, '        wire [13:0] execute=iw_pipe[wave_q+1];', '        wire [14:0] execute=iw_pipe[wave_q+1];')
    src = replace(src, "execute[11]?execute[9:6]-4'd1:execute[9:6]", "execute[14]?4'd6:(execute[11]?execute[9:6]-4'd1:execute[9:6])")
    src = replace(src, """                end else if(IW_FUSED&&iw_request_inner==63&&(iw_request_tile<15||iw_join))begin
                    iw_request_tile<=iw_request_tile+4'd1;iw_request_inner<=0;""", """                end else if(IW_FUSED&&iw_request_inner==63&&(iw_request_tile<15||iw_join))begin
                    iw_request_tile<=k8_skip?4'd15:iw_request_tile+4'd1;iw_request_inner<=0;""")
    src = replace(src, '    wire [63:0] ap_input_rdata;', '''    wire input_request_upper=!wp_boot&&(request_row==8||request_row==12);
    wire [63:0] ap_input_rdata;''')
    src = replace(src, """            wire read_enable=ap_input_read&&read_row&&(input_request_generation==1'(gen));""", """            wire read_enable=(ap_input_read&&read_row&&(input_request_generation==1'(gen)))||
                             (gen==0&&k8_read);""")
    src = replace(src, '            wire memory_clk;\n            kwt_ffn_clock_gate gate(.clk(clk),.enable(memory_enable),', '''            wire upper=write_enable?(high_write?(input_count>=511&&input_count<1023):
                                              (input_count>=512&&input_count<1024)):
                (wp_boot?gen==0&&k8_read:input_request_upper);
            wire memory_clk;
            kwt_ffn_clock_gate gate(.clk(clk),.enable(memory_enable),''')
    src = replace(src, ".addr({1'b0,offset}),.wdata(high_write?load_high:load_data)", ".addr({upper,offset}),.wdata(high_write?load_high:load_data)")
    src = replace(src, """            wire capture_row=iw_capture[cp_copy]&&((ap_row!=3)||!iw_capture_tail[cp_copy]);""", """            wire aux_capture=k8_capture&&wp_capture_token[8:7]==2'(cp_copy^2);
            wire capture_row=aux_capture||(iw_capture[cp_copy]&&((ap_row!=3)||!iw_capture_tail[cp_copy]));""")
    src = replace(src, '''            if(cp_copy==0)assign capture_value=ap_input_rdata[ap_row*16+:16];
            else assign capture_value=wp_boot?ap_input_rdata[ap_row*16+:16]:jp_input_return[(ap_row*4+cp_copy-1)*16+:16];''', '''            if(cp_copy==0)assign capture_value=aux_capture?generation_data[15:0]:ap_input_rdata[ap_row*16+:16];
            else assign capture_value=aux_capture?generation_data[15:0]:
                wp_boot?ap_input_rdata[ap_row*16+:16]:jp_input_return[(ap_row*4+cp_copy-1)*16+:16];''')
    src = replace(src, '            wire active=jp_quant_commit&&(3\'(qr)<quant_valid_rows);', '''            wire active=(jp_quant_commit&&(3'(qr)<quant_valid_rows))||(k8_write&&k8_row==2'(qr));
            wire [1:0] quant_column_group=k8_write?(k8_quartet^2'd2):lane[3:2];''')
    src = replace(src, "assign select_quartet[q]=active&&(lane[3:2]==2'(q));", "assign select_quartet[q]=active&&(quant_column_group==2'(q));")
    src = replace(src, '        .group_done(output_group_done),.commit(jp_quant_commit),.valid_rows(quant_valid_rows),', '''        .group_done(output_group_done),.commit(jp_quant_commit),.valid_rows(quant_valid_rows),
        .scratch_write(k8_write),.scratch_row(k8_row),
        .scratch_address({k8_row,k8_write_tile[2:0]-3'd7,k8_quartet}),''')
    src = replace(src, '''        wire wp_seed=wp_boot&&iw_mac_valid[jp_column/4]&&wp_execute_token[5:0]==0;''', '''        localparam integer aux_source=jp_column^8;
        wire aux_mac=k8_mac&&wp_execute_token[8:7]==2'(aux_source/4);
        wire wp_seed=wp_boot&&(iw_mac_valid[jp_column/4]||aux_mac)&&wp_execute_token[5:0]==0;
        wire [2:0] shadow_index=aux_mac?3'(aux_source/2):3'(jp_column/2);
        assign shifts[jp_lane]=column_shift[jp_column];''')
    src = replace(src, 'q16_seed_shadow[jp_column/2][(jp_column%2)*32+:32]', 'q16_seed_shadow[shadow_index][(jp_column%2)*32+:32]')
    src = replace(src, 'q16_seed_shadow[jp_column/2][64+(jp_column%2)*8+:8]', 'q16_seed_shadow[shadow_index][64+(jp_column%2)*8+:8]')
    src = replace(src, 'wire mac_update=iw_mac_valid[jp_column/4]&&', 'wire mac_update=aux_mac||iw_mac_valid[jp_column/4]&&')
    src = replace(src, "wire quant_commit=jp_quant_commit&&(3'(jp_row)<quant_valid_rows)&&(lane[3:2]==2'(jp_column/4));", '''wire quant_commit=(jp_quant_commit&&(3'(jp_row)<quant_valid_rows)&&(lane[3:2]==2'(jp_column/4)))||
                          (k8_write&&k8_row==2'(jp_row)&&k8_quartet==2'(aux_source/4));''')
    src = replace(src, 'wire signed [15:0] weight_value=$signed(operand_weight[jp_column*16+:16]);', '''wire signed [15:0] weight_value=aux_mac?
            $signed(operand_weight[aux_source*16+:16]):$signed(operand_weight[jp_column*16+:16]);''')
    src = replace(src, '        wire accumulator_clk,shift_register_clk;', '        wire accumulator_clk;')
    src = replace(src, '''            kwt_ffn_clock_gate shift_gate(.clk(clk),.enable(seed_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(shift_register_clk));''', '')
    src = replace(src, '            assign shift_register_clk=jp_mac_lanes[jp_lane-1].shift_register_clk;', '')
    src = replace(src, '''        always @(posedge shift_register_clk)begin
            if(seed_update)shifts[jp_lane]<=seed_shift;
        end''', '''        if(jp_row==0)begin: shared_shift
            wire shift_register_clk;
            if(jp_column%2==0)begin: pair_gate
                kwt_ffn_clock_gate shift_gate(.clk(clk),.enable(seed_update),
                    .test_enable(clock_test_enable||!rst_n),.gated_clk(shift_register_clk));
            end else assign shift_register_clk=jp_mac_lanes[jp_lane-1].shared_shift.shift_register_clk;
            always @(posedge shift_register_clk)if(seed_update)column_shift[jp_column]<=seed_shift;
        end''')
    src = replace(src, '&&(input_count==512);', '&&(input_count==768);')
    src = replace(src, "    wire [13:0] active_input_limit=(layer_request||wp_boot)?14'd512:input_window_limit;", '''    wire [13:0] active_input_limit=layer_request?14'd768:
        wp_boot?(wp_issue&&wp_generation?14'd768:14'd1024):input_window_limit;''')
    return src


def queue(src):
    src = replace(src, '    input wire [2:0] valid_rows,', '''    input wire scratch_write,
    input wire [1:0] scratch_row,
    input wire [6:0] scratch_address,
    input wire [2:0] valid_rows,''')
    src = replace(src, '    reg [1:0] pending_column;', '''    reg [1:0] pending_column;
    reg pending_scratch;''')
    src = replace(src, '    wire transposed_read=next_item[14:11]==0;', '''    wire transposed_read=next_item[14:11]==0;
    wire scratch_read=next_item[14:10]==2&&next_item[7:0]>=112&&next_item[7:0]<240;
    wire scratch_boundary=next_item[14:10]==2&&(next_item[7:0]==111||next_item[7:0]==239);''')
    src = replace(src, '&&(next_item[7:0]!=8\'hff)&&', "&&(next_item[7:0]!=8'hff)&&!scratch_boundary&&")
    src = replace(src, 'wire read_en=issue&&(read_bank_row', 'wire read_en=issue&&!scratch_read&&(read_bank_row')
    src = replace(src, '    wire [63:0] returned_row=memory_data[pending_row*64+:64];', '''    wire [63:0] scratch_data;
    wire [63:0] scratch_words=write_words[scratch_row*64+:64];
    generate for(genvar column=0;column<4;column=column+1)begin: k8_scratch
        wire rd=issue&&scratch_read&&
            (next_item[1:0]==2'(column)||(issue_pair&&next_column==2'(column)));
        wire carry=issue_pair&&next_item[1:0]==3&&column==0;
        wire [4:0] quad=next_item[6:2]-5'd28+5'(carry);
        wire [6:0] address=scratch_write?scratch_address:{issue_row,quad};
        wire memory_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(scratch_write||rd),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(scratch_write||rd),.we(scratch_write),
            .addr(address),.wdata(scratch_words[column*16+:16]),.rdata(scratch_data[column*16+:16]));
    end endgenerate
    wire [63:0] returned_row=pending_scratch?scratch_data:memory_data[pending_row*64+:64];''')
    src = replace(src, 'pending_row<=0;pending_column<=0;', 'pending_row<=0;pending_column<=0;pending_scratch<=0;')
    return replace(src, '            pending_row<=read_bank_row;', '            if(issue)pending_scratch<=scratch_read;\n            pending_row<=read_bank_row;')


def firmware(src):
    start = src.index('    wr_base(base,0x40u,(uint32_t)(uintptr_t)input);wr_base(base,0x44u,256u);')
    end = src.index('    return wait_state(d,64u);', start)
    head = src[start:src.index('    for(unsigned row=0;', start)].replace('256u);', '384u);').replace('ADDR,512', 'ADDR,768')
    return src[:start] + head + '''    rc=transport_load(base,input+12u*32u,128u);if(rc)return rc;
    for(unsigned row=0;row<99;row+=4) {
        unsigned next=row+8;
        if(row>=8&&next<99) {
            unsigned next_rows=(99-next<4)?99-next:4;
            rc=transport_load(base,input+next*32u,next_rows*32u);if(rc)return rc;
        }
        unsigned rows=(99-row<4)?99-row:4;
        rc=transport_output(base,output+row*256u,rows*256u);if(rc)return rc;
    }
''' + src[end:]


def local_bench(src):
    src = replace(src, 'for(integer i=0;i<256;i=i+1)', 'for(integer i=0;i<384;i=i+1)')
    src = replace(src, "write_word(8'h44,256);write_word(8'h48,3)", "write_word(8'h44,384);write_word(8'h48,3)")
    src = replace(src, 'input_block(0,8);', 'input_block(0,12);')
    src = replace(src, '            write_word(8,0);write_word(12,512);', '            write_word(8,0);write_word(12,768);input_block(12,4);')
    src = replace(src, '            if(block_row+8<99)', '            if(block_row>=8&&block_row+8<99)')
    src = replace(src, 'dut.core.q16_seed_shadow[(lane_id%16)/2][64+', 'dut.core.q16_seed_shadow[dut.core.jp_mac_lanes[lane_id].shadow_index][64+')
    return src


def materialize():
    selection = json.loads((REPORT/'model-results.json').read_text())
    assert selection['selected']=='K8-3'
    selected = ROOT/'constraints/ffn_selected.json'
    cfg = json.loads(selected.read_text())
    assert cfg['variant']==PARENT
    (REPORT/'baseline-selected.json').write_bytes(selected.read_bytes())
    trb.NAME, trb.firmware = NAME, firmware
    fw, boot_words = trb.compile_firmware(cfg)
    copy_tree(ROOT/cfg['source_snapshot'], SOURCE)
    for name, edit in (('kwt_encoder.sv',compute),('kwt_joint_output_queue.sv',queue),
                       ('kwt_ld_frontend.sv',lambda s:replace(s,"words==32'd256","words==32'd384"))):
        path=SOURCE/'encoder'/name
        write_text(path, edit(path.read_text()))
    (SOC/'eda').mkdir(parents=True,exist_ok=True)
    parent = BUILD/'complete_soc'/PARENT
    for path in list(parent.iterdir())+list((parent/'eda').glob('*.tcl')):
        if not path.is_file() or path.suffix not in ('.sv','.v','.svh','.f','.json','.sh','.tcl'):
            continue
        if path.name in ('gate_tb.sv','gate_files.f','compile_gate.sh','pr1_assessment.tcl'):
            continue
        source=path.read_text().replace(PARENT,NAME)
        if path.name=='complete_soc_tb.sv':
            source=replace(source,'a=1;a<256;','a=1;a<384;')
            source=replace(source,'a=256;a<3168;','a=384;a<3168;')
            core=cfg['core_path']
            source=replace(source,'q16_seed_shadow[(lane_id%16)/2][64+',
                'q16_seed_shadow['+core+'.jp_mac_lanes[lane_id].shadow_index][64+')
        elif path.name=='configuration.json':
            data=json.loads(source)
            data.update(firmware=fw,startup_model='K8-3')
            source=json.dumps(data,indent=2)+'\n'
        elif path.name=='kwt_shared_dma_icb_sm40.sv':
            source=replace(source,"joined_cmd_addr[18:2]<17'd256","joined_cmd_addr[18:2]<17'd384")
            source=replace(source,"input_committed<12'd256","input_committed<12'd384")
        elif path.name=='boot_count.svh':
            source='localparam BOOT_WORDS=%d;\n'%boot_words
        write_text(SOC/path.relative_to(parent),source)
    copy_tree(parent/'packed_inputs', SOC/'packed_inputs')
    manifest=json.loads((ROOT/cfg['adaptive_manifest']).read_text())
    manifest.update(variant=NAME,parent_variant=PARENT,purpose='experiment',selected_model='K8-3',
                    firmware=fw,parent=dict(variant=PARENT,configuration=cfg,firmware=cfg['firmware'],
                                             source_snapshot=cfg['source_snapshot'],profile=cfg['implementation']))
    manifest['changes'].update(boot_input_words=384,prologue_g2_tiles=list(range(7,15)),shared_physical_shift=True)
    manifest['hardware'].extend(('prologue_quartet_reuse','k8_scratch'))
    folder=ROOT/'constraints'/NAME/'candidates'
    folder.mkdir(parents=True,exist_ok=True)
    write_text(folder/(NAME+'.json'),json.dumps(manifest,indent=2)+'\n')
    RTL_TEST.mkdir(parents=True,exist_ok=True)
    original = BUILD/'rtl'/PARENT/'loading_dma_tb.sv'
    write_text(RTL_TEST/'loading_dma_tb.sv',local_bench(original.read_text()))
    write_text(RTL_TEST/'bank_port_tb.sv',original.with_name('bank_port_tb.sv').read_text())


def develop():
    trb.SOURCE,trb.RTL_TEST,trb.REPORT,trb.SOC=SOURCE,RTL_TEST,REPORT,SOC
    trb.develop()


def bank_check():
    trb.RTL_TEST,trb.REPORT,trb.SOC,trb.SOURCE=RTL_TEST,REPORT,SOC,SOURCE
    trb.bank_check()


if __name__=='__main__':
    {'materialize':materialize,'develop':develop,'bank':bank_check}[sys.argv[1]]()



