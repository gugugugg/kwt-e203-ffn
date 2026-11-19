"""Materialize and exercise the selected packed-input R3O stream design."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PARENT, NAME = 'ffn_sr_r3o', 'ffn_r3o_stream'
REPORT = ROOT / 'reports/optimization' / NAME
SOURCE = ROOT / 'build/optimization/rtl_sources' / NAME
SOC = ROOT / 'build/optimization/complete_soc' / NAME
RTL_TEST = ROOT / 'build/optimization/rtl' / NAME
sys.path[:0] = [str(ROOT / 'scripts/sr_transport_next'), str(ROOT / 'scripts/sr_pr1')]
from candidate import endpoint, engine, observe_handoffs
from prepare import replace


def extend_fast(text):
    return replace(text, "(joined_cmd_addr>=32'ha0020000)&&(joined_cmd_addr<32'ha0028800)",
        "(((joined_cmd_addr>=32'ha0020000)&&(joined_cmd_addr<32'ha0028800))||"
        "((joined_cmd_addr>=32'ha0000000)&&(joined_cmd_addr<32'ha0003180)))")


def packed_core(text):
    text = replace(text, 'output wire load_ready,load_capacity_ready,',
                   'output wire load_ready,load_capacity_ready,input_pair_capacity_ready,')
    text = replace(text, '    reg [1:0] input_write_row;\n    reg input_write_generation,input_read_generation;',
        """    // Packed and scalar PIO writes follow the same k-major three-row order.
    reg [8:0] input_write_cursor;
    reg input_read_generation;
    function automatic [8:0] advance_input_cursor(input [8:0] cursor);
        reg [6:0] index;
        begin
            index = cursor[8:2];
            if(cursor[1:0]==2'd2) advance_input_cursor={index+7'd1,2'd0};
            else advance_input_cursor={index,cursor[1:0]+2'd1};
        end
    endfunction
    wire [8:0] input_high_cursor=advance_input_cursor(input_write_cursor);
    wire [13:0] input_window_limit=(14'({1'b0,row})+14'd6)<<6;""")
    text = replace(text, 'wire input_loading=loading&&(load_kind==0);',
                   "wire input_loading=loading&&(load_kind==0)&&(load_addr==16'(input_count));")
    text = replace(text, """        wire write_enable=input_loading&&(input_write_row==2'(ap_row));
        wire read_enable=ap_input_read;
        wire memory_enable=write_enable||read_enable;
        wire [6:0] memory_addr=write_enable?{input_write_generation,load_addr[5:0]}:
                                            {input_read_generation,request_inner};""",
        """        wire low_write=input_loading&&(input_write_cursor[1:0]==2'(ap_row));
        wire high_write=input_loading&&(load_count==2)&&(input_high_cursor[1:0]==2'(ap_row));
        wire write_enable=low_write||high_write;
        wire read_enable=ap_input_read;
        wire memory_enable=write_enable||read_enable;
        wire [6:0] memory_addr=write_enable?(high_write?input_high_cursor[8:2]:input_write_cursor[8:2]):
                                            {input_read_generation,request_inner};""")
    text = replace(text, '.addr(memory_addr),.wdata(load_data),.rdata(ap_input_rdata[ap_row*16+:16]));',
                   '.addr(memory_addr),.wdata(high_write?load_high:load_data),.rdata(ap_input_rdata[ap_row*16+:16]));')
    text = replace(text, "({1'b0,input_count}<((14'({1'b0,row})+14'd6)<<6))&&!ap_input_read))));",
        """({1'b0,input_count}<input_window_limit)&&!ap_input_read))));
    assign input_pair_capacity_ready=(input_count<6335)&&
        (({1'b0,input_count}+14'd1)<input_window_limit);""")
    old_reset = 'input_write_row<=0;input_write_generation<=0;input_read_generation<=0;'
    if text.count(old_reset) != 2:
        raise RuntimeError('R3O cursor reset points differ')
    text = text.replace(old_reset, 'input_write_cursor<=0;input_read_generation<=0;')
    text = replace(text, """                    if(load_addr[5:0]==6'd63)begin
                        if(input_write_row==2)begin
                            input_write_row<=0;input_write_generation<=!input_write_generation;
                        end else input_write_row<=input_write_row+2'd1;
                    end""", """                    input_write_cursor<=(load_count==2)?
                        advance_input_cursor(input_high_cursor):input_high_cursor;""")
    return text


def packed_wrapper(text):
    text = replace(text, 'wire ld_error_sticky,dma_core_load_capacity_ready;',
        """wire ld_error_sticky,core_load_capacity_ready,input_pair_capacity_ready;
wire dma_core_load_capacity_ready=core_load_capacity_ready&&
    ((load_kind!=0)||input_pair_capacity_ready);""")
    # Declare the assignment after the load-kind declaration for Verilator and VCS.
    text = replace(text, """wire dma_core_load_capacity_ready=core_load_capacity_ready&&
    ((load_kind!=0)||input_pair_capacity_ready);""", "wire dma_core_load_capacity_ready;")
    marker = '    reg linear_mode,pack_pending;'
    text = replace(text, marker, marker + """
    assign dma_core_load_capacity_ready=core_load_capacity_ready&&
        ((load_kind!=0)||input_pair_capacity_ready);""")
    text = replace(text, """        ((pio_cmd_addr==8'h10&&load_address<16'd6336)||
         (pio_cmd_addr==8'h30&&load_address<16'd6335))&&!dma_core_load_capacity_ready;""",
        """        ((pio_cmd_addr==8'h10&&load_address<16'd6336&&!core_load_capacity_ready)||
         (pio_cmd_addr==8'h30&&load_address<16'd6335&&!dma_core_load_capacity_ready));""")
    text = replace(text, "wire packed_load=fire&&full_write&&(pio_cmd_addr==8'h30)&&core_load_ready&&",
        """wire packed_load=fire&&full_write&&(pio_cmd_addr==8'h30)&&core_load_ready&&
        ((load_kind!=0)||input_pair_capacity_ready)&&""")
    text = replace(text, '.load_capacity_ready(dma_core_load_capacity_ready),',
        '.load_capacity_ready(core_load_capacity_ready),.input_pair_capacity_ready(input_pair_capacity_ready),')
    text = replace(text, '.load_pair(packed_load&&load_kind!=0&&load_kind!=5)',
                   '.load_pair(packed_load&&load_kind!=5)')
    text = replace(text, 'packed_load&&load_kind!=0&&load_kind!=5)?16',
                   'packed_load&&load_kind!=5)?16')
    return replace(text, 'pack_pending<=(load_kind==0)||(load_kind==5);', 'pack_pending<=load_kind==5;')


def stream_engine(text):
    text = engine(text, 'PRF_W1')
    return replace(text, "pd_count==2&&address>=32'ha0020000&&address<32'ha0028800&&",
        """pd_count==2&&((address>=32'ha0020000&&address<32'ha0028800)||
                        (address>=32'ha0000000&&address<32'ha0003180))&&""")


def images():
    base = ROOT / 'build/optimization/ffn_ar_area/frozen/images'
    dest = SOC / 'packed_inputs'
    dest.mkdir(exist_ok=True)
    for case in range(1,24,2):
        raw = (base / ('task_%02d_shared.hex' % case)).read_text().splitlines()[:3168]
        samples = [half for word in map(lambda x:int(x,16),raw) for half in (word&65535,word>>16)]
        stream = [samples[group*192+row*64+k] for group in range(33)
                  for k in range(64) for row in range(3)]
        data = [lo|hi<<16 for lo,hi in zip(stream[::2],stream[1::2])]
        (dest / ('task_%02d_packed.hex' % case)).write_text(''.join('%08x\n'%word for word in data))


def bench(text):
    anchor = '    task load_words(input integer kind,input integer count);'
    text = replace(text, anchor, """    function automatic [15:0] input_stream_word(input integer at);
        integer base, offset;
        begin
            base=(at/192)*192;
            offset=at%192;
            input_stream_word=inputs[base+(offset%3)*64+offset/3];
        end
    endfunction
""" + anchor)
    for index in ('address','address+1','at','at+1'):
        text = text.replace('inputs['+index+']','input_stream_word('+index+')')
    old = 'if(stream_input&&double_input)input_block(0,row_group);'
    text = replace(text,old,
        """if(stream_input&&double_input)input_block(0,mixed_access?2*row_group:row_group);""")
    text = replace(text, 'else if(block_row+row_group<99)input_block',
                   'else if(block_row+row_group<99&&(!mixed_access||block_row!=0))input_block')
    text = replace(text, 'at%17==0||at+1==last', 'at%17==0||at==190||at+1==last')
    marker = '    kwt_icb_encoder dut(.*);'
    text = replace(text, marker, marker + '''
    always @(posedge clk)
        if(mixed_access&&dut.core.input_loading&&dut.core.load_count==2&&dut.core.input_count==191)
            $display("R3O_STREAM_CROSS_GENERATION layer=%0d",layer);
''')
    return text


def materialize():
    selection = json.loads((REPORT / 'model-selection.json').read_text())
    if not selection['passed'] or selection['selected'] != 'M3':
        raise RuntimeError('Only the selected M3 can materialize')
    previous = ROOT / 'constraints/ffn_selected.json'
    cfg = json.loads(previous.read_text())
    if cfg['variant'] != PARENT:
        raise RuntimeError('R3O is not the current release')
    (REPORT/'baseline-selected.json').write_bytes(previous.read_bytes())
    if not SOURCE.exists():
        shutil.copytree(str(ROOT/cfg['source_snapshot']), str(SOURCE))
    for relative, transform in [('encoder/kwt_encoder.sv',packed_core),
                               ('encoder_bus/kwt_icb_encoder.sv',packed_wrapper),
                               ('encoder/kwt_ld_engine.sv',stream_engine)]:
        (SOURCE/relative).write_text(transform((ROOT/cfg['source_snapshot']/relative).read_text()))
    SOC.mkdir(exist_ok=True)
    old = SOC.with_name(PARENT)
    for path in old.iterdir():
        if not path.is_file() or path.suffix not in ('.sv','.v','.svh','.f','.json','.sh'):
            continue
        text = path.read_text().replace(PARENT,NAME)
        text = text.replace('build/optimization/firmware/'+NAME,cfg['firmware'])
        if path.name == 'kwt_shared_dma_icb_sm40.sv':
            text = extend_fast(endpoint(text,'PRF_W1'))
        elif path.name == 'complete_soc_tb.sv':
            text = observe_handoffs(text)
            text = replace(text,'            @(negedge clk);\n            start_cycle=cycles;',
                """            if(current_mode)begin
                filename=$sformatf("build/optimization/complete_soc/ffn_r3o_stream/packed_inputs/task_%02d_packed.hex",current_case);
                $readmemh(filename,host_buffer,0,3167);
            end
            @(negedge clk);
            start_cycle=cycles;""")
        elif path.name == 'configuration.json':
            record = json.loads(text)
            record['input_layout'] = 'group3_inner_major'
            text = json.dumps(record,indent=2)+'\n'
        (SOC/path.name).write_text(text,newline='\n')
    eda=SOC/'eda'
    eda.mkdir(exist_ok=True)
    for path in (old/'eda').glob('*.tcl'):
        (eda/path.name).write_text(path.read_text().replace(PARENT,NAME),newline='\n')
    manifest = json.loads((ROOT/cfg['adaptive_manifest']).read_text())
    manifest.update(variant=NAME,parent_variant=PARENT,purpose='experiment',input_layout='group3_inner_major')
    manifest['parent'] = dict(variant=PARENT,configuration=cfg,firmware=cfg['firmware'],
                              source_snapshot=cfg['source_snapshot'],profile=cfg['implementation'])
    manifest['hardware'] += ['BIDIR','PAIR_IN','F_IN']
    profile = ROOT/'constraints'/NAME/'candidates'
    profile.mkdir(parents=True,exist_ok=True)
    (profile/(NAME+'.json')).write_text(json.dumps(manifest,indent=2)+'\n')
    images()
    RTL_TEST.mkdir(exist_ok=True)
    (RTL_TEST/'loading_dma_tb.sv').write_text(bench(
        (RTL_TEST.with_name(PARENT)/'loading_dma_tb.sv').read_text()))


def run(command, log):
    with log.open('w') as stream:
        subprocess.run([str(x) for x in command],cwd=str(ROOT),stdout=stream,
                       stderr=subprocess.STDOUT,check=True)


def develop(only=None):
    files=[ROOT/'rtl'/name for name in ('kwt_sram16x1024_model.sv','kwt_spmem16.sv','kwt_requantize.sv')]
    files+=sorted((SOURCE/'encoder').glob('*.sv'))+sorted((SOURCE/'encoder_bus').glob('*.sv'))
    files += [RTL_TEST/'loading_dma_tb.sv']
    target=RTL_TEST/'verilator'
    run(['verilator_bin.exe','--cc','--exe','--main','--timing','--compiler','gcc','-Wno-fatal',
         '--top-module','row_reuse_tb','--output-split','20000','--Mdir',target,
         '-I'+str(SOURCE/'encoder')]+files,REPORT/'local-elaborate.log')
    run(['mingw32-make','-C',target,'-f','Vrow_reuse_tb.mk',
         'VERILATOR_ROOT=E:/xpian/tools/oss-cad-suite/share/verilator',
         'PYTHON3=E:/xpian/.venv/Scripts/python.exe','-j','4'],REPORT/'local-build.log')
    scenarios=[]
    vectors=ROOT/'build/optimization/rtl/ffn_ara_SR/native_vectors'
    for label,options in [('actual12',[]),('mixed_paused',['+MIXED']),('single',['+SINGLE'])]:
        if only is not None and label != only:
            continue
        log=REPORT/('local-'+label+'.log')
        run([target/'Vrow_reuse_tb.exe','+VECTOR_DIR='+str(vectors),
             '+ROW_GROUP=3','+STREAM','+DOUBLE']+options,log)
        result=log.read_text()
        if result.count('FFN_NEXT_RTL_PASS layer=')!=12 or 'FFN_NEXT_RTL_ALL_PASS' not in result:
            raise RuntimeError('Incomplete local golden result: '+label)
        if label=='mixed_paused' and result.count('R3O_STREAM_CROSS_GENERATION')!=12:
            raise RuntimeError('Mixed regression did not cover the input generation boundary')
        scenarios.append(label)
        print('R3O_STREAM_RTL_PASS',label,flush=True)
    if only is not None:
        previous = json.loads((REPORT/'local-acceptance.json').read_text())
        scenarios = previous['scenarios']
    (REPORT/'local-acceptance.json').write_text(json.dumps(dict(passed=True,scenarios=scenarios,
        cases_per_scenario=12,outputs_per_case=25344,lanes=48,weight_banks=16,mixed_crosses_input_generation=True),indent=2)+'\n')


if __name__=='__main__':
    if sys.argv[1] == 'mixed':
        original = RTL_TEST.with_name(PARENT) / 'loading_dma_tb.sv'
        (RTL_TEST/'loading_dma_tb.sv').write_text(bench(original.read_text()))
        develop('mixed_paused')
    else:
        {'materialize':materialize,'develop':develop}[sys.argv[1]]()
