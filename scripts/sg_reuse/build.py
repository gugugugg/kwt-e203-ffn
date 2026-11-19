"""Materialize the selected S+G slot-reuse successor."""
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
NAME, PARENT = 'ffn_sg_reuse', 'ffn_ps_SG'
REPORT = EXPERIMENT = ROOT / 'reports/optimization' / NAME
BUILD = ROOT / 'build/optimization'
SOURCE = BUILD / 'rtl_sources' / NAME
SOC = BUILD / 'complete_soc' / NAME
RTL_TEST = BUILD / 'rtl' / NAME
spec = importlib.util.spec_from_file_location('sg_builder', ROOT / 'scripts/p2_startup/build.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
copy_tree, replace, write_text = base.copy_tree, base.replace, base.write_text


def queue(src):
    src = replace(src, '    input wire [2:0] valid_rows,', '''    input wire write_transposed,query_reuse,next_query_reuse,
    input wire [2:0] valid_rows,''')
    src = replace(src, '''    assign generation_empty=generation_state[query_generation]==EMPTY;
    assign next_generation_empty=generation_state[!query_generation]==EMPTY;''', '''    reg [1:0] reuse_reserved;
    assign generation_empty=generation_state[query_generation]==EMPTY||
        (query_reuse&&generation_state[query_generation]==READY&&!reuse_reserved[query_generation]);
    assign next_generation_empty=generation_state[!query_generation]==EMPTY||
        (next_query_reuse&&generation_state[!query_generation]==READY&&!reuse_reserved[!query_generation]);''')
    src = replace(src, '    wire [1:0] issue_row=next_item[9:8];', '''    wire [1:0] issue_row=next_item[9:8];
    wire transposed_read=next_item[14:11]==0;
    wire [1:0] read_bank_row=issue_row^(transposed_read?next_item[3:2]:2'b00);''')
    src = replace(src, "&&(next_item[7:0]!=8'hff)&&",
                  "&&(next_item[7:0]!=8'hff)&&(!transposed_read||next_item[1:0]!=2'd3)&&")
    src = replace(src, 'issue&&(issue_row==2\'(ROW))&&', 'issue&&(read_bank_row==2\'(ROW))&&')
    src = replace(src, '        wire [6:0] address=write_en?{compute_generation,write_address}:{issue_generation,read_quartet};', '''        wire [5:0] write_offset=write_transposed?{2'(ROW)^write_address[1:0],write_address[5:2]}:write_address;
        wire [5:0] read_offset=transposed_read?{issue_row,next_item[7:4]}:read_quartet;
        wire [6:0] address=write_en?{compute_generation,write_offset}:{issue_generation,read_offset};''')
    src = replace(src, '    generate for(genvar bank=0;bank<16;bank=bank+1)begin: row_stash', '''    wire [1:0] row_xor=write_transposed?write_address[1:0]:2'b00;
    wire [255:0] switched_rows,bank_words;
    assign switched_rows=row_xor[0]?{write_words[191:128],write_words[255:192],
                                    write_words[63:0],write_words[127:64]}:write_words;
    assign bank_words=row_xor[1]?{switched_rows[127:0],switched_rows[255:128]}:switched_rows;
    generate for(genvar bank=0;bank<16;bank=bank+1)begin: row_stash''')
    src = replace(src, '.wdata(write_words[bank*16+:16])', '.wdata(bank_words[bank*16+:16])')
    src = src.replace('generation_state[0]<=EMPTY;generation_state[1]<=EMPTY;',
                      'generation_state[0]<=EMPTY;generation_state[1]<=EMPTY;reuse_reserved<=0;')
    src = replace(src, '''            if(retire_group)generation_state[item[10]]<=EMPTY;
            if(reserve)generation_state[reserve_generation]<=FILL;''', '''            if(retire_group)begin
                generation_state[item[10]]<=reuse_reserved[item[10]]?FILL:EMPTY;
                reuse_reserved[item[10]]<=0;
            end
            if(reserve)begin
                if(generation_state[reserve_generation]==READY&&
                   !(retire_group&&item[10]==reserve_generation))
                    reuse_reserved[reserve_generation]<=1;
                else generation_state[reserve_generation]<=FILL;
            end''')
    return replace(src, 'pending_row<=issue_row;', 'pending_row<=read_bank_row;')


def compute(src):
    src = replace(src, '    wire iw_run=(state==B_MAC)&&!iw_request_done;', '''    wire reuse_block;
    wire iw_run=(state==B_MAC)&&!iw_request_done&&!reuse_block;''')
    src = replace(src, '    wire iw_request_tail=iw_join_inflight?(row==7\'d92):(row==7\'d96);', '''    wire iw_request_tail=iw_join_inflight?(row==7'd92):(row==7'd96);
    // Use retired words at the start of the cycle, excluding held and pending.
    wire would_emit=(iw_request_inner==64)||
        (IW_FUSED&&iw_request_inner==0&&(iw_request_tile!=0||iw_join_first));
    wire retire_second=iw_join_first?(row==7'd12):
        (iw_join_inflight?(row==7'd8):(row==7'd12));
    wire retire_first=iw_join_first?(row==7'd8):
        (iw_join_inflight?(row==7'd4):(row==7'd8));
    wire [3:0] retire_tile=(iw_request_inner==64)?iw_request_tile:iw_request_tile-4'd1;
    wire old_slot_released=(item[14:10]>5'(retire_second))||
        (item[14:10]==5'(retire_second)&&item[9:6]>retire_tile);
    assign reuse_block=(state==B_MAC)&&would_emit&&(retire_first||retire_second)&&!old_slot_released;''')
    src = replace(src, '            iw_join_first<=iw_join;',
                  '            if(!reuse_block)iw_join_first<=iw_join;')
    return replace(src, '        .compute_generation(quant_generation),', '''        .compute_generation(quant_generation),.write_transposed(wp_boot),
        .query_reuse(row==7'd8||row==7'd12),.next_query_reuse(row==7'd4||row==7'd8),''')


def shared(src):
    first = src.index('    wire host_dual_candidate=')
    stop = src.index('    wire host_background=', first)
    dual = src[first:stop]
    src = src[:first] + src[stop:]
    return replace(src, '    wire host_foreground=', '''    wire joined_weight_read=joined_load_read&&
        joined_cmd_addr[18:2]>=17'd32768&&joined_cmd_addr[18:2]<17'd40960;
''' + dual.replace('host_stream&&joined_fire&&(joined_load_read||joined_startup_input)',
                   'joined_fire&&((host_stream&&(joined_load_read||joined_startup_input))||\n'
                   '                     (host_background&&joined_weight_read))') + '    wire host_foreground=')


def frontend(src):
    src = replace(src, 'soft_reset,input_ready,output_ready,', 'soft_reset,input_ready,output_ready,layer_ready,')
    src = replace(src, '    wire busy,done,dma_error;', '''    wire busy,done,dma_error;
    localparam [2:0] CH_IDLE=0,CH_INPUT=1,CH_LAYER=2,CH_KIND=3,CH_ADDR=4,CH_WEIGHT=5;
    reg [2:0] chain;
    reg chain_address,chain_words,chain_pending,chain_error;
    wire chain_pio=chain==CH_LAYER||chain==CH_KIND||chain==CH_ADDR;
    wire chain_busy=chain!=CH_IDLE;
    wire chain_enabled=chain==CH_INPUT&&chain_address&&chain_words&&!busy;
    wire [7:0] chain_pio_address=chain==CH_LAYER?8'h18:chain==CH_KIND?8'h08:8'h0c;
    wire [31:0] chain_pio_data=chain==CH_ADDR?32'd0:32'd1;''')
    src = replace(src, '||!busy);', '||!(busy||chain_busy));')
    src = replace(src, '(cpu_cmd_wdata==1)||(cpu_cmd_wdata==2);',
                  '(cpu_cmd_wdata==1)||(cpu_cmd_wdata==2)||\n        (cpu_cmd_wdata==3&&words==32\'d256);')
    src = replace(src, '    wire launch=csr_fire', '    wire cpu_launch=csr_fire')
    src = replace(src, "&&cpu_cmd_addr==8'h48&&!busy&&valid_command;",
                  "&&cpu_cmd_addr==8'h48&&!(busy||chain_busy)&&valid_command;")
    src = replace(src, '''    wire [31:0] status={29'd0,dma_error,done,busy};
    assign error_sticky=dma_error;''', '''    wire launch=cpu_launch||chain==CH_WEIGHT;
    wire [31:0] status={29'd0,dma_error||chain_error,done,busy||chain_busy};
    assign error_sticky=dma_error||chain_error;''')
    src = replace(src, '    assign cpu_cmd_ready=csr?csr_ready:(csr_slot&&a_cmd_ready);',
                  '    assign cpu_cmd_ready=csr?csr_ready:(!chain_pio&&csr_slot&&a_cmd_ready);')
    src = replace(src, '    assign cpu_rsp_valid=csr_rsp_valid||a_rsp_valid;',
                  '    assign cpu_rsp_valid=csr_rsp_valid||(!chain_pio&&a_rsp_valid);')
    src = replace(src, '''        .a_cmd_valid(cpu_cmd_valid&&!csr&&csr_slot),.a_cmd_ready(a_cmd_ready),.a_cmd_addr(cpu_cmd_addr),
        .a_cmd_read(cpu_cmd_read),.a_cmd_wdata(cpu_cmd_wdata),.a_cmd_wmask(cpu_cmd_wmask),
        .a_rsp_valid(a_rsp_valid),.a_rsp_ready(cpu_rsp_ready&&!csr_rsp_valid),.a_rsp_rdata(a_rsp_data),.a_rsp_err(a_rsp_err),''', '''        .a_cmd_valid(chain_pio?!chain_pending:cpu_cmd_valid&&!csr&&csr_slot),
        .a_cmd_ready(a_cmd_ready),.a_cmd_addr(chain_pio?chain_pio_address:cpu_cmd_addr),
        .a_cmd_read(!chain_pio&&cpu_cmd_read),.a_cmd_wdata(chain_pio?chain_pio_data:cpu_cmd_wdata),
        .a_cmd_wmask(chain_pio?4'hf:cpu_cmd_wmask),
        .a_rsp_valid(a_rsp_valid),.a_rsp_ready(chain_pio||(cpu_rsp_ready&&!csr_rsp_valid)),
        .a_rsp_rdata(a_rsp_data),.a_rsp_err(a_rsp_err),''')
    src = replace(src, '.direction(cpu_cmd_wdata==2),', '.direction(cpu_launch&&cpu_cmd_wdata==2),')
    src = replace(src, '8\'h48:if(busy||!valid_command)', '8\'h48:if(busy||chain_busy||!valid_command)')
    return replace(src, 'endmodule', '''    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            chain<=CH_IDLE;chain_address<=0;chain_words<=0;chain_pending<=0;chain_error<=0;
        end else if(soft_reset)begin
            chain<=CH_IDLE;chain_address<=0;chain_words<=0;chain_pending<=0;chain_error<=0;
        end else begin
            if(cpu_launch)begin
                chain_error<=0;
                if(cpu_cmd_wdata==3)begin
                    chain<=CH_INPUT;chain_address<=0;chain_words<=0;
                end
            end
            if(chain==CH_INPUT)begin
                if(csr_fire&&!cpu_cmd_read&&cpu_cmd_wmask==4'hf)begin
                    if(cpu_cmd_addr==8'h40)chain_address<=1;
                    if(cpu_cmd_addr==8'h44)chain_words<=1;
                end
                if(chain_enabled)begin
                    if(dma_error)chain<=CH_IDLE;
                    else if(layer_ready)chain<=CH_LAYER;
                end
            end
            if(chain_pio)begin
                if(!chain_pending&&a_cmd_ready)chain_pending<=1;
                if(a_rsp_valid)begin
                    chain_pending<=0;
                    if(a_rsp_err)begin chain_error<=1;chain<=CH_IDLE;end
                    else chain<=chain+3'd1;
                end
            end
            if(chain==CH_WEIGHT)chain<=CH_IDLE;
        end
    end
endmodule''')


def firmware(src):
    start = src.index('    rc=transport_load(base,input,256);')
    end = src.index('    return wait_state(d,64u);', start)
    return src[:start] + '''    fence_io();
    wr_base(base,0x40u,(uint32_t)(uintptr_t)input);wr_base(base,0x44u,256u);
    fence_io();wr_base(base,0x48u,3u);fence_io();
    wr_base(base,0x40u,(uint32_t)(uintptr_t)parameters);wr_base(base,0x44u,8192u);
    fence_io();
    if((*(volatile uint32_t *)(base+0x50u))&4u)return KWU_HW_ERROR;
    fence_io();
    wr_base(base,KIND,0);wr_base(base,ADDR,512);
    for(unsigned row=0;row<99;row+=4) {
        unsigned next=row+8;
        if(next<99) {
            unsigned next_rows=(99-next<4)?99-next:4;
            rc=transport_load(base,input+next*32u,next_rows*32u);if(rc)return rc;
        }
        unsigned rows=(99-row<4)?99-row:4;
        rc=transport_output(base,output+row*256u,rows*256u);if(rc)return rc;
    }
''' + src[end:]


def compile_firmware(config):
    import subprocess
    old = ROOT / config['firmware']
    dest = BUILD / 'firmware' / NAME
    inputs = dest / 'input-files'
    copy_tree(old / 'input-files', inputs)
    driver = inputs / 'driver.c'
    write_text(driver, firmware(driver.read_text()))
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
                    parent_firmware=config['firmware'], startup_descriptor_order=['shift','bias','input','weight'])
    write_text(dest / 'firmware.json', json.dumps(metadata, indent=2)+'\n')
    return dest.relative_to(ROOT).as_posix(), metadata['boot_words']


