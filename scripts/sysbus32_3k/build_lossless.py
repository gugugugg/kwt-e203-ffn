"""Generate the selected lossless CH SoC from the frozen 3K implementation."""

import json
import sys

import build_soc as build
from lossless import pack_input, pack_tile, signed

ROOT, HERE = build.ROOT, build.HERE
PARENT = build.NAME
NAME = 'ffn_sysbus32_lossless'
SOC = build.SOC.with_name(NAME)
SOURCE = build.SOURCE.with_name(NAME)
REPORT = build.REPORT.with_name(NAME)
EXTRA = 'host_loading'


def fixtures():
    identities = [(r, k) for first in range(0, 96, 8) for k in range(64)
                  for r in (first,first+1,first+4,first+5,first+2,first+3,first+6,first+7)]
    identities += [(row,k) for k in range(64) for row in range(96,99)]
    model = REPORT/'model-selection.json'
    if model.is_file():
        model = json.loads(model.read_text())
        assert model['selected'] == 'CH'
    else:
        model = None
    for case in range(1,13):
        addresses, data = build.pack(case-1)
        original = dict(zip(addresses,data))
        values = [signed((original[i] >> bit)&65535,16) for i in range(3168) for bit in (0,16)]
        packed, split = pack_input(values, identities)
        encoded = dict(enumerate(packed))
        tiles = []
        last = 32768
        for offset in range(32768,41280,532):
            packet = pack_tile([original[i] for i in range(offset,offset+532)])
            address = list(range(last,last+len(packet)))
            encoded.update(zip(address,packet))
            tiles.append(address)
            last += len(packet)
        order = [0] + tiles[0] + list(range(1,split)) + tiles[1] + list(range(split,len(packed)))
        order.extend(i for tile in tiles[2:] for i in tile)
        assert len(order) == len(encoded)
        if model:
            assert len(order) == model['results']['CH']['rows'][case-1]['encoded_words']
        for stem, fmt, contents in (('payload','%08x', [encoded[i] for i in order]),
                                    ('addresses','%05x', order), ('count','%08x', [len(order)])):
            build.write(SOC/('packed_inputs/task_%02d_%s.hex'%(case,stem)), '\n'.join(fmt % i for i in contents)+'\n')


def endpoint(text):
    text = build.replace(text, '    input wire ld_rsp_err\n', '    input wire host_loading,\n    input wire ld_rsp_err\n')
    text = build.replace(text, '    wire [31:0] wb_data,src_addr;', '''    wire [31:0] wb_data,src_addr;
    wire coded_valid,coded_ready,coded_rsp,coded_rsp_ready;
    wire [31:0] coded_addr,decoded_word;
    kwt_lossless_source decode(.clk(clk),.rst_n(rst_n),.start(start),.busy(busy),
        .input_committed(input_committed),.parameter_committed(parameter_committed),
        .raw_valid(src_valid),.raw_ready(src_ready),.raw_addr(src_addr),
        .raw_rsp_valid(src_rsp),.raw_rsp_ready(src_rsp_ready),.raw_data(decoded_word),
        .source_valid(coded_valid),.source_ready(coded_ready),.source_addr(coded_addr),
        .source_rsp_valid(coded_rsp),.source_rsp_ready(coded_rsp_ready),.source_data(ld_rsp_rdata));''')
    text = build.replace(text, '.input_committed(input_committed),.parameter_committed(parameter_committed),.output_priority(output_priority),',
                         ".input_committed(12'd3168),.parameter_committed(14'd8512),.output_priority(output_priority),")
    text = build.replace(text, '.ld_rsp_rdata(ld_rsp_rdata),.ld_rsp_err(ld_rsp_err),',
                         '.ld_rsp_rdata(decoded_word),.ld_rsp_err(ld_rsp_err&&wb_ack_valid),')
    text = build.replace(text, '.source_valid(src_valid),.source_ready(src_ready),.source_addr(src_addr),',
                         '.source_valid(coded_valid),.source_ready(coded_ready),.source_addr(coded_addr),')
    text = build.replace(text, '.source_rsp_valid(src_rsp),.source_rsp_ready(src_rsp_ready),',
                         '.source_rsp_valid(coded_rsp),.source_rsp_ready(coded_rsp_ready),')
    return build.replace(text, '.result_valid(wb_valid),.result_ready(wb_ready)',
                         '.result_valid(wb_valid),.host_loading(host_loading),.result_ready(wb_ready)')


