"""Derive the two independent shared-bank research builds from published S1+B32."""
import argparse
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
PARENT = 'ffn_q16_staged'
EXPERIMENT = ROOT/'reports/optimization/ffn_s1_bank_overlap'
MODES = {'N':4096,'I':1}


def variant(mode):
    return 'ffn_s1_bank_'+mode


def copy_tree(source,target):
    for path in source.rglob('*'):
        if path.is_file():
            dest=target/path.relative_to(source)
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,dest)


def write_text(path,text):
    with path.open('w',encoding='utf-8',newline='\n') as stream:
        stream.write(text)


def replace(text, old, new):
    if text.count(old)!=1:
        raise ValueError('Frozen source differs: '+old)
    return text.replace(old,new)


def controller(text, mode):
    declarations = """
    reg [13:0] parameter_committed;
    reg [6:0] shift_committed;
    wire [16:0] ld_word=ld_cmd_addr[18:2];
    wire host_parameter_next=!host_cmd_read&&host_cmd_wmask==4'hf&&
            parameter_committed<14'd8448&&host_cmd_addr==17'd32768+17'(parameter_committed);
    wire host_shift_next=!host_cmd_read&&host_cmd_wmask==4'hf&&
            shift_committed<7'd64&&host_cmd_addr==17'd59392+17'(shift_committed);
    wire host_stream=host_cmd_valid&&input_background_phase&&(host_parameter_next||host_shift_next);
    wire dma_parameter_read=ld_cmd_read&&ld_cmd_addr[1:0]==2'b00&&
                            ld_cmd_addr>=32'ha0020000&&ld_cmd_addr<32'ha0028400;
    wire dma_shift_read=ld_cmd_read&&ld_cmd_addr[1:0]==2'b00&&
                        ld_cmd_addr>=32'ha003a000&&ld_cmd_addr<32'ha003a100;
    wire parameter_ready=@PARAMETER_READY@;
    wire dma_load_eligible=(!dma_parameter_read||parameter_ready)&&(!dma_shift_read||shift_committed==7'd64);

    function automatic [16:0] bank_word(input [16:0] addr);
        begin
            @REMAP@
        end
    endfunction
    wire [16:0] host_bank_word=bank_word(host_cmd_addr);
    wire [16:0] joined_bank_word=bank_word(joined_cmd_addr[18:2]);
    wire joined_address_valid=joined_cmd_addr[31:19]==13'h1400;
    wire joined_load_read=joined_cmd_dma&&joined_cmd_read&&joined_address_valid&&
                          joined_cmd_addr[1:0]==2'b00&&
                         ((joined_cmd_addr[18:2]>=17'd32768&&joined_cmd_addr[18:2]<17'd41216)||
                          (joined_cmd_addr[18:2]>=17'd59392&&joined_cmd_addr[18:2]<17'd59456));
    wire joined_fire;
    wire host_dual_candidate=host_stream&&joined_fire&&joined_load_read;
    wire host_bank_conflict=host_dual_candidate&&host_bank_word[16:12]==joined_bank_word[16:12];
    wire host_dual=host_dual_candidate&&!host_bank_conflict;
"""
    if mode=='N':
        ready = "(ld_word<17'd36864)?parameter_committed>=14'd4096:\n" \
                "                         (ld_word<17'd40960)?parameter_committed>=14'd8192:parameter_committed==14'd8448"
        mapping = 'bank_word=addr;'
    else:
        ready = 'ld_word[13:0]<parameter_committed'
        mapping = """if(addr[16:13]==4'b0100)
                bank_word={addr[16:13],addr[0],addr[11:1],addr[12]};
            else bank_word=addr;"""
    declarations=declarations.replace('@PARAMETER_READY@',ready).replace('@REMAP@',mapping)
    text=replace(text,'    reg input_background_phase;','    reg input_background_phase;'+declarations)
    text=replace(text,'input_background_phase&&host_input_next;',
                 "input_background_phase&&parameter_committed==14'd8448&&shift_committed==7'd64&&host_input_next;")
    text=replace(text,'host_cmd_valid&&!host_background;','host_cmd_valid&&!(host_background||host_stream);')
    text=replace(text,'staged_dma_ready&&dma_input_eligible;', 'staged_dma_ready&&dma_input_eligible&&dma_load_eligible;')
    text=replace(text,'.b_cmd_valid(ld_cmd_valid&&dma_input_eligible),',
                      '.b_cmd_valid(ld_cmd_valid&&dma_input_eligible&&dma_load_eligible),')
    text=replace(text,'wire joined_fire=joined_cmd_valid&&joined_cmd_ready;',
                      'assign joined_fire=joined_cmd_valid&&joined_cmd_ready;')
    text=replace(text,'assign host_cmd_ready=idle&&(!host_background||!joined_cmd_valid);',
                      'assign host_cmd_ready=(idle&&(!(host_background||host_stream)||!joined_cmd_valid))||host_dual;')
    text=replace(text,'''    wire joined_address_valid=joined_cmd_addr[31:19]==13'h1400;
    wire physical_accept=host_fire||(joined_fire&&joined_address_valid);
    wire live_we=host_fire?!host_cmd_read:!joined_cmd_read;
    wire [16:0] live_addr=host_fire?host_cmd_addr:joined_cmd_addr[18:2];
    wire [31:0] live_wdata=host_fire?host_cmd_wdata:joined_cmd_wdata;
    wire [3:0] live_wmask=host_fire?host_cmd_wmask:joined_cmd_wmask;
    wire physical_write=physical_accept&&live_we;''','''    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            parameter_committed<=0;
            shift_committed<=0;
        end else if((host_fire&&host_input_word&&host_cmd_addr==0)||
                    (joined_fire&&!joined_cmd_dma&&!joined_cmd_read&&joined_cmd_addr==32'ha007ff30)) begin
            parameter_committed<=0;
            shift_committed<=0;
        end else if(host_fire) begin
            if(host_parameter_next) parameter_committed<=parameter_committed+14'd1;
            if(host_shift_next) shift_committed<=shift_committed+7'd1;
        end
    end
    wire host_primary=host_fire&&!host_dual;
    wire physical_accept=host_primary||(joined_fire&&joined_address_valid);
    wire live_we=host_primary?!host_cmd_read:!joined_cmd_read;
    wire [16:0] live_addr=host_primary?host_bank_word:joined_bank_word;
    wire [31:0] live_wdata=host_fire?host_cmd_wdata:joined_cmd_wdata;
    wire [3:0] live_wmask=host_fire?host_cmd_wmask:joined_cmd_wmask;
    wire physical_write=(physical_accept&&live_we)||host_dual;''')
    text=replace(text,'    kwt_shared_sram_sm40 memory(','    kwt_bank_overlap_sram memory(')
    text=replace(text,'        .addr(physical_accept?live_addr:held_addr),',
        '        .addr(physical_accept?live_addr:held_addr),.stream_write(host_dual),.stream_addr(host_bank_word),')
    return text


