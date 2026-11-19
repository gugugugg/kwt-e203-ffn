"""Materialize S/R/SR from their same-family frozen parent, outside ongoing experiments."""
import json
import re
from ffn_adaptive_next import ROOT, load, candidates, copy_tree


def edit(text, old, new):
    if old not in text:raise RuntimeError('Frozen parent edit point missing: ' + old[:90])
    return text.replace(old, new)


def cache_logic(paired=False):
    return '''
    reg signed [15:0] row_cache[0:CACHE_LAST];
    reg row_cache_valid;
    reg [6:0] row_cache_row;
    reg [4:0] row_cache_request;
    reg [3:0] row_cache_chunk;
    reg row_cache_pending;
    wire row_cache_ready=row_cache_valid&&(row_cache_row==7'(row));
    wire [4:0] row_cache_groups=GROUP_COUNT;
    wire row_cache_issue=(state==A_REQ)&&!row_cache_ready&&(row_cache_request<row_cache_groups);
    wire row_cache_clk;
    kwt_ffn_clock_gate row_input_gate(.clk(clk),.enable(row_cache_pending),
        .test_enable(clock_test_enable||!rst_n),.gated_clk(row_cache_clk));
    integer cache_bank;
    always @(posedge row_cache_clk) if(row_cache_pending)
        for(cache_bank=0;cache_bank<8;cache_bank=cache_bank+1)
            row_cache[int'(row_cache_chunk)*8+cache_bank]<=sp_rdata[cache_bank*16+:16];
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            row_cache_valid<=0;row_cache_row<=0;row_cache_request<=0;
            row_cache_pending<=0;row_cache_chunk<=0;
        end else if(state==CLEAR) begin
            row_cache_valid<=0;row_cache_request<=0;row_cache_pending<=0;
        end else begin
            row_cache_pending<=row_cache_issue;
            if(row_cache_issue) begin
                row_cache_chunk<=row_cache_request[3:0];row_cache_request<=row_cache_request+1'b1;
            end
            if(row_cache_pending&&{1'b0,row_cache_chunk}==row_cache_groups-1'b1) begin
                row_cache_valid<=1;row_cache_row<=7'(row);
            end
            if(state!=A_REQ) begin row_cache_request<=0;row_cache_pending<=0;end
        end
    end
'''.replace('CACHE_LAST', '127' if paired else '63').replace('GROUP_COUNT', "(row<98)?5'd16:5'd8" if paired else "5'd8")


def cache_request(paired=False):
    address = "(row+int'(row_cache_request>=8))*8+int'(row_cache_request[2:0])" if paired else "row*8+int'(row_cache_request)"
    return '''        if(row_cache_issue) begin
            sp_en='1;
            for(b=0;b<8;b=b+1) sp_addr[b*13+:13]=13'(ADDRESS);
        end
'''.replace('ADDRESS', address)


def apply_s(text):
    at = text.index('    wire [6:0] read_row=')
    text = text[:at] + cache_logic() + text[at:]
    text = re.sub(r'wire signed \[16:0\] mac_a=[^;]+;',
                  "wire signed [16:0] mac_a=$signed({row_cache[inner][15],row_cache[inner]});", text)
    start = text.index('        if(state==A_REQ||prefetch) begin')
    end = text.index('        if(bias_request)', start)
    block = cache_request() + '''        if((state==A_REQ&&row_cache_ready)||prefetch) begin
            pm_en='1;for(b=0;b<LANES;b=b+1) pm_addr[b*13+:13]=13'(int'(weight_address)/LANES);
        end
'''
    text = text[:start] + block + text[end:]
    return edit(text, 'A_REQ: state<=B_MAC;', 'A_REQ: if(row_cache_ready) state<=B_MAC;')


