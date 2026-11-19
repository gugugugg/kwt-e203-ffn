"""Apply the post-DMA compute deltas to the frozen single-row, sixteen-lane core."""
import re


def _replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Inspect the frozen compute edit point: ' + before[:100])
    return text.replace(before, after, 1)


def _sub(text, pattern, replacement):
    text, count = re.subn(pattern, replacement, text)
    if count != 1:
        raise ValueError('Inspect the frozen compute expression: ' + pattern)
    return text


def _clock_declaration(text):
    if '    wire datapath_clk;\n    reg [13:0] clear_index;' in text:
        return text
    text = _replace(text, '    wire datapath_clk;\n', '')
    return _replace(text, '    reg [4:0] state;\n',
                    '    reg [4:0] state;\n    wire datapath_clk;\n')


def _gate_enable(text, extra):
    pattern = r'(kwt_ffn_clock_gate datapath_gate\(\.clk\(clk\),\.enable\()([^\n]+)(\),\n)'
    return _sub(text, pattern, lambda match: match[1] + match[2] + '||' + extra + match[3])


def _activation_register(text):
    block = '''    // A_REQ and each weight prefetch capture the matching activation.
    reg signed [15:0] pd_areg;
    wire pd_areg_capture=(state==A_REQ&&row_cache_ready)||prefetch;
    always @(posedge datapath_clk) if(pd_areg_capture)
        pd_areg<=row_cache[{row[0],request_inner}];
    wire signed [16:0] mac_a=$signed({pd_areg[15],pd_areg});'''
    text = _sub(text, r'    wire signed \[16:0\] mac_a=[^;]+;', block)
    return _gate_enable(text, '(state==A_REQ&&row_cache_ready)')


def _product_register(text):
    text = _replace(text, '    reg [4:0] state;\n',
                    "    localparam [4:0] PD_PM_DRAIN=5'd16;\n    reg [4:0] state;\n")
    native_product = "36'(mac_a*$signed(pm_rdata[lane_id*16+:16]))"
    booth = 'begin: cg_booth_lanes' in text
    product = 'cg_product[lane_id]' if booth else native_product
    capture_product = 'cg_product[pd_pm_lane]' if booth else 'mac_a*$signed(pm_rdata[pd_pm_lane*16+:16])'
    block = '''    // Product and accumulator registers share the same gated clock edge.
    wire pd_pm_issue=(state==B_MAC)||(state==ROW1_MAC);
    reg pd_pm_valid;
    reg signed [31:0] pd_pm_product[0:LANES-1];
    always @(posedge datapath_clk or negedge rst_n) begin
        if(!rst_n)pd_pm_valid<=0;
        else pd_pm_valid<=pd_pm_issue;
    end
    generate for(genvar pd_pm_lane=0;pd_pm_lane<LANES;pd_pm_lane=pd_pm_lane+1) begin: pd_product_registers
        always @(posedge datapath_clk) if(pd_pm_issue)
            pd_pm_product[pd_pm_lane]<=32'(%s);
    end endgenerate
''' % capture_product
    text = _replace(text, '    wire stash_write=state==EMIT_STASH;',
                    block + '    wire stash_write=state==EMIT_STASH;')
    text = _replace(text,
                    'wire mac_update=((state==B_MAC)||(state==ROW1_MAC))&&(mac_group==group_id);',
                    'wire mac_update=pd_pm_valid&&((state==B_MAC)||(state==ROW1_MAC)||(state==PD_PM_DRAIN))&&(mac_group==group_id);')
    registered_product = "$signed({{4{pd_pm_product[lane_id][31]}},pd_pm_product[lane_id]})"
    if 'wire [35:0] cg_p=' in text:
        text = _replace(text, 'wire [35:0] cg_p=' + product + ';',
                        'wire [35:0] cg_p=' + registered_product + ';')
    else:
        text = _replace(text,
                        'if(mac_update) accumulator[group_id*LANES+lane_id]<=accumulator[group_id*LANES+lane_id]+' + product + ';',
                        'if(mac_update) accumulator[group_id*LANES+lane_id]<=accumulator[group_id*LANES+lane_id]+' + registered_product + ';')
    text = _replace(text,
                    'if(inner==63) begin lane<=0;emit_group<=0;state<=EMIT;end',
                    'if(inner==63) begin lane<=0;emit_group<=0;state<=PD_PM_DRAIN;end')
    text = _replace(text, '                EMIT:if(fifo_push) begin',
                    '                PD_PM_DRAIN:state<=EMIT;\n                EMIT:if(fifo_push) begin')
    return _gate_enable(text, '(state==PD_PM_DRAIN)')


def _distributed_quantizer(text):
    start = text.index('    wire [35:0] quant_bits=')
    end = text.index('    kwt_ffn_requantize quantizer(', start)
    end = text.index(';', end) + 1
    block = '''    wire signed [15:0] result_word;
    wire [63:0] pd_qd4_results;
    generate for(genvar pd_qgroup=0;pd_qgroup<4;pd_qgroup=pd_qgroup+1) begin: pd_local_quantizers
        wire selected=(state==EMIT)&&(lane[3:2]==2'(pd_qgroup));
        wire [35:0] value_bits=selected?accumulator[pd_qgroup*4+int'(lane[1:0])]:36'd0;
        wire signed [63:0] value={{28{value_bits[35]}},value_bits};
        wire signed [7:0] shift=selected?shifts[pd_qgroup*4+int'(lane[1:0])]:8'sd0;
        kwt_ffn_requantize quantizer(.value(value),.shift(shift),.result(pd_qd4_results[pd_qgroup*16+:16]));
    end endgenerate
    assign result_word=$signed(pd_qd4_results[lane[3:2]*16+:16]);'''
    return text[:start] + block + text[end:]


def transform(text, flags):
    """Return a new source; flags contain only AREG/QD4/PM deltas for this call."""
    flags = set(flags)
    unknown = flags - {'AREG', 'QD4', 'PM'}
    if unknown:
        raise ValueError('Unknown post-DMA compute delta: ' + ','.join(sorted(unknown)))
    if not flags:
        return text
    for field, value in [('ROW_GROUP', 1), ('INPUT_SLOTS', 2), ('STREAM_INPUT', 1),
                         ('SMALL_INPUT', 1), ('USE_ROW_CACHE', 1), ('LANES', 16)]:
        if not re.search(r'\b' + field + r'\s*=\s*' + str(value) + r'\b', text):
            raise ValueError('Compute deltas require the frozen ' + field + '=' + str(value) + ' core')
    markers = {'AREG': 'reg signed [15:0] pd_areg;', 'QD4': 'begin: pd_local_quantizers',
               'PM': 'PD_PM_DRAIN='}
    for flag in flags:
        if markers[flag] in text:
            raise ValueError('Compute delta already present: ' + flag)
    if flags & {'AREG', 'PM'}:
        if 'if(0) begin: fine_gate' not in text:
            raise ValueError('Inspect accumulator clocking before adding compute registers')
        text = _clock_declaration(text)
    if 'AREG' in flags:
        text = _activation_register(text)
    if 'PM' in flags:
        text = _product_register(text)
    if 'QD4' in flags:
        text = _distributed_quantizer(text)
    return text
