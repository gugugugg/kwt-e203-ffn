"""Build the selected two-group prologue from the frozen W4Z+FT release."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / 'reports/optimization/ffn_w4z_prologue'
PARENT = 'ffn_iw_W4Z_FT'
NAME = 'ffn_wp_P2'
sys.path.insert(0, str(ROOT / 'scripts/s1_bank_overlap'))
from build_overlap import copy_tree, replace, write_text


def compute(source):
    source = replace(source, 'B_FILL=10,ADVANCE=14,WAIT_INPUT=15,DRAIN=12;',
                     'B_FILL=10,ADVANCE=14,WAIT_INPUT=15,DRAIN=12,WP_BOOT=16;')
    source = replace(source, 'output wire layer_start_ready,busy,',
                     'output wire layer_start_ready,busy,prologue_config_ready,')
    marker = '    reg [11:0] iw_pipe[0:4];'
    source = replace(source, marker, marker + """
    // Each batch contains 256 committed weight halfwords in four banks.
    // Two input generations use that batch before advancing to the next quartet.
    wire wp_boot=state==WP_BOOT;
    reg [14:0] wp_weight_count;
    reg [13:0] wp_count;
    reg [1:0] wp_reserved;
    reg [3:0] wp_bias_step,wp_bias_tile,wp_shadow_tile;
    reg wp_shadow_valid;
    wire [3:0] wp_tile=wp_count[12:9];
    wire [1:0] wp_quartet=wp_count[8:7];
    wire wp_generation=wp_count[6];
    wire [5:0] wp_k=wp_count[5:0];
    wire [4:0] wp_bias_target={1'b0,wp_tile}+5'(wp_quartet==3&&wp_generation&&wp_k>=4);
    wire wp_bias_active=wp_boot&&!wp_count[13]&&wp_bias_target<16&&
                       (wp_bias_step!=0||!wp_shadow_valid||wp_shadow_tile!=wp_bias_target[3:0]);
    wire wp_bias_request=wp_bias_active&&wp_bias_step<8;
    wire wp_bias_capture=wp_bias_active&&wp_bias_step!=0;
    wire [2:0] wp_shadow_pair=wp_bias_step[2:0]-3'd1;
    wire wp_issue=wp_boot&&wp_reserved==2&&!wp_count[13]&&
                  wp_weight_count[14:8]>{1'b0,wp_tile,wp_quartet}&&
                  (wp_k!=0||(wp_shadow_valid&&wp_shadow_tile==wp_tile));
    wire [12:0] wp_weight_address={3'b000,ap_gray6(wp_k),wp_tile};
    reg [13:0] wp_capture_token,wp_execute_token;
    reg [7:0] wp_emit_token;
    wire wp_capture=wp_capture_token[13];
    wire wp_execute=wp_execute_token[13];
    wire wp_emit=wp_emit_token[7];
    wire wp_emit_generation=wp_emit_token[6];
    wire wp_finish=wp_emit&&wp_emit_token[5:0]==6'd63;
    wire wp_reserve=wp_boot&&wp_reserved!=2;
    wire wp_weight_conflict=wp_issue&&
        (wp_weight_count[9:8]==wp_quartet||
         (wp_weight_count[7:0]==8'hff&&wp_weight_count[9:8]+2'd1==wp_quartet));
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            wp_count<=0;wp_reserved<=0;
            wp_bias_step<=0;wp_bias_tile<=0;wp_shadow_tile<=0;wp_shadow_valid<=0;
            wp_capture_token<=0;wp_execute_token<=0;wp_emit_token<=0;
        end else if(layer_start_valid&&layer_start_ready)begin
            wp_count<=0;wp_reserved<=0;wp_bias_step<=0;wp_shadow_valid<=0;
            wp_capture_token<=0;wp_execute_token<=0;wp_emit_token<=0;
        end else if(wp_boot)begin
            wp_capture_token<={wp_issue,wp_count[12:0]};
            wp_execute_token<=wp_capture_token;
            wp_emit_token<={wp_execute&&wp_execute_token[5:0]==63,
                           wp_execute_token[6],wp_execute_token[12:9],wp_execute_token[8:7]};
            if(wp_issue)wp_count<=wp_count+1'b1;
            if(wp_reserve)wp_reserved<=wp_reserved+1'b1;
            if(wp_bias_active)begin
                if(wp_bias_step==0)wp_bias_tile<=wp_bias_target[3:0];
                if(wp_bias_step==8)begin
                    wp_shadow_tile<=wp_bias_tile;wp_shadow_valid<=1;wp_bias_step<=0;
                end else wp_bias_step<=wp_bias_step+1'b1;
            end
        end
    end""")
    source = replace(source, 'wire output_group_done=iw_emit_valid[3]&&(iw_emit_tile[3]==15);',
                     'wire output_group_done=wp_boot?wp_finish:(iw_emit_valid[3]&&(iw_emit_tile[3]==15));')
    source = replace(source, 'else if(output_group_done&&row<96)', 'else if(!wp_boot&&output_group_done&&row<96)')
    source = replace(source, 'wire ap_er_first_request=iw_mac_valid', 'wire ap_er_first_request=!wp_boot&&iw_mac_valid')
    source = replace(source, 'wire ap_er_next_request=iw_mac_valid', 'wire ap_er_next_request=!wp_boot&&iw_mac_valid')
    source = replace(source, 'wire ap_er_reseed=jp_quant_commit', 'wire ap_er_reseed=!wp_boot&&jp_quant_commit')
    source = replace(source, "wire [3:0] ap_bias_tile=ap_er_request?ap_er_target_tile:4'd0;",
                     """wire [3:0] ap_bias_tile=wp_boot?(wp_bias_step==0?wp_bias_target[3:0]:wp_bias_tile):
        (ap_er_request?ap_er_target_tile:4'd0);""")
    source = replace(source, 'wire [2:0] ap_bias_pair=ap_er_request?ap_er_request_pair:chunk;',
                     'wire [2:0] ap_bias_pair=wp_boot?wp_bias_step[2:0]:(ap_er_request?ap_er_request_pair:chunk);')
    source = replace(source, 'wire bias_request=(state==BIAS_REQ)||ap_er_request;',
                     'wire bias_request=(state==BIAS_REQ)||ap_er_request||wp_bias_request;')
    a = source.index('        assign iw_weight_read[wave_q]')
    b = source.index('    end endgenerate', a)
    source = source[:a] + """        assign iw_weight_read[wave_q]=wp_boot?(wp_issue&&wp_quartet==2'(wave_q)):req[11];
        assign iw_weight_address[wave_q]=wp_boot?wp_weight_address:{3'b000,ap_gray6(req[5:0]),req[9:6]};
        assign iw_capture[wave_q]=wp_boot?(wp_capture&&wp_capture_token[8:7]==2'(wave_q)):iw_pipe[wave_q][11];
        assign iw_mac_valid[wave_q]=wp_boot?(wp_execute&&wp_execute_token[8:7]==2'(wave_q)):execute[11];
        assign iw_emit_valid[wave_q]=wp_boot?(wp_emit&&wp_emit_token[1:0]==2'(wave_q)):execute[10];
        assign iw_mac_tile[wave_q]=wp_boot?wp_execute_token[12:9]:execute[9:6];
        assign iw_mac_inner[wave_q]=wp_boot?wp_execute_token[5:0]:execute[5:0];
        assign iw_emit_tile[wave_q]=wp_boot?wp_emit_token[5:2]:(execute[11]?execute[9:6]-4'd1:execute[9:6]);
""" + source[b:]
    source = replace(source, 'wire ap_input_read=iw_issue_mac;',
                     """wire ap_input_read=iw_issue_mac||wp_issue;
    wire input_request_generation=wp_boot?wp_generation:input_read_generation;
    wire input_capture_generation=wp_boot?wp_capture_token[6]:input_read_generation;
    wire [5:0] input_request_inner=wp_boot?wp_k:request_inner;""")
    source = replace(source, 'generation_data[input_read_generation*16+:16]',
                     'generation_data[input_capture_generation*16+:16]')
    source = replace(source, "(input_read_generation==1'(gen))", "(input_request_generation==1'(gen))")
    source = replace(source, ':request_inner;\n            wire memory_clk;', ':input_request_inner;\n            wire memory_clk;')
    source = replace(source, 'else assign capture_value=jp_input_return[(ap_row*4+cp_copy-1)*16+:16];',
                     'else assign capture_value=wp_boot?ap_input_rdata[ap_row*16+:16]:jp_input_return[(ap_row*4+cp_copy-1)*16+:16];')
    source = replace(source, "wire write_shadow=q16_shadow_capture&&(inner[2:0]==3'(pair_id));",
                     """wire write_shadow=wp_boot?(wp_bias_capture&&wp_shadow_pair==3'(pair_id)):
            (q16_shadow_capture&&inner[2:0]==3'(pair_id));""")
    source = replace(source, 'wire q16_shadow_capture=iw_mac_valid', 'wire q16_shadow_capture=!wp_boot&&iw_mac_valid')
    source = replace(source, '.reserve(output_reserve),.compute_generation(input_read_generation),',
                     '.reserve(output_reserve||wp_reserve),.compute_generation(wp_boot?(wp_reserve?wp_reserved[0]:wp_emit_generation):input_read_generation),')
    source = replace(source, 'wire seed_update=(row_valid&&bias_capture',
                     """wire wp_seed=wp_boot&&iw_mac_valid[jp_column/4]&&wp_execute_token[5:0]==0;
        wire seed_update=wp_seed||(row_valid&&bias_capture""")
    source = replace(source, 'seed_bias=ap_er_reseed?', 'seed_bias=(ap_er_reseed||wp_seed)?')
    source = replace(source, 'seed_shift=ap_er_reseed?', 'seed_shift=(ap_er_reseed||wp_seed)?')
    a = source.index('    assign layer_start_ready=')
    b = source.index('    assign load_ready=', a)
    source = source[:a] + """    assign layer_start_ready=layer_request&&(parameter_count==512)&&(shift_count==128)&&(input_count==512);
    assign prologue_config_ready=wp_boot||(state==WAIT_INPUT&&row==8);
    wire [13:0] active_input_limit=(layer_request||wp_boot)?14'd512:input_window_limit;
    assign load_capacity_ready=((state==WAIT_LAYER)&&
         ((load_kind==1&&parameter_count<512)||(load_kind==5&&shift_count<128)))||
         (wp_boot&&load_kind==1&&wp_weight_count<16384&&!wp_weight_conflict)||
         (load_kind==0&&(layer_request||state>=3)&&(input_count<6336)&&
          ({1'b0,input_count}<active_input_limit));
    assign input_pair_capacity_ready=(input_count<6335)&&
        (({1'b0,input_count}+14'd1)<active_input_limit);
""" + source[b:]
    source = replace(source, 'bank_index=address%LANES;pm_en[bank_index]=1;pm_we[bank_index]=1;',
                     "bank_index=int'({address[9:8],address[1:0]});pm_en[bank_index]=1;pm_we[bank_index]=1;")
    source = replace(source, "ld_parameter_address(13'(address/LANES))",
                     "{3'b000,ap_gray6(address[7:2]),address[13:10]}")
    source = replace(source, 'state<=CLEAR;clear_index<=0;input_count<=0;parameter_count<=0;shift_count<=0;',
                     'state<=CLEAR;clear_index<=0;input_count<=0;parameter_count<=0;shift_count<=0;wp_weight_count<=0;')
    source = replace(source, """1:if(load_addr==16'(parameter_count)&&parameter_count<16896)parameter_count<=parameter_count+15'(load_count);else error<=1;""",
                     """1:if(wp_boot&&load_addr==16'(wp_weight_count)&&wp_weight_count<16384)
                    wp_weight_count<=wp_weight_count+15'(load_count);
                else if(layer_request&&load_addr==16'd16384+16'(parameter_count)&&parameter_count<512)
                    parameter_count<=parameter_count+15'(load_count);
                else error<=1;""")
    source = replace(source, 'else begin parameter_count<=0;shift_count<=0;state<=WAIT_LAYER;end',
                     'else begin parameter_count<=0;shift_count<=0;wp_weight_count<=0;state<=WAIT_LAYER;end')
    source = replace(source, """row<=0;item<=0;state<=WAIT_INPUT;
                    input_write_cursor<=0;input_read_generation<=0;""",
                     """row<=0;item<=0;state<=WP_BOOT;input_read_generation<=0;
                end
                WP_BOOT:if(wp_finish&&wp_emit_generation)begin
                    row<=8;state<=WAIT_INPUT;""")
    source = replace(source, 'wire pf2_capture=iw_emit_valid', 'wire pf2_capture=!wp_boot&&iw_emit_valid')
    return source


def shared(source):
    source = replace(source, 'reg [13:0] parameter_committed;',
                     'reg [13:0] parameter_committed;\n    reg [8:0] bias_committed;')
    source = replace(source, "parameter_committed<14'd8448&&host_cmd_addr==17'd32768+17'(parameter_committed);",
                     """parameter_committed<14'd8192&&host_cmd_addr==17'd32768+17'(parameter_committed);
    wire host_bias_next=!host_cmd_read&&host_cmd_wmask==4'hf&&
            bias_committed<9'd256&&host_cmd_addr==17'd40960+17'(bias_committed);""")
    source = replace(source, '(host_parameter_next||host_shift_next)', 'host_parameter_next')
    source = replace(source, 'wire parameter_ready=ld_word[13:0]<parameter_committed;',
                     """wire parameter_ready=(ld_word<17'd40960)?(ld_word[12:0]<parameter_committed):
        (ld_word[7:0]<bias_committed);""")
    source = replace(source, "parameter_committed==14'd8448", "parameter_committed==14'd8192&&bias_committed==9'd256")
    source = source.replace('parameter_committed<=0;','parameter_committed<=0;\n            bias_committed<=0;')
    source = replace(source, "if(host_parameter_next) parameter_committed<=parameter_committed+14'd1;",
                     """if(host_parameter_next) parameter_committed<=parameter_committed+14'd1;
            if(host_bias_next) bias_committed<=bias_committed+9'd1;""")
    return source


def observations(source, core):
    old = 'else assign value_before=' + core + '.jp_input_return[(cp_row*4+cp_copy-1)*16+:16];'
    if old in source:
        source = replace(source, old, 'else assign value_before=' + core + '.wp_boot?' +
                         core + '.ap_input_rdata[cp_row*16+:16]:' + core +
                         '.jp_input_return[(cp_row*4+cp_copy-1)*16+:16];')
    source = source.replace('shift_at_seed='+core+'.ap_er_reseed?',
                            'shift_at_seed='+core+'.wp_boot?$signed('+core+
                            '.q16_seed_shadow[(lane_id%16)/2][64+(lane_id%2)*8+:8]):'+core+'.ap_er_reseed?')
    return source


def bench(source, core, firmware_dir):
    source = observations(source, core)
    source = source.replace('build/optimization/firmware/ffn_q16_staged/firmware_itcm.hex',
                            firmware_dir+'/firmware_itcm.hex')
    source = source.replace('current_mode?128:3168','current_mode?256:3168')
    a = source.index('                for(integer a=32768;a<=parameter_end;')
    b = source.index('                host_idle();', a)
    return source[:a] + """                if(current_mode)begin
                    for(integer a=40960;a<41216;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
                    for(integer a=59392;a<59456;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
                    put_word(131021,layer+1);host_control=host_control+1;
                    for(integer a=32768;a<40960;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
                    res_time_parameter_injection_end=cycles-start_cycle;
                    for(integer a=256;a<3168;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
                end else begin
                    for(integer a=32768;a<=parameter_end;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
                    put_word(131021,layer+1);host_control=host_control+1;
                end
""" + source[b:]


def local_bench(source):
    source = observations(source, 'dut.core')
    source = replace(source, 'task load_words(input integer kind,input integer count);',
                     'task load_words(input integer kind,input integer first,input integer count);')
    source = replace(source, 'write_word(8,kind);write_word(12,0);address=0;',
                     'write_word(8,kind);write_word(12,first);address=first;')
    source = replace(source, 'if(LD_DMA)dma_transfer(location,count/2,1);',
                     'if(LD_DMA)dma_transfer(location+first*2,(count-first)/2,1);')
    source = replace(source, 'if(!stream_input)load_words(0,6336);','if(!stream_input)load_words(0,0,6336);')
    source = replace(source, '    initial begin\n        if($value$plusargs("ROW_GROUP',
                     '    reg [15:0] weight_original[0:16383];\n    initial begin\n        if($value$plusargs("ROW_GROUP')
    key = '            for(integer bias_index=0;bias_index<256;bias_index=bias_index+1) begin'
    source = replace(source, key, """            for(integer w=0;w<16384;w=w+1)weight_original[w]=parameters[w];
            for(integer t=0;t<16;t=t+1)
                for(integer q=0;q<4;q=q+1)
                    for(integer k=0;k<64;k=k+1)
                        for(integer c=0;c<4;c=c+1)
                            parameters[t*1024+q*256+k*4+c]=weight_original[t*1024+k*16+q*4+c];
""" + key)
    a = source.index('            load_words(1,16896);')
    b = source.index('            receive_limit=', a)
    source = source[:a] + """            load_words(1,16384,16896);load_words(5,0,128);
            write_word(8,0);write_word(12,0);input_block(0,8);
            read_word(4,value);if(!(value&32)) $fatal(1,"WP_START_NOT_READY");
            active=1;write_word(24,1);
            load_words(1,0,16384);
            write_word(8,0);write_word(12,512);

            index=0;
            for(block_row=0;block_row<99;block_row=block_row+4) begin
            if(block_row!=0&&block_row+4<99)
                input_block(block_row+4,(99-block_row-4<4)?99-block_row-4:4);
""" + source[b:]
    return source


def firmware(config):
    old = ROOT / config['firmware']
    dest = ROOT / 'build/optimization/firmware' / NAME
    inputs = dest / 'input-files'
    copy_tree(old / 'input-files', inputs)
    driver = inputs / 'driver.c'
    source = driver.read_text()
    a = source.index('    wr_base(base,KIND,1); wr_base(base,ADDR,0);')
    b = source.index('        unsigned rows=', a)
    source = source[:a] + """    wr_base(base,KIND,1); wr_base(base,ADDR,16384);
    rc=transport_load(base,parameters+8192,256);if(rc)return rc;
    wr_base(base,KIND,5); wr_base(base,ADDR,0);
    rc=transport_load(base,shifts,64);if(rc)return rc;
    wr_base(base,KIND,0); wr_base(base,ADDR,0);
    rc=transport_load(base,input,256);if(rc)return rc;
    rc=wait_state(d,32u);if(rc)return rc;
    wr(d,START_LAYER,1);fence_io();
    wr_base(base,KIND,1); wr_base(base,ADDR,0);
    rc=transport_load(base,parameters,8192);if(rc)return rc;
    wr_base(base,KIND,0); wr_base(base,ADDR,512);
    rc=transport_output(base,output,1024);if(rc)return rc;
    for(unsigned row=4;row<99;row+=KWU_ROW_GROUP) {
""" + source[b:]
    write_text(driver, source)
    metadata = json.loads((old / 'firmware.json').read_text())
    argv = metadata['compile_and_link_argv']
    elf, binary = dest / 'firmware.elf', dest / 'firmware.bin'
    argv[-1] = str(elf)
    compiler = Path(argv[0])
    for command, log in ((argv, 'firmware-build.log'),
        ([str(compiler.with_name('riscv-none-elf-objcopy.exe')), '-O', 'binary', str(elf), str(binary)], 'firmware-objcopy.log'),
        ([str(compiler.with_name('riscv-none-elf-objdump.exe')), '-d', str(elf)], 'disassembly.txt')):
        with (dest / log).open('w') as stream:
            subprocess.run(command, cwd=inputs, stdout=stream, stderr=subprocess.STDOUT, check=True)
    raw = binary.read_bytes()
    image = raw + bytes(262144 - len(raw))
    write_text(dest / 'firmware_itcm.hex', ''.join('%016x\n' % int.from_bytes(image[i:i+8], 'little')
                                               for i in range(0, len(image), 8)))
    metadata.update(compile_and_link_argv=argv, firmware_bytes=len(raw), boot_words=(len(raw)+7)//8,
                    parent_firmware=config['firmware'], prologue_input_words=256, weight_words=8192, bias_words=256)
    write_text(dest / 'firmware.json', json.dumps(metadata, indent=2)+'\n')
    return dest.relative_to(ROOT).as_posix(), metadata['boot_words']


def materialize():
    assert json.loads((EXPERIMENT / 'model-selection.json').read_text())['winner']=='P2'
    selected = ROOT / 'constraints/ffn_selected.json'
    config = json.loads(selected.read_text())
    assert config['variant']==PARENT
    report = ROOT / 'reports/optimization' / NAME
    report.mkdir(parents=True, exist_ok=True)
    (report / 'baseline-selected.json').write_bytes(selected.read_bytes())
    fw, boot_words = firmware(config)
    root = ROOT / 'build/optimization'
    snapshot = root / 'rtl_sources' / NAME
    out = root / 'complete_soc' / NAME
    copy_tree(ROOT / config['source_snapshot'], snapshot)
    core = snapshot / 'encoder/kwt_encoder.sv'
    write_text(core, compute(core.read_text()))
    wrapper = snapshot / 'encoder_bus/kwt_icb_encoder.sv'
    source = wrapper.read_text().replace('wire dma_core_load_capacity_ready;',
                                          'wire dma_core_load_capacity_ready,prologue_config_ready;')
    source = replace(source, '.layer_start_valid(do_layer),.layer_start_ready(core_layer_ready),',
                     '.layer_start_valid(do_layer),.layer_start_ready(core_layer_ready),.prologue_config_ready(prologue_config_ready),')
    source = source.replace('(core_start_ready||core_layer_request)', '(core_start_ready||core_layer_request||prologue_config_ready)')
    write_text(wrapper, source)
    parent = root / 'complete_soc' / PARENT
    (out / 'eda').mkdir(parents=True, exist_ok=True)
    for path in list(parent.iterdir()) + list((parent/'eda').glob('*.tcl')):
        if not path.is_file() or path.suffix not in ('.sv','.v','.svh','.f','.json','.sh','.tcl'):
            continue
        if path.name in ('gate_tb.sv','gate_files.f','compile_gate.sh','pr1_assessment.tcl'):
            continue
        text = path.read_text().replace(PARENT, NAME)
        if path.name=='complete_soc_tb.sv':
            text = bench(text, config['core_path'], fw)
        elif path.name=='configuration.json':
            data = json.loads(text)
            data.update(firmware=fw, prologue='P2', staged_input_words=256)
            text = json.dumps(data, indent=2)+'\n'
        elif path.name=='kwt_shared_dma_icb_sm40.sv':
            text = shared(text)
        elif path.name=='boot_count.svh':
            text = 'localparam BOOT_WORDS=%d;\n' % boot_words
        write_text(out / path.relative_to(parent), text)
    copy_tree(parent / 'packed_inputs', out / 'packed_inputs')
    for path in (out / 'packed_inputs').glob('linear_layer_*_b32.hex'):
        words = path.read_text().splitlines()
        weights = [words[(tile*64+k)*8+quartet*2+pair] for tile in range(16) for quartet in range(4)
                   for k in range(64) for pair in range(2)]
        write_text(path, '\n'.join(weights + words[8192:])+'\n')
    manifest = json.loads((ROOT/config['adaptive_manifest']).read_text())
    manifest.update(variant=NAME, parent_variant=PARENT, purpose='experiment', selected_model='P2', firmware=fw,
                    parent=dict(variant=PARENT, configuration=config, firmware=config['firmware'],
                                source_snapshot=config['source_snapshot'], profile=config['implementation']))
    manifest['changes'].update(prologue='P2', staged_input_words=256)
    manifest['hardware'].append('P2')
    folder = ROOT/'constraints'/NAME/'candidates'
    folder.mkdir(parents=True, exist_ok=True)
    write_text(folder/(NAME+'.json'),json.dumps(manifest,indent=2)+'\n')
    rtl = root/'rtl'/NAME
    rtl.mkdir(parents=True, exist_ok=True)
    write_text(rtl/'loading_dma_tb.sv', local_bench((root/'rtl'/PARENT/'loading_dma_tb.sv').read_text()))


def develop():
    sys.path.insert(0, str(ROOT/'scripts/r4f2_q8'))
    import build_q8
    build_q8.SOURCE=ROOT/'build/optimization/rtl_sources'/NAME
    build_q8.RTL_TEST=ROOT/'build/optimization/rtl'/NAME
    build_q8.REPORT=ROOT/'reports/optimization'/NAME
    build_q8.develop()


if __name__ == '__main__':
    {'materialize': materialize, 'develop': develop}[sys.argv[1]]()