def apply_r(text, manifest):
    end = text.index('    integer acc_offset,bias_offset;')
    text = text[:end]
    text = edit(text, 'GROUPS=OVERLAP?2:1', 'GROUPS=2')
    text = edit(text, '    reg [3:0] state;', '    reg [4:0] state;')
    at = text.index('    reg [4:0] state;')
    text = text[:at] + '    localparam [4:0] ROW1_MAC=9,EMIT_STASH=10,STASH_REQ=11,STASH_OUT=13;\n' + text[at:]
    text = edit(text, '    wire signed [15:0] result_word;', '''    wire signed [15:0] result_word;
    reg [7:0] stash_pointer;
    wire [31:0] stash_rdata;
    wire [15:0] fifo_word=(state==STASH_OUT)?stash_rdata[stash_pointer[0]*16+:16]:result_word;
    wire stash_write=state==EMIT_STASH;
    wire stash_read=(state==STASH_REQ)||((state==STASH_OUT)&&fifo_push&&stash_pointer<255);
    wire [7:0] stash_address=(state==STASH_OUT)?stash_pointer+1'b1:stash_pointer;
    wire [7:0] stash_column=8'(tile*LANES+lane);
''')
    text = edit(text, 'wire emission=OVERLAP?complete_group[emit_group]:(state==EMIT);',
                'wire emission=(state==EMIT)||(state==STASH_OUT);')
    text = re.sub(r'wire \[35:0\] quant_bits=[^;]+;',
                  "wire [35:0] quant_bits=accumulator[((state==EMIT_STASH)?LANES:0)+lane];", text)
    text = re.sub(r'\.shift\(shifts\[[^\n]+\]\),\.result',
                  '.shift(shifts[((state==EMIT_STASH)?LANES:0)+lane]),.result', text)
    text = re.sub(r'wire prefetch=[^;]+;',
                  'wire prefetch=((state==ROW1_MAC)||((state==B_MAC)&&row==98))&&(inner<63);', text)
    text = re.sub(r'wire bias_request=[^;]+;', 'wire bias_request=state==BIAS_REQ;', text)
    text = re.sub(r'wire bias_capture=[^;]+;', 'wire bias_capture=state==BIAS_CAP;', text)
    text = re.sub(r'wire \[5:0\] bias_tile=[^;]+;', "wire [5:0] bias_tile=6'(tile);", text)
    text = re.sub(r'wire \[3:0\] bias_chunk=[^;]+;', "wire [3:0] bias_chunk=4'(chunk);", text)
    if '    wire datapath_clk' in text:
        a = text.index('    wire datapath_clk');b = text.index('    wire [6:0] read_row=', a)
        text = text[:a] + text[b:]
    text = re.sub(r'assign trace_index=[^;]+;',
                  "assign trace_index=(state==STASH_OUT)?15'((row+1)*256+int'(stash_pointer)):15'(row*256+tile*LANES+lane);", text)
    text = edit(text, "assign trace_data={{48{result_word[15]}},result_word};",
                "assign trace_data={{48{fifo_word[15]}},fifo_word};")
    cache = manifest['changes']['row_cache']
    if cache:
        at = text.index('    wire [6:0] read_row=');text = text[:at] + cache_logic(True) + text[at:]
        text = re.sub(r'wire signed \[16:0\] mac_a=[^;]+;',
                      "wire signed [16:0] mac_a=$signed(row_cache[((state==ROW1_MAC)?64:0)+inner]);", text)
    else:
        at = text.index('    wire [6:0] read_row=');text = text[:at] + '    wire row_cache_ready=1\'b1;\n' + text[at:]
        text = edit(text, "wire [12:0] input_address=13'(int'(read_row)*64+inner);",
                    "wire [12:0] input_address=13'((row+int'(state==ROW1_MAC))*64+inner);")
    a = text.index('        if(state==A_REQ||prefetch) begin');b = text.index('        if(bias_request)', a)
    requests = cache_request(True) if cache else '''        if((state==A_REQ)||prefetch||((state==B_MAC)&&row<98)) begin
            address=(row+int'((state==B_MAC)&&row<98))*64+int'(request_inner);bank_index=address%8;
            sp_en[bank_index]=1;sp_addr[bank_index*13+:13]=13'(address/8);
        end
'''
    requests += '''        if((state==A_REQ&&row_cache_ready)||prefetch) begin
            pm_en='1;for(b=0;b<LANES;b=b+1) pm_addr[b*13+:13]=13'(int'(weight_address)/LANES);
        end
'''
    text = text[:a] + requests + text[b:]
    source = (ROOT / manifest['parent']['source_snapshot'] / 'encoder/kwt_encoder.sv').read_text()
    clear_last = re.search(r'CLEAR: if\(clear_index==(\d+)\)', source).group(1)
    depth = int(re.search(r'fifo\[0:(\d+)\]', text).group(1)) + 1
    ptr = (depth-1).bit_length();count = depth.bit_length()
    body = (ROOT / 'rtl/ffn/kwt_ffn_rowpair_body.svh').read_text()
    for key, value in dict(CLEAR_LAST=clear_last, PTR_BITS=ptr, COUNT_BITS=count,
                           FINE_REG=int(manifest['effective_changes'].get('fine_register_gate', False)),
                           BIAS_OFFSET='0' if manifest['effective_changes'].get('compact_bias') else "(int'(bias_chunk)*8%LANES)*16").items():
        body = body.replace('@'+key+'@', str(value))
    return text + body


def prepare(variant):
    m = load(variant);out = ROOT / 'build/optimization/rtl_sources' / variant
    copy_tree(ROOT / m['parent']['source_snapshot'], out)
    path = out / 'encoder/kwt_encoder.sv';text = path.read_text()
    if m['changes']['row_pair']:text = apply_r(text, m)
    elif m['changes']['row_cache']:text = apply_s(text)
    path.write_text(text)
    (out / 'configuration.json').write_text(json.dumps(m, indent=2))
    return out


def variants():
    return {name: ['PIPE', 'OUTPUT'] for name in candidates()}


if __name__ == '__main__':
    import sys
    for variant in sys.argv[1:]:print(prepare(variant))
