"""Materialize the sole winner from the frozen Q16+PF2 release."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
NAME, PARENT = 'ffn_q16_staged', 'ffn_q8_q16'
REPORT = ROOT / 'reports/optimization' / NAME
SOURCE = ROOT / 'build/optimization/rtl_sources' / NAME
SOC = ROOT / 'build/optimization/complete_soc' / NAME
RTL = ROOT / 'build/optimization/rtl' / NAME
BOOTSTRAP = {'M0':3168, 'B32':3168, 'S2':256, 'S2+B32':256, 'S1+B32':128}


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ValueError('Frozen source differs: ' + old)
    return text.replace(old,new)


def shared_controller(text):
    text = replace(text,'wire read_handoff_allowed,read_handoff_eligible;', '''wire read_handoff_allowed,read_handoff_eligible;
    wire staged_dma_ready;
    reg [11:0] input_committed;
    reg input_background_phase;
    wire host_input_word=!host_cmd_read&&host_cmd_addr<17'd3168&&host_cmd_wmask==4'hf;
    wire host_input_next=host_input_word&&host_cmd_addr=={5'b0,input_committed};
    wire host_background=host_cmd_valid&&input_background_phase&&host_input_next;
    wire host_foreground=host_cmd_valid&&!host_background;
    wire dma_input_read=ld_cmd_read&&ld_cmd_addr[1:0]==2'b00&&
                        ld_cmd_addr>=32'ha0000000&&ld_cmd_addr<32'ha0003180;
    wire dma_input_eligible=!dma_input_read||input_committed==12'd3168||
                            input_committed[11:7]>ld_cmd_addr[13:9];
    assign ld_cmd_ready=staged_dma_ready&&dma_input_eligible;''')
    text = replace(text,'.b_cmd_valid(ld_cmd_valid),','.b_cmd_valid(ld_cmd_valid&&dma_input_eligible),')
    text = replace(text,'.b_cmd_ready(ld_cmd_ready),','.b_cmd_ready(staged_dma_ready),')
    text = replace(text,'assign host_cmd_ready=idle;',
                   'assign host_cmd_ready=idle&&(!host_background||!joined_cmd_valid);')
    text = replace(text,'!host_cmd_valid&&!host_rsp_valid;', '!host_foreground&&!host_rsp_valid;')
    text = replace(text,'(idle||read_handoff)&&!host_cmd_valid;',
                   '(idle||read_handoff)&&!host_foreground;')
    text = replace(text,'wire joined_address_valid=', '''always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            input_committed<=0;
            input_background_phase<=0;
        end else if(host_fire) begin
            if(host_input_word&&host_cmd_addr==0) begin
                input_committed<=12'd1;
                input_background_phase<=0;
            end else if(host_input_next) begin
                input_committed<=input_committed+12'd1;
            end else if(!host_cmd_read&&host_cmd_addr==17'd131021&&
                        host_cmd_wmask==4'hf&&host_cmd_wdata==32'd1) begin
                input_background_phase<=1;
            end
        end
    end
    wire joined_address_valid=''')
    return text


def compact_core(text):
    text = replace(text,'17408','16896',2)
    text = replace(text,'''                    if(!BIAS32||address%4<2) begin
                        if(BIAS32) address=(address/4)*2+address%4;
                        bank_index=address%BIAS_BANKS;bias_en[bank_index]=1;bias_we[bank_index]=1;
                        bias_addr[bank_index*7+:7]=7'(address/BIAS_BANKS);bias_wdata[bank_index*16+:16]=k==0?load_data:load_high;
                    end''','''                    bank_index=address%BIAS_BANKS;bias_en[bank_index]=1;bias_we[bank_index]=1;
                    bias_addr[bank_index*7+:7]=7'(address/BIAS_BANKS);bias_wdata[bank_index*16+:16]=k==0?load_data:load_high;''')
    return text


def bench(text, bootstrap, compact, measured):
    if compact:
        text = replace(text, 'current_mode?8704:25856','current_mode?8448:25856')
        if measured:
            text = replace(text, '32768+parameter_words,host_buffer[32768+parameter_words]',
                           '32768+(current_mode?8704:parameter_words),host_buffer[32768+(current_mode?8704:parameter_words)]')
            text = replace(text,'check_guard(32768+parameter_words,','check_guard(32768+(current_mode?8704:parameter_words),')
        text = replace(text,'$readmemh(filename,host_buffer,32768,32768+parameter_words-1);',
            '''if(current_mode) filename=$sformatf("build/optimization/complete_soc/ffn_q16_staged/packed_inputs/linear_layer_%02d_b32.hex",current_source);
                $readmemh(filename,host_buffer,32768,32768+parameter_words-1);''')
        if measured:
            text = replace(text,'current_mode?11936:450752','current_mode?11680:450752')
        else:
            text = replace(text,'current_mode?139840:450752','current_mode?139584:450752')
    if measured and bootstrap!=3168:
        text = replace(text, 'a<3168;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end',
                       'a<(current_mode?%d:3168);a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end'%bootstrap)
        marker='put_word(131021,layer+1);host_control=host_control+1;'
        before, after=text.split(marker)
        end=after.index('host_idle();')
        tail=('if(current_mode) for(integer a=%d;a<3168;a=a+1) begin '
              'put_word(a,host_buffer[a]);host_payload=host_payload+1;end\n                '%bootstrap)
        text=before+marker+after[:end]+tail+after[end:]
        text=replace(text,'dut.shared_memory.host_cmd_valid||dut.shared_memory.host_rsp_valid||',
                          'dut.shared_memory.host_foreground||dut.shared_memory.host_rsp_valid||')
        monitor = """
