"""Replace the frozen FFN row registers with two synchronous input macros."""


def _replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Inspect frozen input edit point: ' + before[:100])
    return text.replace(before, after, 1)


def transform_core(text):
    start = text.index('    reg signed [15:0] row_cache[')
    end = text.index('    wire [35:0] quant_bits=', start)
    block = '''    wire row_cache_ready=input_complete;
    wire input_loading=loading&&(load_kind==0);
    wire ap_input_read=((state==A_REQ)&&row_cache_ready)||prefetch;
    wire [31:0] ap_input_rdata;
    generate for(genvar ap_row=0;ap_row<2;ap_row=ap_row+1) begin: ap_input_rows
        wire write_enable=input_loading&&(load_addr[6]==1'(ap_row));
        wire read_enable=ap_input_read&&(row[0]==1'(ap_row));
        wire memory_enable=write_enable||read_enable;
        wire [6:0] memory_addr=write_enable?{1'b0,load_addr[5:0]}:{1'b0,request_inner[5:0]};
        wire memory_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(memory_enable),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(memory_enable),.we(write_enable),
            .addr(memory_addr),.wdata(load_data),.rdata(ap_input_rdata[ap_row*16+:16]));
    end endgenerate
    wire signed [15:0] ap_input_value=row[0]?ap_input_rdata[31:16]:ap_input_rdata[15:0];
    wire signed [16:0] mac_a=$signed(ap_input_value);
'''
    text = text[:start] + block + text[end:]
    text = _replace(text, '''        if(row_cache_issue) begin
            sp_en='1;for(b=0;b<8;b=b+1) sp_addr[b*13+:13]=13'(row*8+row_cache_request);
        end
''', '')
    return text


def transform_wrapper(text):
    text = _replace(text, '.load_pair(packed_load&&load_kind!=5)',
                    '.load_pair(packed_load&&load_kind!=0&&load_kind!=5)')
    text = _replace(text,
                    "load_address<=load_address+((packed_load&&load_kind!=5)?16'd2:16'd1);",
                    "load_address<=load_address+((packed_load&&load_kind!=0&&load_kind!=5)?16'd2:16'd1);")
    text = _replace(text, 'pack_pending<=load_kind==5;',
                    'pack_pending<=(load_kind==0)||(load_kind==5);')
    return text