def local_bench(src):
    src = replace(src, '''            if(block_row!=0&&block_row+4<99)
                input_block(block_row+4,(99-block_row-4<4)?99-block_row-4:4);''',
                   '''            if(block_row+8<99)
                input_block(block_row+8,(99-block_row-8<4)?99-block_row-8:4);''')
    src = replace(src, '''            write_word(8,0);write_word(12,0);input_block(0,8);
            read_word(4,value);if(!(value&32)) $fatal(1,"WP_START_NOT_READY");
            active=1;write_word(24,1);
            load_words(1,0,16384);''', '''            write_word(8,0);write_word(12,0);
            if(LD_DMA)begin
                for(integer i=0;i<256;i=i+1)
                    ld_shared[i]={input_stream_word(2*i+1),input_stream_word(2*i)};
                for(integer i=0;i<8192;i=i+1)
                    ld_shared[32768+i]={parameters[2*i+1],parameters[2*i]};
                active=1;
                write_word(8'h40,32'ha0000000);write_word(8'h44,256);write_word(8'h48,3);
                write_word(8'h40,32'ha0020000);write_word(8'h44,8192);
                read_word(8'h50,value);if(value&4)$fatal(1,"CHAIN_TRANSFER_ERROR");
            end else begin
                input_block(0,8);
                read_word(4,value);if(!(value&32)) $fatal(1,"WP_START_NOT_READY");
                active=1;write_word(24,1);
                load_words(1,0,16384);
            end''')
    return replace(src, '    kwt_icb_encoder dut(.*);', '''    kwt_icb_encoder dut(.*);
    integer reuse_holds=0, early_reservations=0, transpose_singles=0;
    always @(posedge clk) if(active) begin
        if(dut.core.reuse_block)begin
            if(dut.core.iw_issue_mac||dut.core.iw_issue_emit)
                $fatal(1,"REUSE_STALL_ISSUED_TOKEN");
            reuse_holds=reuse_holds+1;
        end
        if(dut.core.output_queue.reserve&&
           dut.core.output_queue.generation_state[dut.core.output_queue.reserve_generation]==2)
            early_reservations=early_reservations+1;
        if(dut.core.output_queue.issue&&dut.core.output_queue.transposed_read&&
           dut.core.output_queue.next_item[1:0]==3&&dut.core.output_queue.next_item[7:0]!=8'hff)begin
            if(dut.core.output_queue.issue_pair)$fatal(1,"TRANSPOSE_BANK_WRAP_PAIRED");
            transpose_singles=transpose_singles+1;
        end
    end
    final $display("SLOT_REUSE_COVERAGE stalls=%0d early=%0d singles=%0d",
                   reuse_holds,early_reservations,transpose_singles);''')


