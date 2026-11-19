"""Apply BP and E2 to the frozen sixteen-MAC tile core."""
def _replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Inspect frozen tile edit point: ' + before[:100])
    return text.replace(before, after, 1)


def _trace_ports(text):
    if 'output wire trace_pair_valid' in text:
        return text
    return _replace(text, 'output wire signed [63:0] trace_data',
                    'output wire signed [63:0] trace_data,\n    output wire trace_pair_valid,\n    output wire signed [63:0] trace_high')


def adapt_bus_trace(source: str) -> str:
    if 'output wire trace_pair_valid' in source:
        return source
    text = _trace_ports(source)
    return _replace(text, '.trace_index(trace_index),.trace_data(trace_data));',
                    '.trace_index(trace_index),.trace_data(trace_data),\n        .trace_pair_valid(trace_pair_valid),.trace_high(trace_high));')


def _bias_prefetch(text):
    text = _replace(text, '    reg [4:0] state;',
                    "    localparam [4:0] TP_BP_SEED=5'd16;\n    reg [4:0] state;")
    at = '    wire bias_request=state==BIAS_REQ,bias_capture=state==BIAS_CAP;'
    block = '''    reg tp_bp_active,tp_bp_capture_phase,tp_bp_valid;
    reg [2:0] tp_bp_chunk;
    reg [3:0] tp_bp_tile;
    wire tp_bp_seed=state==TP_BP_SEED;
    wire tp_bp_launch=(state==B_MAC)&&(inner==0)&&((row<98)||(tile<TILES-1));
    wire [3:0] tp_bp_next_tile=(tile==TILES-1)?4'd0:4'(tile+1);
    wire tp_bp_request=tp_bp_launch||(tp_bp_active&&!tp_bp_capture_phase);
    wire tp_bp_capture=tp_bp_active&&tp_bp_capture_phase;
    wire [3:0] tp_bp_read_tile=tp_bp_request?(tp_bp_launch?tp_bp_next_tile:tp_bp_tile):4'(tile);
    wire [2:0] tp_bp_read_chunk=tp_bp_request?(tp_bp_launch?3'd0:tp_bp_chunk):3'(chunk);
    reg [511:0] tp_bp_bias;
    reg [127:0] tp_bp_shift;
    wire bias_request=(state==BIAS_REQ)||tp_bp_request;
    wire bias_capture=state==BIAS_CAP;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n)begin
            tp_bp_active<=0;tp_bp_capture_phase<=0;tp_bp_valid<=0;tp_bp_chunk<=0;tp_bp_tile<=0;
        end else if(layer_start_valid&&layer_start_ready)begin
            tp_bp_active<=0;tp_bp_capture_phase<=0;tp_bp_valid<=0;tp_bp_chunk<=0;
        end else begin
            if(tp_bp_seed)tp_bp_valid<=0;
            if(tp_bp_launch)begin
                tp_bp_active<=1;tp_bp_capture_phase<=1;tp_bp_chunk<=0;tp_bp_tile<=tp_bp_next_tile;
            end else if(tp_bp_active)begin
                if(tp_bp_capture_phase)begin
                    tp_bp_capture_phase<=0;
                    if(tp_bp_chunk==7)begin tp_bp_active<=0;tp_bp_valid<=1;end
                    else tp_bp_chunk<=tp_bp_chunk+1'b1;
                end else tp_bp_capture_phase<=1;
            end
        end
    end
'''
    text = _replace(text, at, block)
    block = '''    generate for(genvar tp_bp_bank=0;tp_bp_bank<8;tp_bp_bank=tp_bp_bank+1)begin: tp_bias_shadow_banks
        wire capture=tp_bp_capture&&(tp_bp_chunk==3'(tp_bp_bank));
        wire shadow_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(capture),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(shadow_clk));
        always @(posedge shadow_clk)if(capture)begin
            tp_bp_bias[tp_bp_bank*64+:64]<=bias_rdata;
            tp_bp_shift[tp_bp_bank*16+:16]<=shift_rdata;
        end
    end endgenerate
'''
    # Place the shadow block after both macro return buses are declared.
    text = _replace(text, '    wire [15:0] shift_rdata;', '    wire [15:0] shift_rdata;\n' + block)
    text = _replace(text, "wire [15:0] bias_address=16'(tile*LANES*4+chunk*8);",
                    "wire [15:0] bias_address=16'(int'(tp_bp_read_tile)*LANES*4+int'(tp_bp_read_chunk)*8);")
    text = _replace(text, 'BIAS32?(tile*(LANES/2)+chunk)',
                    "BIAS32?(int'(tp_bp_read_tile)*(LANES/2)+int'(tp_bp_read_chunk))")
    text = _replace(text, "shift_addr=7'(tile*(LANES/2)+chunk);",
                    "shift_addr=7'(int'(tp_bp_read_tile)*(LANES/2)+int'(tp_bp_read_chunk));")
    text = _replace(text, '.enable(bias_capture||(state==B_MAC)||(state==ROW1_MAC)||fifo_push)',
                    '.enable(bias_capture||tp_bp_seed||(state==B_MAC)||(state==ROW1_MAC)||fifo_push)')
    text = _replace(text, '                    if(bias_update&&chunk==lane_id/2) begin',
                    '''                    if(tp_bp_seed)begin
                        accumulator[group_id*LANES+lane_id]<=36'($signed(tp_bp_bias[lane_id*32+:32]));
                        shifts[group_id*LANES+lane_id]<=$signed(tp_bp_shift[lane_id*8+:8]);
                    end
                    if(bias_update&&chunk==lane_id/2) begin''')
    text = _replace(text, 'MAC_INIT:begin chunk<=0;state<=BIAS_REQ;end',
                    '''MAC_INIT:begin chunk<=0;state<=tp_bp_valid?TP_BP_SEED:BIAS_REQ;end
                TP_BP_SEED:begin inner<=0;mac_group<=0;state<=A_REQ;end''')
    return text


