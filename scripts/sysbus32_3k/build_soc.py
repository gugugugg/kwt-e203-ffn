"""Materialize the 64-MAC single-System-Bus research SoC."""
import json
from pathlib import Path
import shutil
import sys

from core_edit import derive

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BUILD = ROOT / 'build/optimization'
PARENT = 'ffn_trb_sysbus32'
NAME = 'ffn_sysbus32_3k'
OLD = BUILD / 'complete_soc' / PARENT
SOC = BUILD / 'complete_soc' / NAME
SOURCE = BUILD / 'rtl_sources' / NAME
REPORT = ROOT / 'reports/optimization' / NAME
FIRMWARE = 'build/optimization/firmware/ffn_trb_threebank'
sys.path.insert(0, str(ROOT / 'scripts/trb_threebank'))
from fixture import pack


def replace(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def endpoint(text):
    text = text[:text.index('    wire trace_valid;')]
    body = (ROOT / 'scripts/trb_threebank/endpoint.svh').read_text(encoding='utf-8')
    a = body.index('    assign ld_cmd_read=1;')
    b = body.index('    always @(posedge', a)
    body = body[:a] + body[b:]
    body = replace(body, '    kwt_threebank_core core(.*);', '''    wire src_valid,src_ready,src_rsp,src_rsp_ready,output_priority;
    wire wb_valid,wb_ready,wb_ack_valid,wb_ack_ready;
    wire [16:0] wb_addr;
    wire [31:0] wb_data,src_addr;
    kwt_threebank_core core(.clk(clk),.rst_n(rst_n),.start(start),.busy(busy),.done(done),.error(error),
        .input_committed(input_committed),.parameter_committed(parameter_committed),.output_priority(output_priority),
        .ld_cmd_valid(src_valid),.ld_cmd_ready(src_ready),.ld_cmd_addr(src_addr),
        .ld_rsp_valid(src_rsp),.ld_rsp_ready(src_rsp_ready),.ld_rsp_rdata(ld_rsp_rdata),.ld_rsp_err(ld_rsp_err),
        .wb_valid(wb_valid),.wb_ready(wb_ready),.wb_addr(wb_addr),.wb_data(wb_data),
        .wb_ack_valid(wb_ack_valid),.wb_ack_ready(wb_ack_ready));
    kwt_sysbus_issue issue_bus(.clk(clk),.rst_n(rst_n),.start(start),
        .source_valid(src_valid),.source_ready(src_ready),.source_addr(src_addr),
        .source_rsp_valid(src_rsp),.source_rsp_ready(src_rsp_ready),
        .result_valid(wb_valid),.result_ready(wb_ready),.result_addr(wb_addr),.result_data(wb_data),
        .result_ack(wb_ack_valid),.result_ack_ready(wb_ack_ready),.output_priority(output_priority),
        .ld_cmd_valid(ld_cmd_valid),.ld_cmd_read(ld_cmd_read),.ld_cmd_ready(ld_cmd_ready),
        .ld_cmd_addr(ld_cmd_addr),.ld_cmd_wdata(ld_cmd_wdata),.ld_cmd_wmask(ld_cmd_wmask),
        .ld_rsp_valid(ld_rsp_valid),.ld_rsp_ready(ld_rsp_ready));''')
    return text + body


def masters(text):
    text = replace(text, '    input wire [3:0] sram_cmd_wmask\n);', '''    input wire [3:0] sram_cmd_wmask,
    output reg [11:0] input_committed,
    output reg [13:0] parameter_committed
);''')
    a = text.index('    reg [11:0] input_committed;')
    b = text.index('    // A single', a)
    text = text[:a] + text[b:]
    text = replace(text, 'ld_cmd_valid&&dma_eligible', 'ld_cmd_valid')
    text = replace(text, '{host_cmd_ready,dma_ready,cpu_cmd_ready}', '{host_cmd_ready,ld_cmd_ready,cpu_cmd_ready}')
    a = text.index('    always @(posedge', text.index('wire full_write'))
    return text[:a] + '''    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            input_committed<=0;
            parameter_committed<=0;
        end else if (full_write) begin
            if (commit_word==0) begin
                input_committed<=1;
                parameter_committed<=0;
            end else if (input_committed<3168&&commit_word==17'(input_committed))
                input_committed<=input_committed+12'd1;
            else if (parameter_committed<8512&&commit_word==17'd32768+17'(parameter_committed))
                parameter_committed<=parameter_committed+14'd1;
        end
    end
endmodule
'''


PORTS = '    input wire [11:0] input_committed,\n    input wire [13:0] parameter_committed,\n'
WIRES = 'wire [11:0] input_committed;\nwire [13:0] parameter_committed;\n'
CONNECTIONS = '        .input_committed(input_committed),\n        .parameter_committed(parameter_committed),\n'


def bench(parent):
    prefix = parent[:parent.index('    string filename,mode_name')]
    prefix += '    realtime activity_begin,activity_end;\n'
    prefix += parent[parent.index('    wire cpu_fire='):parent.index('    bit firmware_done=0;')]
    prefix += '    bit firmware_done=0;\n'
    prefix += parent[parent.index('    task command_phase;'):parent.index('    task put_word')].split('endtask')[0]+'endtask\n'
    prefix += parent[parent.index('    task put_word'):parent.index('    always @(posedge clk) if(rst_n) begin')]
    begin = parent.index('        for(integer b=0;b<')
    # Use the frozen System Bus boot path, including mailbox initialization over ICB.
    start = parent.index('        $readmemh(firmware_path,boot_words);') + len('        $readmemh(firmware_path,boot_words);\n')
    stop = parent.index('        for(task_number=0;', start)
    boot = parent[start:stop]
    assert 'host_idle();' in boot and begin < stop
    body = (ROOT / 'scripts/trb_threebank/bench_body.svh').read_text(encoding='utf-8')
    body = body.replace('ffn_trb_threebank', NAME).replace('build/optimization/firmware/'+NAME, FIRMWARE)
    body = body.replace('/* BOOT */', boot)
    a = body.index('    integer triples=')
    b = body.index('    always @(posedge clk)', a)
    main = 'dut.soc.u_e203_subsys_main'
    body = body[:a] + '''    integer result_acks=0, result_index;
    wire source_fire=@MAIN@.ld_cmd_valid&&@MAIN@.ld_cmd_ready&&@MAIN@.ld_cmd_read;
    wire result_fire=dut.shared_memory.memory.en&&dut.shared_memory.memory.we&&
        dut.shared_memory.memory.addr>=16384&&dut.shared_memory.memory.addr<29056;
    wire result_ack=@MAIN@.u_e203_subsys_perips.accelerator.wb_ack_valid&&
        @MAIN@.u_e203_subsys_perips.accelerator.wb_ack_ready;
'''.replace('@MAIN@', main) + body[b:]
    body = body.replace('dut.wb_addr', 'dut.shared_memory.memory.addr').replace('dut.wb_data', 'dut.shared_memory.memory.wdata')
    a = body.index('`ifndef KWT_UNIFIED_GATE', body.index('            last_write=cycles;'))
    b = body.index('`endif', a)+len('`endif')
    body = body[:a] + '            if(dut.shared_memory.memory.wmask!=4\'hf) $fatal(1,"RESULT_MASK");' + body[b:]
    body = body.replace(';triples=0', '').replace('THREEBANK_COUNTS case=%0d triples=%0d', 'SYSBUS3K_COUNTS case=%0d')
    body = body.replace('current_case,triples,ld_dma_reads', 'current_case,ld_dma_reads')
    return prefix + body


def materialize():
    model = json.loads((REPORT / 'candidate-model.json').read_text(encoding='utf-8'))
    assert model['passes_cycle_screen']
    src = BUILD / 'rtl_sources' / PARENT / 'encoder/kwt_ffn_requantize.sv'
    write(SOURCE / 'encoder/kwt_ffn_requantize.sv', src.read_text(encoding='utf-8'))
    write(SOURCE / 'encoder/kwt_threebank_core.sv', derive((ROOT / 'scripts/trb_threebank/core.sv').read_text(encoding='utf-8')))
    write(SOURCE / 'encoder/kwt_sysbus_issue.sv', (HERE / 'issue_bus.sv').read_text(encoding='utf-8'))
    for path in list(OLD.iterdir()) + list((OLD / 'eda').glob('*.tcl')):
        if not path.is_file() or path.suffix not in ('.sv','.svh','.v','.f','.tcl','.rcf') or path.name.startswith('local-'):
            continue
        name = path.name
        text = path.read_text(encoding='utf-8').replace(PARENT, NAME)
        if name == 'kwt_shared_dma_icb_sm40.sv':
            text = (HERE / 'write_ack.sv').read_text(encoding='utf-8').replace('kwt_sysbus_commit_ack', 'kwt_shared_icb_sm40')
            # Keep the original top's target port names.
            import re
            text = re.sub(r'\b(cmd_|rsp_)(\w+)', r'cpu_\1\2', text)
        elif name == 'kwt_sysbus_masters.sv':
            text = masters(text)
        elif name == 'kwt_loading_dma_accelerator.sv':
            text = endpoint(replace(text, '    input wire ld_rsp_err\n);', PORTS+'    input wire ld_rsp_err\n);'))
        elif name == 'e203_subsys_perips.v':
            text = replace(text, '    input wire ld_rsp_err\n', PORTS+'    input wire ld_rsp_err\n')
        elif name == 'e203_subsys_main.v':
            text = replace(text, 'e203_subsys_perips u_e203_subsys_perips (', WIRES+'e203_subsys_perips u_e203_subsys_perips (')
            text = replace(text, '        .ld_rsp_err(ld_rsp_err),', CONNECTIONS+'        .ld_rsp_err(ld_rsp_err),')
            text = replace(text, '.sram_cmd_wmask(sysmem_icb_cmd_wmask)\n', '.sram_cmd_wmask(sysmem_icb_cmd_wmask),\n'+CONNECTIONS.rstrip().rstrip(',')+'\n')
        elif name == 'kwt_loading_dma_endpoint.svh':
            text = replace(text, '        .ld_rsp_err(ld_rsp_err),', CONNECTIONS+'        .ld_rsp_err(ld_rsp_err),')
        elif name == 'complete_soc_tb.sv':
            text = bench(text)
        elif name == 'boot_count.svh':
            count = json.loads((ROOT / FIRMWARE / 'firmware.json').read_text(encoding='utf-8'))['boot_words']
            text = 'localparam integer BOOT_WORDS=%d;\n' % count
        elif name in ('files.f', 'synthesis_files.f'):
            text = '\n'.join(line for line in text.splitlines() if line.strip() and '/rtl_sources/'+NAME+'/' not in line)
            text += '\n'+'\n'.join(p.relative_to(ROOT).as_posix() for p in sorted((SOURCE / 'encoder').glob('*.sv'))) + '\n'
        elif name.endswith('.tcl'):
            text = text.replace('exec find build/server/technology', 'exec find -L build/server/technology')
        write(SOC / path.relative_to(OLD), text)
    for case in range(12):
        addresses, words = pack(case)
        write(SOC / ('packed_inputs/task_%02d_payload.hex' % (case+1)), ''.join('%08x\n' % word for word in words))
        write(SOC / ('packed_inputs/task_%02d_addresses.hex' % (case+1)), ''.join('%05x\n' % word for word in addresses))
    write(SOC / 'configuration.json', json.dumps(dict(variant=NAME, parent_variant=PARENT, firmware=FIRMWARE,
          macs=64, input_macros=8, weight_macros=16, result_macros=16, result_slots=32, bus_width=32), indent=2)+'\n')


if __name__ == '__main__':
    materialize()