def memory():
    text=(ROOT/'rtl/public_encoder/kwt_shared_sram_sm40.sv').read_text()
    text=replace(text,'module kwt_shared_sram_sm40(','module kwt_bank_overlap_sram(')
    text=replace(text,'    input wire [16:0] addr,','    input wire [16:0] addr,stream_addr,\n    input wire stream_write,')
    text=replace(text,'if(en) read_bank','if(en&&!we) read_bank')
    text=replace(text,'    for(genvar bank=0;bank<32;bank=bank+1) begin: banks',
        '''    for(genvar bank=0;bank<32;bank=bank+1) begin: banks
        wire stream_hit;
        if(bank==8||bank==9||bank==10||bank==14) begin: stream_bank
            assign stream_hit=stream_write&&stream_addr[16:12]==5'(bank);
        end else begin: primary_only
            assign stream_hit=1'b0;
        end
        wire bank_write=we||stream_hit;
        wire [11:0] bank_addr=stream_hit?stream_addr[11:0]:addr[11:0];''')
    text=replace(text,'.CLK(clk),.CEN(!(en&&addr[16:12]==bank)),',
                      ".CLK(clk),.CEN(!((en&&addr[16:12]==5'(bank))||stream_hit)),")
    text=replace(text,'.GWEN(~we),.WEN(~{{8{we&&wmask[half*2+1]}},{8{we&&wmask[half*2]}}}),',
                      '.GWEN(~bank_write),.WEN(~{{8{bank_write&&wmask[half*2+1]}},{8{bank_write&&wmask[half*2]}}}),')
    return replace(text,'.A(addr[11:0]),','.A(bank_addr),')


