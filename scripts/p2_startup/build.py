"""Materialize only the S+G winner from the frozen P2 release."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / 'reports/optimization/ffn_p2_startup'
PARENT = 'ffn_wp_P2'
NAME = 'ffn_ps_SG'
REPORT = ROOT / 'reports/optimization' / NAME
BUILD = ROOT / 'build/optimization'
SOC = BUILD / 'complete_soc' / NAME
SOURCE = BUILD / 'rtl_sources' / NAME
RTL_TEST = BUILD / 'rtl' / NAME
sys.path.insert(0, str(ROOT / 'scripts/s1_bank_overlap'))
from build_overlap import copy_tree, replace, write_text


def shared(src):
    src = replace(src, '    wire host_stream=host_cmd_valid&&input_background_phase&&host_parameter_next;\n', '')
    src = replace(src, '(ld_word[7:0]<bias_committed);', "(bias_committed==9'd256);")
    src = replace(src, '    wire joined_fire;', """    wire joined_startup_input=joined_cmd_dma&&joined_cmd_read&&joined_address_valid&&
                          joined_cmd_addr[1:0]==2'b00&&joined_cmd_addr[18:2]<17'd256;
    wire joined_fire;""")
    src = replace(src, 'host_stream&&joined_fire&&joined_load_read;',
                  'host_stream&&joined_fire&&(joined_load_read||joined_startup_input);')
    src = replace(src, '    wire host_background=', """    wire host_stream=host_cmd_valid&&input_background_phase&&
        (host_parameter_next||host_bias_next||host_shift_next||
         (host_input_next&&input_committed<12'd256));
    wire host_background=""")
    a = src.index('    wire host_dual_candidate=')
    b = src.index('    wire host_input_word=', a)
    dual = src[a:b]
    src = src[:a] + src[b:]
    src = replace(src, '    wire host_background=', dual + '    wire host_background=')
    src = replace(src, 'if(bank==8||bank==9||bank==10||bank==14)',
                  'if(bank==0||bank==8||bank==9||bank==10||bank==14)')
    return replace(src, """end else if((host_fire&&host_input_word&&host_cmd_addr==0)||
                    (joined_fire&&!joined_cmd_dma&&!joined_cmd_read&&joined_cmd_addr==32'ha007ff30)) begin""",
        'end else if(host_fire&&host_input_word&&host_cmd_addr==0) begin')


def compute(src):
    src = replace(src, 'reg [11:0] iw_pipe[0:4];', 'reg [13:0] iw_pipe[0:4];')
    src = replace(src, '    wire iw_issue_mac=', """    wire next_generation_empty;
    reg iw_join_inflight,iw_join_first;
    wire [13:0] iw_next_input_end=(row==7'd92)?14'd6336:input_window_limit;
    wire iw_join=IW_FUSED&&iw_run&&!iw_join_inflight&&row<7'd96&&
                 iw_request_tile==4'd15&&iw_request_inner==7'd63&&
                 {1'b0,input_count}>=iw_next_input_end&&next_generation_empty;
    wire iw_request_generation=input_read_generation^iw_join_inflight;
    wire iw_request_tail=iw_join_inflight?(row==7'd92):(row==7'd96);
    wire iw_issue_mac=""")
    src = replace(src, 'iw_request_inner==0&&iw_request_tile!=0',
                  'iw_request_inner==0&&(iw_request_tile!=0||iw_join_first)')
    src = replace(src, 'wire [11:0] iw_issue={iw_issue_mac,iw_issue_emit,iw_issue_tile,request_inner};',
                  """wire [13:0] iw_issue={iw_request_tail,iw_request_generation,
                          iw_issue_mac,iw_issue_emit,iw_issue_tile,request_inner};""")
    src = replace(src, '    wire [3:0] iw_mac_valid,iw_emit_valid,iw_capture;',
                  """    wire [3:0] iw_mac_valid,iw_emit_valid,iw_capture;
    wire [3:0] iw_mac_tail,iw_emit_tail,iw_capture_tail,iw_emit_generation;
    wire quant_tail=|(iw_emit_valid&iw_emit_tail);
    wire [2:0] quant_valid_rows=quant_tail?3'd3:3'd4;
    wire quant_generation=wp_boot?wp_emit_generation:|(iw_emit_valid&iw_emit_generation);""")
    src = replace(src, '        wire [11:0] req;', '        wire [13:0] req;')
    src = replace(src, '        wire [11:0] execute=iw_pipe[wave_q+1];',
                  """        wire [13:0] execute=iw_pipe[wave_q+1];
        // The fused tile-zero token retires the preceding generation.
        wire fused_join=execute[11]&&execute[10]&&execute[9:6]==4'd0;
        assign iw_mac_tail[wave_q]=!wp_boot&&execute[13];
        assign iw_capture_tail[wave_q]=!wp_boot&&iw_pipe[wave_q][13];
        assign iw_emit_tail[wave_q]=!wp_boot&&execute[13]&&!fused_join;
        assign iw_emit_generation[wave_q]=execute[12]^fused_join;""")
    src = replace(src, '    always @(posedge clk or negedge rst_n)begin\n        if(!rst_n)begin\n            iw_request_tile',
                  """    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            iw_join_inflight<=0;
            iw_join_first<=0;
        end else begin
            iw_join_first<=iw_join;
            if(layer_start_valid&&layer_start_ready)iw_join_inflight<=0;
            else if(iw_join)iw_join_inflight<=1;
            else if(!wp_boot&&output_group_done)iw_join_inflight<=0;
        end
    end
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            iw_request_tile""")
    src = replace(src, '!wp_boot&&output_group_done&&row<96)',
                  '!wp_boot&&output_group_done&&row<96&&!iw_join_inflight)')
    src = replace(src, 'IW_FUSED&&iw_request_inner==63&&iw_request_tile<15)',
                  'IW_FUSED&&iw_request_inner==63&&(iw_request_tile<15||iw_join))')
    src = replace(src, 'wire input_request_generation=wp_boot?wp_generation:input_read_generation;',
                  'wire input_request_generation=wp_boot?wp_generation:iw_request_generation;')
    src = replace(src, 'wire input_capture_generation=wp_boot?wp_capture_token[6]:input_read_generation;',
                  'wire input_capture_generation=wp_boot?wp_capture_token[6]:iw_pipe[0][12];')
    src = replace(src, "        wire row_valid=3'(ap_row)<block_rows;",
                  '        wire read_row=(ap_row!=3)||!iw_request_tail||wp_boot;')
    src = replace(src, 'ap_input_read&&row_valid&&', 'ap_input_read&&read_row&&')
    src = replace(src, 'wire capture_row=iw_capture[cp_copy]&&row_valid;',
                  'wire capture_row=iw_capture[cp_copy]&&((ap_row!=3)||!iw_capture_tail[cp_copy]);')
    src = replace(src, "jp_quant_commit&&(3'(qr)<block_rows)", "jp_quant_commit&&(3'(qr)<quant_valid_rows)")
    src = replace(src, """.restart(layer_start_valid&&layer_start_ready),.reserve(output_reserve||wp_reserve),.compute_generation(wp_boot?(wp_reserve?wp_reserved[0]:wp_emit_generation):input_read_generation),
        .group_done(output_group_done),.commit(jp_quant_commit),.valid_rows(block_rows),""",
                  """.restart(layer_start_valid&&layer_start_ready),.reserve(output_reserve||wp_reserve||iw_join),
        .query_generation(input_read_generation),.next_generation_empty(next_generation_empty),
        .reserve_generation(wp_boot?wp_reserved[0]:(input_read_generation^iw_join)),
        .compute_generation(quant_generation),
        .group_done(output_group_done),.commit(jp_quant_commit),.valid_rows(quant_valid_rows),""")
    src = replace(src, 'wire mac_update=iw_mac_valid[jp_column/4]&&row_valid;',
                  'wire mac_update=iw_mac_valid[jp_column/4]&&((jp_row!=3)||!iw_mac_tail[jp_column/4]);')
    src = replace(src, 'wire quant_commit=jp_quant_commit&&row_valid&&',
                  "wire quant_commit=jp_quant_commit&&(3'(jp_row)<quant_valid_rows)&&")
    return replace(src, 'B_MAC:if(output_group_done)state<=ADVANCE;',
                   """B_MAC:if(output_group_done)begin
                    if(iw_join_inflight)begin
                        row<=row+7'd4;
                        input_read_generation<=!input_read_generation;
                    end else state<=ADVANCE;
                end""")


def queue(src):
    src = replace(src, 'input wire reserve,compute_generation,group_done,commit,',
                  'input wire reserve,reserve_generation,compute_generation,query_generation,group_done,commit,')
    src = replace(src, 'output wire generation_empty,', 'output wire generation_empty,next_generation_empty,')
    src = replace(src, 'assign generation_empty=generation_state[compute_generation]==EMPTY;',
                  """assign generation_empty=generation_state[query_generation]==EMPTY;
    assign next_generation_empty=generation_state[!query_generation]==EMPTY;""")
    return replace(src, 'if(reserve)generation_state[compute_generation]<=FILL;',
                   'if(reserve)generation_state[reserve_generation]<=FILL;')


def observations(src, core):
    src = src.replace("4*int'("+core+'.block_rows)', "4*int'("+core+'.quant_valid_rows)')
    src = src.replace("2*int'("+core+'.block_rows)', "2*int'("+core+'.quant_valid_rows)')
    return replace(src, "(3'(cp_row)<"+core+'.block_rows)',
                   "((cp_row!=3)||!"+core+'.iw_capture_tail[cp_copy])')


def bench(src, core):
    src = observations(src, core)
    src = replace(src, 'current_mode?256:3168', 'current_mode?1:3168')
    src = replace(src, '48: layer_request=cpu_data;', """48: begin
                        layer_request=cpu_data;
                        if(current_mode)res_time_parameter_request=cycles-start_cycle;
                    end""")
    src = replace(src, """            host_idle();
            for(layer=0;layer<(current_mode?1:12);layer=layer+1) begin
                wait(layer_request==layer);res_time_parameter_request=cycles-start_cycle;""",
                  """            if(!current_mode)host_idle();
            for(layer=0;layer<(current_mode?1:12);layer=layer+1) begin
                if(!current_mode) begin
                    wait(layer_request==layer);res_time_parameter_request=cycles-start_cycle;
                end""")
    src = replace(src, """                    for(integer a=40960;a<41216;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
                    for(integer a=59392;a<59456;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
                    put_word(131021,layer+1);host_control=host_control+1;""",
                  """                    put_word(131021,layer+1);host_control=host_control+1;
                    for(integer a=59392;a<59456;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
                    for(integer a=40960;a<41216;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
                    for(integer a=1;a<256;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end""")
    src = replace(src, '!dut.shared_memory.joined_load_read||',
                  '!(dut.shared_memory.joined_load_read||dut.shared_memory.joined_startup_input)||')
    src = replace(src, '    integer output_count=', '    integer startup_group_joins=0;\n    integer output_count=')
    body = """    always @(posedge system_clk) begin
        if(!system_reset_n||(activity_window&&host_cmd_valid&&host_cmd_ready&&
                             !host_cmd_read&&host_cmd_addr==0)) startup_group_joins<=0;
        else if(@CORE@.iw_join) startup_group_joins<=startup_group_joins+1;
    end
""".replace('@CORE@', core)
    start = src.rindex('endmodule')
    src = src[:start] + """`ifndef KWT_UNIFIED_GATE
""" + body + """`endif
""" + src[start:]
    return replace(src, '$display("BANK_OVERLAP_COUNTS',
                   '$display("P2_STARTUP_JOINS case=%0d count=%0d",current_case,startup_group_joins);\n        $display("BANK_OVERLAP_COUNTS')


def firmware(config):
    old = ROOT / config['firmware']
    dest = BUILD / 'firmware' / NAME
    inputs = dest / 'input-files'
    copy_tree(old / 'input-files', inputs)
    driver = inputs / 'driver.c'
    src = driver.read_text()
    bias = """    wr_base(base,KIND,1); wr_base(base,ADDR,16384);
    rc=transport_load(base,parameters+8192,256);if(rc)return rc;
"""
    shift = """    wr_base(base,KIND,5); wr_base(base,ADDR,0);
    rc=transport_load(base,shifts,64);if(rc)return rc;
"""
    write_text(driver, replace(src, bias + shift, shift + bias))
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
                    parent_firmware=config['firmware'], startup_descriptor_order=['shift', 'bias', 'input', 'weight'])
    write_text(dest / 'firmware.json', json.dumps(metadata, indent=2)+'\n')
    return dest.relative_to(ROOT).as_posix(), metadata['boot_words']


def materialize():
    assert json.loads((EXPERIMENT / 'model-selection.json').read_text())['winner'] == 'SG'
    selected = ROOT / 'constraints/ffn_selected.json'
    config = json.loads(selected.read_text())
    assert config['variant'] == PARENT
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / 'baseline-selected.json').write_bytes(selected.read_bytes())
    fw, boot_words = firmware(config)
    copy_tree(ROOT / config['source_snapshot'], SOURCE)
    for name, edit in [('kwt_encoder.sv', compute), ('kwt_joint_output_queue.sv', queue)]:
        path = SOURCE / 'encoder' / name
        write_text(path, edit(path.read_text()))
    parent = BUILD / 'complete_soc' / PARENT
    (SOC / 'eda').mkdir(parents=True, exist_ok=True)
    for path in list(parent.iterdir()) + list((parent/'eda').glob('*.tcl')):
        if not path.is_file() or path.suffix not in ('.sv','.v','.svh','.f','.json','.sh','.tcl'):
            continue
        if path.name in ('gate_tb.sv','gate_files.f','compile_gate.sh','pr1_assessment.tcl'):
            continue
        text = path.read_text().replace(PARENT, NAME)
        if path.name == 'complete_soc_tb.sv':
            text = bench(text, config['core_path'])
        elif path.name == 'configuration.json':
            data = json.loads(text)
            data.update(firmware=fw, startup_model='SG')
            text = json.dumps(data, indent=2)+'\n'
        elif path.name == 'kwt_shared_dma_icb_sm40.sv':
            text = shared(text)
        elif path.name == 'boot_count.svh':
            text = 'localparam BOOT_WORDS=%d;\n' % boot_words
        write_text(SOC / path.relative_to(parent), text)
    copy_tree(parent / 'packed_inputs', SOC / 'packed_inputs')
    manifest = json.loads((ROOT/config['adaptive_manifest']).read_text())
    manifest.update(variant=NAME, parent_variant=PARENT, purpose='experiment', selected_model='SG',
                    firmware=fw, parent=dict(variant=PARENT, configuration=config, firmware=config['firmware'],
                                             source_snapshot=config['source_snapshot'], profile=config['implementation']))
    manifest['changes'].update(startup_dma_order='shift_bias_input_weight', continuous_row_groups=True)
    manifest['hardware'].extend(('startup_overlap', 'row_group_join'))
    folder = ROOT/'constraints'/NAME/'candidates'
    folder.mkdir(parents=True, exist_ok=True)
    write_text(folder/(NAME+'.json'), json.dumps(manifest, indent=2)+'\n')
    RTL_TEST.mkdir(parents=True, exist_ok=True)
    original = BUILD/'rtl'/PARENT/'loading_dma_tb.sv'
    write_text(RTL_TEST/'loading_dma_tb.sv', observations(original.read_text(), 'dut.core'))


def develop():
    sys.path.insert(0, str(ROOT/'scripts/r4f2_q8'))
    import build_q8
    build_q8.SOURCE, build_q8.RTL_TEST, build_q8.REPORT = SOURCE, RTL_TEST, REPORT
    build_q8.develop()


if __name__ == '__main__':
    {'materialize': materialize, 'develop': develop}[sys.argv[1]]()