`ifndef KWT_UNIFIED_GATE
    integer staged_late_words=0,staged_mac_words=0,staged_last_input=0,staged_group_blocked=0;
    always @(posedge system_clk) begin
        if(!activity_window) begin
            staged_late_words=0;staged_mac_words=0;staged_last_input=0;staged_group_blocked=0;
        end else begin
            if(dut.shared_memory.host_fire&&dut.shared_memory.joined_fire)
                $fatal(1,"STAGED_SHARED_PORT_DOUBLE_ACCEPT");
            if(dut.shared_memory.host_fire&&dut.shared_memory.host_input_word) begin
                staged_last_input=cycles-start_cycle;
                if(dut.shared_memory.host_background) begin
                    staged_late_words=staged_late_words+1;
                    if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==7)
                        staged_mac_words=staged_mac_words+1;
                end
            end
            if(dut.shared_memory.ld_cmd_valid&&!dut.shared_memory.dma_input_eligible)
                staged_group_blocked=staged_group_blocked+1;
        end
    end
`endif
"""
        # Keep the counters live through readback, like the other per-task observers.
        monitor=monitor.replace('if(!activity_window) begin','if(!rst_n||(activity_window&&!retire_in_window)) begin')
        monitor=monitor.replace('end else begin','end else if(activity_window) begin',1)
        monitor=monitor.replace('!retire_in_window','!staged_in_window').replace(
            '    always @(posedge system_clk)', '    reg staged_in_window=0;\n    always @(posedge system_clk)')
        monitor=monitor.replace('        end\n    end\n','        end\n        staged_in_window=activity_window;\n    end\n')
        text=replace(text,'endmodule',monitor+'endmodule')
        display = '$display("Q16_STAGED_COUNTS background=%0d during_mac=%0d input_wait=%0d last_input=%0d",staged_late_words,staged_mac_words,staged_group_blocked,staged_last_input);'
        text=replace(text,'$display("Q16_COUNTS',display+'\n        $display("Q16_COUNTS')
    return text


def firmware(old):
    dest=ROOT/'build/optimization/firmware'/NAME
    src=dest/'input-files'
    shutil.copytree(old/'input-files',src,dirs_exist_ok=True)
    driver=src/'driver.c'
    driver.write_text(replace(driver.read_text(),'transport_load(base,parameters,8704)',
                              'transport_load(base,parameters,8448)'),newline='\n')
    cfg=json.loads((old/'firmware.json').read_text())
    argv=list(cfg['compile_and_link_argv'])
    elf, binary = dest/'firmware.elf', dest/'firmware.bin'
    argv[-1]=str(elf)
    compiler=Path(argv[0])
    jobs=([argv,'firmware-build.log'],
          [[str(compiler.with_name('riscv-none-elf-objcopy.exe')),'-O','binary',str(elf),str(binary)],'firmware-objcopy.log'],
          [[str(compiler.with_name('riscv-none-elf-objdump.exe')),'-d',str(elf)],'disassembly.txt'])
    for command,log in jobs:
        with (dest/log).open('w') as stream:
            subprocess.run(command,cwd=src,stdout=stream,stderr=subprocess.STDOUT,check=True)
    raw=binary.read_bytes()
    image=raw+bytes(262144-len(raw))
    (dest/'firmware_itcm.hex').write_text(''.join('%016x\n'%int.from_bytes(image[i:i+8],'little')
                                                for i in range(0,len(image),8)),newline='\n')
    cfg.update(compile_and_link_argv=argv,firmware_bytes=len(raw),boot_words=(len(raw)+7)//8,
               frozen_input_sources=False,parameter_words=8448,parent_firmware=old.relative_to(ROOT).as_posix())
    (dest/'firmware.json').write_text(json.dumps(cfg,indent=2)+'\n')
    return dest.relative_to(ROOT).as_posix(),cfg['boot_words']


def materialize():
    selection=json.loads((REPORT/'model-selection.json').read_text())
    selected=selection['selected']
    if not selection['passed'] or selected not in BOOTSTRAP or selected=='M0':
        raise RuntimeError('No staged hardware winner')
    bootstrap, compact=BOOTSTRAP[selected], 'B32' in selected
    published=ROOT/'constraints/ffn_selected.json'
    cfg=json.loads(published.read_text())
    assert cfg['variant']==PARENT
    (REPORT/'baseline-selected.json').write_bytes(published.read_bytes())
    parent=ROOT/cfg['source_snapshot']
    old=SOC.with_name(PARENT)
    shutil.copytree(parent,SOURCE,dirs_exist_ok=True)
    fw, boot=cfg['firmware'], None
    if compact:
        fw, boot=firmware(ROOT/fw)
        for rel,transform in (
            ('encoder/kwt_encoder.sv',compact_core),
            ('encoder_bus/kwt_icb_encoder.sv',lambda s:replace(s,"16'd17408","16'd16896")),
            ('encoder/kwt_ld_engine.sv',lambda s:replace(s,"32'ha0028800","32'ha0028400"))):
            target=SOURCE/rel
            target.write_text(transform((parent/rel).read_text()),newline='\n')

    def specialize(text):
        return text.replace(cfg['firmware'],'@FIRMWARE@').replace(PARENT,NAME).replace('@FIRMWARE@',fw)

    SOC.mkdir(exist_ok=True)
    for path in old.iterdir():
        if not path.is_file() or path.suffix not in ('.sv','.v','.svh','.f','.json','.sh'):
            continue
        if path.name in ('gate_tb.sv','gate_files.f','compile_gate.sh'):
            continue
        text=specialize(path.read_text())
        if path.name=='kwt_shared_dma_icb_sm40.sv':
            if bootstrap!=3168:
                text=shared_controller(text)
            if compact:
                text=replace(text,"32'ha0028800","32'ha0028400")
        elif path.name in ('complete_soc_tb.sv','profile_tb.sv'):
            text=bench(text,bootstrap,compact,path.name=='complete_soc_tb.sv')
        elif path.name=='boot_count.svh' and boot is not None:
            text='localparam BOOT_WORDS=%d;\n'%boot
        elif path.name=='configuration.json':
            configuration=json.loads(text)
            configuration.update(staged_input_words=bootstrap,compact_bias=compact,
                                 host_payload_words32=11680 if compact else 11936)
            text=json.dumps(configuration,indent=2)+'\n'
        (SOC/path.name).write_text(text,newline='\n')
    (SOC/'eda').mkdir(exist_ok=True)
    for path in (old/'eda').glob('*.tcl'):
        if path.name!='pr1_assessment.tcl':
            (SOC/'eda'/path.name).write_text(specialize(path.read_text()),newline='\n')
    shutil.copytree(old/'packed_inputs',SOC/'packed_inputs',dirs_exist_ok=True)
    if compact:
        images=ROOT/'build/optimization/ffn_ar_area/frozen/images'
        sources=(images/'case_sources.hex').read_text().splitlines()
        for case in range(1,24,2):
            index=int(sources[case],16)
            words=(images/('linear_layer_%02d_parameters.hex'%index)).read_text().splitlines()
            assert len(words)==8704
            for low,high in zip(words[8192::2],words[8193::2]):
                assert int(high,16)==(0xffffffff if int(low,16)&0x80000000 else 0)
            (SOC/'packed_inputs'/('linear_layer_%02d_b32.hex'%index)).write_text(
                '\n'.join(words[:8192]+words[8192::2])+'\n',newline='\n')
    manifest=json.loads((ROOT/cfg['adaptive_manifest']).read_text())
    manifest.update(variant=NAME,parent_variant=PARENT,purpose='experiment',selected_model=selected,
                    firmware=fw,parent=dict(variant=PARENT,configuration=cfg,firmware=cfg['firmware'],
                                            source_snapshot=cfg['source_snapshot'],profile=cfg['implementation']))
    manifest['changes'].update(staged_input_words=bootstrap,compact_bias=compact)
    if bootstrap!=3168:
        manifest['hardware'].append('staged_input')
    if compact:
        manifest['hardware'].append('B32')
    folder=ROOT/'constraints'/NAME/'candidates'
    folder.mkdir(parents=True,exist_ok=True)
    (folder/(NAME+'.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    RTL.mkdir(exist_ok=True)
    local=(RTL.with_name(PARENT)/'loading_dma_tb.sv').read_text()
    if compact:
        local=replace(local,'load_words(1,17408)','load_words(1,16896)')
        local=replace(local,'$readmemh(filename,parameters);',
                      '''$readmemh(filename,parameters);
            for(integer bias_index=0;bias_index<256;bias_index=bias_index+1) begin
                if({parameters[16387+4*bias_index],parameters[16386+4*bias_index]}!==
                   {32{parameters[16385+4*bias_index][15]}}) $fatal(1,"B32_VECTOR_SIGN_EXTENSION");
                parameters[16384+2*bias_index]=parameters[16384+4*bias_index];
                parameters[16385+2*bias_index]=parameters[16385+4*bias_index];
            end''')
    (RTL/'loading_dma_tb.sv').write_text(local,newline='\n')


def develop():
    sys.path.insert(0,str(ROOT/'scripts/q8_q16'))
    import build_q16
    build_q16.SOURCE,build_q16.RTL,build_q16.REPORT=SOURCE,RTL,REPORT
    q8=build_q16.q8
    q8.SOURCE,q8.RTL_TEST,q8.REPORT=SOURCE,RTL,REPORT
    q8.develop()


if __name__=='__main__':
    {'materialize':materialize,'develop':develop}[sys.argv[1]]()