def bench(text,mode):
    text=replace(text,
        'for(integer a=32768;a<=parameter_end;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end',
        '''for(integer a=32768;a<=parameter_end;a=a+1) begin
                    if(current_mode&&a==32768+@FIRST@) begin put_word(131021,layer+1);host_control=host_control+1;end
                    put_word(a,host_buffer[a]);host_payload=host_payload+1;
                end'''.replace('@FIRST@',str(MODES[mode])))
    text=replace(text,'put_word(131021,layer+1);host_control=host_control+1;res_time_parameter_injection_end=cycles-start_cycle;',
        'if(!current_mode) begin put_word(131021,layer+1);host_control=host_control+1;end\n'
        '                res_time_parameter_injection_end=cycles-start_cycle;')
    text=replace(text,'''        if(dut.shared_memory.memory.en) begin
            if(dut.shared_memory.memory.we) shared_write32<=shared_write32+1;
            else shared_read32<=shared_read32+1;
        end''','''        if(dut.shared_memory.memory.en&&!dut.shared_memory.memory.we) shared_read32<=shared_read32+1;
        if((dut.shared_memory.memory.en&&dut.shared_memory.memory.we)||dut.shared_memory.host_dual)
            shared_write32<=shared_write32+1;''')
    text=replace(text,'integer staged_late_words=0,staged_mac_words=0,staged_last_input=0,staged_group_blocked=0;',
        'integer staged_late_words=0,staged_mac_words=0,staged_last_input=0,staged_group_blocked=0;\n'
        '    integer bank_dual=0,bank_conflict=0,bank_wait=0;')
    text=replace(text,'staged_late_words=0;staged_mac_words=0;staged_last_input=0;staged_group_blocked=0;',
        'staged_late_words=0;staged_mac_words=0;staged_last_input=0;staged_group_blocked=0;\n'
        '            bank_dual=0;bank_conflict=0;bank_wait=0;')
    text=replace(text,'''            if(dut.shared_memory.host_fire&&dut.shared_memory.joined_fire)
                $fatal(1,"STAGED_SHARED_PORT_DOUBLE_ACCEPT");''','''            if(dut.shared_memory.host_fire&&dut.shared_memory.joined_fire&&!dut.shared_memory.host_dual)
                $fatal(1,"BANK_UNQUALIFIED_DOUBLE_ACCEPT");
            if(dut.shared_memory.host_dual) begin
                if(!dut.shared_memory.host_fire||!dut.shared_memory.joined_fire||!dut.shared_memory.joined_load_read||
                    dut.shared_memory.host_bank_word[16:12]==dut.shared_memory.joined_bank_word[16:12])
                    $fatal(1,"BANK_PHYSICAL_PORT_CONFLICT");
                bank_dual=bank_dual+1;
            end
            if(dut.shared_memory.host_bank_conflict)bank_conflict=bank_conflict+1;
            if(dut.shared_memory.ld_cmd_valid&&!dut.shared_memory.dma_load_eligible)bank_wait=bank_wait+1;''')
    return replace(text,'        $display("Q16_STAGED_COUNTS',
        '        $display("BANK_OVERLAP_COUNTS dual=%0d same_bank=%0d uncommitted=%0d",bank_dual,bank_conflict,bank_wait);\n'
        '        $display("Q16_STAGED_COUNTS')


def materialize(mode):
    name=variant(mode)
    report=ROOT/'reports/optimization'/name
    selected=ROOT/'constraints/ffn_selected.json'
    cfg=json.loads(selected.read_text(encoding='utf-8'))
    assert cfg['variant']==PARENT
    report.mkdir(parents=True,exist_ok=True)
    (report/'baseline-selected.json').write_bytes(selected.read_bytes())
    root=ROOT/'build/optimization'
    old=root/'complete_soc'/PARENT
    out=root/'complete_soc'/name
    source=root/'rtl_sources'/name
    # Both research variants use the accepted compute and firmware bytes.
    copy_tree(ROOT/cfg['source_snapshot'],source)
    def specialize(text):
        return text.replace(cfg['firmware'],'@FIRMWARE@').replace(PARENT,name).replace('@FIRMWARE@',cfg['firmware'])
    out.mkdir(parents=True,exist_ok=True)
    for path in old.iterdir():
        if not path.is_file() or path.suffix not in ('.sv','.v','.svh','.f','.json','.sh'):
            continue
        if path.name in ('gate_tb.sv','gate_files.f','compile_gate.sh'):
            continue
        text=specialize(path.read_text(encoding='utf-8'))
        if path.name=='kwt_shared_dma_icb_sm40.sv':
            text=controller(text,mode)+'\n'+memory()
        elif path.name=='complete_soc_tb.sv':
            text=bench(text,mode)
        elif path.name=='configuration.json':
            meta=json.loads(text)
            meta.update(shared_bank_overlap=mode,parameter_stream_first_words=MODES[mode])
            text=json.dumps(meta,indent=2)+'\n'
        write_text(out/path.name,text)
    (out/'eda').mkdir(exist_ok=True)
    for path in (old/'eda').glob('*.tcl'):
        if path.name!='pr1_assessment.tcl':
            write_text(out/'eda'/path.name,specialize(path.read_text()))
    copy_tree(old/'packed_inputs',out/'packed_inputs')
    manifest=json.loads((ROOT/cfg['adaptive_manifest']).read_text())
    manifest.update(variant=name,parent_variant=PARENT,purpose='experiment',selected_model=mode,
                    parent=dict(variant=PARENT,configuration=cfg,firmware=cfg['firmware'],
                                source_snapshot=cfg['source_snapshot'],profile=cfg['implementation']))
    manifest['changes'].update(shared_bank_overlap=mode,parameter_stream_first_words=MODES[mode])
    manifest['hardware'].append('bank_overlap_'+mode)
    folder=ROOT/'constraints'/name/'candidates'
    folder.mkdir(parents=True,exist_ok=True)
    (folder/(name+'.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    assert all(p.read_bytes()==(ROOT/cfg['source_snapshot']/p.relative_to(source)).read_bytes()
               for p in source.rglob('*') if p.is_file())


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('modes',nargs='+',choices=MODES)
    for mode in parser.parse_args().modes:
        materialize(mode)