def _paired_emit(text):
    text = _replace(text, 'wire fifo_push=emission&&((fifo_count<16)||(pop_count!=0));',
                    "wire fifo_push=emission&&((6'(fifo_count)+6'd2)<=(6'd16+6'(pop_count)));\n    wire [1:0] tp_push_count=fifo_push?2'd2:2'd0;")
    at = '    wire stash_write=state==EMIT_STASH;'
    block = '''    wire [35:0] tp_high_quant_bits=accumulator[emit_group*LANES+lane+1];
    wire signed [63:0] tp_high_quant_value={{28{tp_high_quant_bits[35]}},tp_high_quant_bits};
    wire signed [15:0] tp_result_high;
    kwt_ffn_requantize tp_high_quantizer(.value(tp_high_quant_value),
        .shift(shifts[emit_group*LANES+lane+1]),.result(tp_result_high));
'''
    text = _replace(text, at, block + at)
    text = _replace(text, "always @(posedge bank_clk) if(bank_write&&fifo_write[0]==1'(word_id))\n                fifo[fifo_bank*2+word_id]<=fifo_word;",
                    'always @(posedge bank_clk) if(bank_write)\n                fifo[fifo_bank*2+word_id]<=word_id==0?fifo_word:tp_result_high;')
    text = _replace(text, "if(fifo_push) fifo_write<=fifo_write+1'b1;",
                    "if(fifo_push) fifo_write<=fifo_write+4'd2;")
    text = _replace(text, "fifo_count<=fifo_count+5'(fifo_push)-5'(pop_count);",
                    "fifo_count<=fifo_count+5'(tp_push_count)-5'(pop_count);")
    text = _replace(text, 'EMIT:if(fifo_push) begin\n                    if(lane<LANES-1) lane<=lane+1;',
                    'EMIT:if(fifo_push) begin\n                    if(lane<LANES-2) lane<=lane+2;')
    return text


def transform(source: str, hardware: list) -> str:
    flags = set(hardware)
    text = _trace_ports(source)
    if 'BP' in flags and 'TP_BP_SEED=' not in text:
        text = _bias_prefetch(text)
    if 'E2' in flags and 'wire [1:0] tp_push_count=' not in text:
        text = _paired_emit(text)
    if 'assign trace_pair_valid=' not in text:
        if 'wire [1:0] tp_push_count=' in text:
            assignments = '''    assign trace_pair_valid=fifo_push;
    assign trace_high={{48{tp_result_high[15]}},tp_result_high};
'''
        else:
            assignments = "    assign trace_pair_valid=1'b0;\n    assign trace_high=64'sd0;\n"
        text = _replace(text, '    assign trace_valid=fifo_push;', assignments + '    assign trace_valid=fifo_push;')
    return text