def bench(text):
    text = build.replace(text, '    integer result_acks=0, result_index;',
                         '    integer result_acks=0, result_index;\n    reg [31:0] wire_count [0:0];')
    text = build.replace(text, '            $readmemh(filename,payload_addr);', '''            $readmemh(filename,payload_addr);
            filename=$sformatf("build/optimization/complete_soc/ffn_sysbus32_lossless/packed_inputs/task_%02d_count.hex",(current_case+1)/2);
            $readmemh(filename,wire_count);''')
    text = build.replace(text, 'i<11680;i=i+1', 'i<wire_count[0];i=i+1')
    text = build.replace(text, 'ld_dma_reads!=11680||result_acks!=12672||host_payload!=11680',
                         'ld_dma_reads!=wire_count[0]||result_acks!=12672||host_payload!=wire_count[0]')
    return build.replace(text, 'host_payload=11680 host_control=5",\n                     current_case,(current_case-1)/2,$countones(output_seen),task_cycles);',
                         'host_payload=%0d host_control=5",\n                     current_case,(current_case-1)/2,$countones(output_seen),task_cycles,host_payload);')


def main():
    for source in build.SOURCE.glob('encoder/*.sv'):
        build.write(SOURCE/'encoder'/source.name, source.read_text())
    for name in ('decode.sv','source_decode.sv'):
        build.write(SOURCE/'encoder'/name, (HERE/name).read_text())
    issue = (HERE/'issue_bus.sv').read_text()
    issue = build.replace(issue,'    input wire result_valid,','    input wire result_valid, host_loading,')
    issue = build.replace(issue,'    assign ld_cmd_valid = room && (choose_read ? source_valid : result_valid);',
                          '    assign ld_cmd_valid = room && (choose_read ? source_valid :\n'
                          '        result_valid && (held || output_priority || !host_loading));')
    issue = build.replace(issue, 'assign result_ready = room && !choose_read && ld_cmd_ready;',
                          'assign result_ready = ld_cmd_valid && !choose_read && ld_cmd_ready;')
    build.write(SOURCE/'encoder/kwt_sysbus_issue.sv',issue)
    for path in list(build.SOC.iterdir())+list((build.SOC/'eda').glob('*.tcl')):
        if not path.is_file() or path.suffix not in ('.sv','.svh','.v','.f','.tcl','.rcf','.json'):
            continue
        text = path.read_text().replace(PARENT,NAME)
        if path.name=='kwt_loading_dma_accelerator.sv':
            text = endpoint(text)
        elif path.name=='e203_subsys_perips.v':
            text = build.replace(text,'    input wire ld_rsp_err\n','    input wire host_loading,\n    input wire ld_rsp_err\n')
        elif path.name in ('e203_subsys_main.v','kwt_loading_dma_endpoint.svh'):
            port = '.host_loading(host_cmd_valid)' if path.name=='e203_subsys_main.v' else '.host_loading(host_loading)'
            text = build.replace(text,'        .ld_rsp_err(ld_rsp_err),','        '+port+',\n        .ld_rsp_err(ld_rsp_err),')
        elif path.name=='complete_soc_tb.sv':
            text = bench(text)
        elif path.name in ('files.f','synthesis_files.f'):
            text += '\n'.join((SOURCE/'encoder'/name).relative_to(ROOT).as_posix() for name in ('decode.sv','source_decode.sv'))+'\n'
        build.write(SOC/path.relative_to(build.SOC),text)
    fixtures()


if __name__=='__main__':
    (fixtures if sys.argv[1:] == ['--fixtures'] else main)()
