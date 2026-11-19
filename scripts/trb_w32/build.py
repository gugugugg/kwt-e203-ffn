"""Materialize only the W32 candidate admitted by the cold-task model."""
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
NAME,PARENT='ffn_trb_w32','ffn_sg_reuse'
REPORT=EXPERIMENT=ROOT/'reports/optimization'/NAME
BUILD=ROOT/'build/optimization'
SOURCE=BUILD/'rtl_sources'/NAME
SOC=BUILD/'complete_soc'/NAME
RTL_TEST=BUILD/'rtl'/NAME
spec=importlib.util.spec_from_file_location('trb_build',ROOT/'scripts/sg_reuse/build.py')
base=importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
copy_tree, replace, write_text=base.copy_tree,base.replace,base.write_text


def section(src,start,end,body):
    a=src.index(start)
    return src[:a]+body+src[src.index(end,a):]


def compute(src):
    src=replace(src,'    reg [12:0] input_count;', '''    reg [12:0] input_count;
    reg [1:0] w32_input_ready;
    reg [7:0] w32_seed_captured;''')
    src=replace(src,"wire input_complete={1'b0,input_count}>=((14'({1'b0,row})+14'(block_rows))<<6);",
        "wire input_complete=w32_input_ready[input_read_generation]&&{1'b0,input_count}>=((14'({1'b0,row})+14'(block_rows))<<6);")
    src=replace(src,"{1'b0,input_count}>=iw_next_input_end&&next_generation_empty;",
        "{1'b0,input_count}>=iw_next_input_end&&w32_input_ready[!input_read_generation]&&next_generation_empty;")
    src=section(src,'    reg [3:0] wp_bias_step','    wire [3:0] wp_tile','')
    src=section(src,'    wire [4:0] wp_bias_target','    wire wp_issue','')
    src=replace(src,'(wp_k!=0||(wp_shadow_valid&&wp_shadow_tile==wp_tile));',
        "w32_seed_captured>={1'b0,wp_tile,wp_quartet,1'b0}+8'd2;")
    src=replace(src,'    wire wp_finish=wp_emit&&wp_emit_token[5:0]==6\'d63;\n','')
    src=replace(src,'            wp_bias_step<=0;wp_bias_tile<=0;wp_shadow_tile<=0;wp_shadow_valid<=0;\n','')
    src=replace(src,'            wp_count<=0;wp_reserved<=0;wp_bias_step<=0;wp_shadow_valid<=0;',
        '            wp_count<=0;wp_reserved<=0;')
    src=section(src,'            if(wp_bias_active)begin','        end\n    end\n    wire iw_first','')
    src=replace(src,'    wire [3:0] iw_mac_tail,iw_emit_tail,iw_capture_tail,iw_emit_generation;',
        '    wire [3:0] iw_mac_tail,iw_emit_tail,iw_capture_tail,iw_emit_generation,iw_mac_generation;')
    src=replace(src,'wire quant_generation=wp_boot?wp_emit_generation:|(iw_emit_valid&iw_emit_generation);',
        'wire quant_generation=|(iw_emit_valid&iw_emit_generation);')
    src=replace(src,'wire output_group_done=wp_boot?wp_finish:(iw_emit_valid[3]&&(iw_emit_tile[3]==15));',
        'wire output_group_done=iw_emit_valid[3]&&(iw_emit_tile[3]==15);')
    src=section(src,'    wire [3:0] ap_bias_tile','    wire bias_capture', '''    wire [3:0] ap_bias_tile=ap_er_request?iw_mac_tile[0]+4'd1:4'd0;
    wire [2:0] ap_bias_pair=ap_er_request?ap_er_request_pair:chunk;
    wire bias_request=(state==BIAS_REQ)||ap_er_request;
''')
    src=replace(src,'        assign iw_emit_tail[wave_q]=!wp_boot&&execute[13]&&!fused_join;\n        assign iw_emit_generation[wave_q]=execute[12]^fused_join;',
        '''        assign iw_mac_generation[wave_q]=wp_boot?wp_execute_token[6]:execute[12];
        reg [6:0] emit_capture,emit_delayed;
        wire raw_valid=wp_boot?(wp_emit&&wp_emit_token[1:0]==2'(wave_q)):execute[10];
        wire raw_tail=!wp_boot&&execute[13]&&!fused_join;
        wire raw_generation=wp_boot?wp_emit_generation:(execute[12]^fused_join);
        wire [3:0] raw_tile=wp_boot?wp_emit_token[5:2]:(execute[11]?execute[9:6]-4'd1:execute[9:6]);
        always @(posedge clk or negedge rst_n)begin
            if(!rst_n)begin emit_capture<=0;emit_delayed<=0;end
            else begin
                emit_capture<={raw_valid,raw_tail,raw_generation,raw_tile};
                emit_delayed<=emit_capture;
            end
        end
        assign {iw_emit_valid[wave_q],iw_emit_tail[wave_q],
                iw_emit_generation[wave_q],iw_emit_tile[wave_q]}=emit_delayed;''')
    src=replace(src,"        assign iw_emit_valid[wave_q]=wp_boot?(wp_emit&&wp_emit_token[1:0]==2'(wave_q)):execute[10];\n",'')
    src=replace(src,"        assign iw_emit_tile[wave_q]=wp_boot?wp_emit_token[5:2]:(execute[11]?execute[9:6]-4'd1:execute[9:6]);\n",'')
    corr=(Path(__file__).parent/'correction.svh').read_text()
    corr=corr.replace('    reg [1:0] w32_input_ready;\n','').replace('w32_seed_requested,w32_seed_captured;', 'w32_seed_requested;')
    src=replace(src,'    reg [79:0] q16_seed_shadow[0:7];',corr+'    reg [79:0] q16_seed_shadow[0:7];')
    src=replace(src,"""        wire write_shadow=wp_boot?(wp_bias_capture&&wp_shadow_pair==3'(pair_id)):
            (q16_shadow_capture&&inner[2:0]==3'(pair_id));""",
        """        wire write_shadow=(bias_capture&&chunk==3'(pair_id))||
            (q16_shadow_capture&&inner[2:0]==3'(pair_id));""")
    src=replace(src,'            q16_seed_shadow[pair_id]<={jp_shift_return,bias_rdata};',
        "            q16_seed_shadow[pair_id]<={2'b00,w32_seed_word};")
    src=section(src,'    generate for(genvar jp_lane=0','    assign start_ready',
        (Path(__file__).parent/'arithmetic.svh').read_text())
    src=replace(src,'&&(input_count==512);','&&(input_count==512)&&(&w32_input_ready);')
    src=replace(src,'shift_wdata=load_data;end',
        "shift_wdata={5'd0,w32_encode_shift(load_data[15:8]),5'd0,w32_encode_shift(load_data[7:0])};end")
    src=replace(src,'        if(bias_request) begin', '''        if(w32_bias_write||w32_seed_read||w32_raw_read)begin
            bias_en='1;shift_en=1;
            for(b=0;b<BIAS_BANKS;b=b+1)bias_addr[b*7+:7]=w32_bias_address;
            shift_addr=w32_bias_address;
            if(w32_bias_write)begin
                bias_we='1;shift_we=1;
                bias_wdata={w32_bias_high[31:0],w32_bias_low[31:0]};
                shift_wdata={1'b0,w32_bias_high[35:32],w32_raw_pair[74:72],
                            1'b0,w32_bias_low[35:32],w32_raw_pair[66:64]};
            end
        end
        if(bias_request) begin''')
    return replace(src,'WP_BOOT:if(wp_finish&&wp_emit_generation)begin',
        'WP_BOOT:if(output_group_done&&quant_generation)begin')