def bank_bench(src):
    src = replace(src, 'integer epoch,accepted,returned,dual,blocked,conflict;',
                  'integer epoch,accepted,returned,dual,blocked,conflict,tail_dual;')
    src = replace(src, '            dual=dual+1;', '''            dual=dual+1;
            if(dut.host_background)begin
                if(!dut.joined_weight_read||dut.host_bank_word[16:12]!=0)
                    $fatal(1,"UNQUALIFIED_WEIGHT_TAIL_WRITE");
                tail_dual=tail_dual+1;
            end''')
    src = replace(src, 'dual=0;blocked=0;conflict=0;checking=1;',
                  'dual=0;blocked=0;conflict=0;tail_dual=0;checking=1;')
    src = replace(src, '''                        if(i!=320)host_word(address(i),payload(i,epoch));
                    @(negedge clk);host_cmd_valid=0;''', '''                        if(i!=320)host_word(address(i),payload(i,epoch));
                    for(integer i=256;i<384;i=i+1)host_word(i,payload(8768+i,epoch));
                    @(negedge clk);host_cmd_valid=0;''')
    src = replace(src, 'if(accepted!=8768||dual==0||blocked==0)',
                  'if(accepted!=8768||dual==0||blocked==0||tail_dual==0||dut.input_committed!=384)')
    src = replace(src, '''            $display("STARTUP_BANK_PASS epoch=%0d dual=%0d conflict=%0d blocked=%0d",
                     epoch,dual,conflict,blocked);''', '''            for(integer i=256;i<384;i=i+1)
                cpu_access(32'ha0000000+4*i,payload(8768+i,epoch),1);
            $display("STARTUP_BANK_PASS epoch=%0d dual=%0d conflict=%0d blocked=%0d tail_dual=%0d",
                     epoch,dual,conflict,blocked,tail_dual);''')
    return src


def complete_bench(src, core):
    begin = '        if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.kwt_cmd_valid&&'
    start = src.index(begin)
    end = src.index('\n            starts=starts+1;', start)
    assert 'kwt_cmd_addr[7:0]==24' in src[start:end]
    return src[:start] + '        if(' + core + '.layer_start_valid&&' + core + '.layer_start_ready)' + src[end:]


def materialize():
    assert json.loads((REPORT / 'model-selection.json').read_text())['winner'] == 'TRB'
    selected = ROOT / 'constraints/ffn_selected.json'
    config = json.loads(selected.read_text())
    assert config['variant'] == PARENT
    (REPORT / 'baseline-selected.json').write_bytes(selected.read_bytes())
    fw, boot_words = compile_firmware(config)
    copy_tree(ROOT / config['source_snapshot'], SOURCE)
    for name, edit in (('encoder/kwt_encoder.sv', compute),
                       ('encoder/kwt_joint_output_queue.sv', queue),
                       ('encoder/kwt_ld_frontend.sv', frontend),
                       ('encoder_bus/kwt_icb_encoder.sv', lambda s: replace(s,
                            '.soft_reset(soft_reset),.input_ready', '.soft_reset(soft_reset),.layer_ready(core_layer_ready),.input_ready'))):
        path = SOURCE / name
        write_text(path, edit(path.read_text()))
    parent = BUILD / 'complete_soc' / PARENT
    (SOC / 'eda').mkdir(parents=True, exist_ok=True)
    for path in list(parent.iterdir()) + list((parent/'eda').glob('*.tcl')):
        if not path.is_file() or path.suffix not in ('.sv','.v','.svh','.f','.json','.sh','.tcl'):
            continue
        if path.name in ('gate_tb.sv','gate_files.f','compile_gate.sh','pr1_assessment.tcl'):
            continue
        source = path.read_text().replace(PARENT, NAME)
        if path.name == 'complete_soc_tb.sv':
            source = complete_bench(source, config['core_path'])
        elif path.name == 'configuration.json':
            data = json.loads(source)
            data.update(firmware=fw, startup_model='TRB')
            source = json.dumps(data, indent=2)+'\n'
        elif path.name == 'kwt_shared_dma_icb_sm40.sv':
            source = shared(source)
        elif path.name == 'boot_count.svh':
            source = 'localparam BOOT_WORDS=%d;\n' % boot_words
        write_text(SOC / path.relative_to(parent), source)
    copy_tree(parent / 'packed_inputs', SOC / 'packed_inputs')
    manifest = json.loads((ROOT/config['adaptive_manifest']).read_text())
    manifest.update(variant=NAME, parent_variant=PARENT, purpose='experiment', selected_model='TRB',
                    firmware=fw, parent=dict(variant=PARENT, configuration=config, firmware=config['firmware'],
                                             source_snapshot=config['source_snapshot'], profile=config['implementation']))
    manifest['changes'].update(prologue_result_transpose=True, progressive_slot_reuse=True,
                               weight_tail_input_dual=True, chained_input_weight=True)
    manifest['hardware'].extend(('transposed_result_slots', 'weight_tail_input_dual', 'chained_input_weight'))
    folder = ROOT/'constraints'/NAME/'candidates'
    folder.mkdir(parents=True, exist_ok=True)
    write_text(folder/(NAME+'.json'), json.dumps(manifest, indent=2)+'\n')
    RTL_TEST.mkdir(parents=True, exist_ok=True)
    original = BUILD/'rtl'/PARENT/'loading_dma_tb.sv'
    write_text(RTL_TEST/'loading_dma_tb.sv', local_bench(original.read_text()))
    write_text(RTL_TEST/'bank_port_tb.sv', bank_bench(original.with_name('bank_port_tb.sv').read_text()))


def develop():
    base.SOURCE, base.RTL_TEST, base.REPORT = SOURCE, RTL_TEST, REPORT
    base.develop()


def bank_check():
    import subprocess
    exe = RTL_TEST/'bank_port.vvp'
    args = ['iverilog', '-g2012', '-s', 'bank_port_tb', '-o', str(exe),
            str(RTL_TEST/'bank_port_tb.sv'), str(SOC/'kwt_shared_dma_icb_sm40.sv'),
            str(SOURCE/'encoder/kwt_ffn_clock_gate.sv')]
    for command, log in ((args, 'local-bank-build.log'), (['vvp', str(exe)], 'local-bank-protocol.log')):
        with (REPORT/log).open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    assert (REPORT/'local-bank-protocol.log').read_text().count('STARTUP_BANK_PASS') == 2


if __name__ == '__main__':
    {'materialize': materialize, 'develop': develop, 'bank': bank_check}[sys.argv[1]]()