def bench(src,core):
    src=replace(src,'products=products+1','products=products+2')
    src=replace(src,"macs=int'("+core+".jp_mac_mask[car_lane])",
                    "macs=2*int'("+core+".jp_mac_mask[car_lane])")
    src=replace(src,'macs=macs+1','macs=macs+2')
    src=replace(src,'{'+core+'.jp_shift_return,'+core+'.bias_rdata}',
        "{2'b00,"+core+'.w32_seed_word}')
    a=src.index('                    shift_at_seed=')
    b=src.index('\n',a)
    src=src[:a]+'                    shift_at_seed='+core+'.jp_mac_lanes[lane_id].seed_shift;'+src[b:]
    return src


def materialize():
    assert json.loads((REPORT/'model-results.json').read_text())['selected']
    selected=ROOT/'constraints/ffn_selected.json'
    cfg=json.loads(selected.read_text())
    assert cfg['variant']==PARENT
    (REPORT/'baseline-selected.json').write_bytes(selected.read_bytes())
    copy_tree(ROOT/cfg['source_snapshot'],SOURCE)
    path=SOURCE/'encoder/kwt_encoder.sv'
    write_text(path,compute(path.read_text()))
    (SOC/'eda').mkdir(parents=True,exist_ok=True)
    parent=BUILD/'complete_soc'/PARENT
    for path in list(parent.iterdir())+list((parent/'eda').glob('*.tcl')):
        if not path.is_file() or path.suffix not in ('.sv','.v','.svh','.f','.json','.sh','.tcl'):
            continue
        if path.name in ('gate_tb.sv','gate_files.f','compile_gate.sh','pr1_assessment.tcl'):
            continue
        text=path.read_text().replace(PARENT,NAME)
        if path.name=='complete_soc_tb.sv':
            text=bench(text,cfg['core_path'])
            text=replace(text,'(|'+cfg['core_path']+'.iw_mac_valid)','(|'+cfg['core_path']+'.w32_product_valid)')
        elif path.name=='configuration.json':
            data=json.loads(text)
            data.update(firmware=cfg['firmware'],startup_model='W32')
            text=json.dumps(data,indent=2)+'\n'
        write_text(SOC/path.relative_to(parent),text)
    copy_tree(parent/'packed_inputs',SOC/'packed_inputs')
    # The native archive expects candidate firmware in its own directory.
    copy_tree(ROOT/cfg['firmware'],BUILD/'firmware'/NAME)
    manifest=json.loads((ROOT/cfg['adaptive_manifest']).read_text())
    manifest.update(variant=NAME,parent_variant=PARENT,purpose='experiment',selected_model='W32',
        firmware=cfg['firmware'],parent=dict(variant=PARENT,configuration=cfg,firmware=cfg['firmware'],
                                            source_snapshot=cfg['source_snapshot'],profile=cfg['implementation']))
    manifest['changes'].update(paired_inner_product=True,main_multipliers=32,correction_multipliers=2)
    manifest['hardware'].append('W32')
    folder=ROOT/'constraints'/NAME/'candidates'
    folder.mkdir(parents=True,exist_ok=True)
    write_text(folder/(NAME+'.json'),json.dumps(manifest,indent=2)+'\n')
    RTL_TEST.mkdir(parents=True,exist_ok=True)
    original=BUILD/'rtl'/PARENT/'loading_dma_tb.sv'
    write_text(RTL_TEST/'loading_dma_tb.sv',bench(original.read_text(),'dut.core'))
    write_text(RTL_TEST/'bank_port_tb.sv',original.with_name('bank_port_tb.sv').read_text())


def develop():
    base.SOURCE,base.RTL_TEST,base.REPORT,base.SOC=SOURCE,RTL_TEST,REPORT,SOC
    base.develop()
    base.bank_check()
    local=REPORT/'local-acceptance.json'
    data=json.loads(local.read_text())
    data.update(shared_protocol_passed=True,output_requantizers=16,paired_main_multipliers=32,
                correction_multipliers=2)
    local.write_text(json.dumps(data,indent=2)+'\n')


if __name__=='__main__':
    {'materialize':materialize,'develop':develop}[sys.argv[1]]()

