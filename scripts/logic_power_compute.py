"""The fixed round-eight changes, applied directly to accepted HM2."""

def c4(text):
    text=text.replace('reg signed [35:0] accumulator[0:15];',
        'reg [35:0] lp_sum[0:15];\n    reg [7:0] lp_carry[0:15];')
    declaration='''function automatic [35:0] lp_expand_carry(input [7:0] value);
        integer bit_id;
        begin
            lp_expand_carry=0;
            for(bit_id=0;bit_id<8;bit_id=bit_id+1)lp_expand_carry[(bit_id+1)*4]=value[bit_id];
        end
    endfunction
    '''
    text=text.replace('wire [3:0] jp_quant_lane={emit_row,lane};',declaration+'wire [3:0] jp_quant_lane={emit_row,lane};')
    text=text.replace('accumulator[jp_quant_lane];','lp_sum[jp_quant_lane]+lp_expand_carry(lp_carry[jp_quant_lane]);')
    text=text.replace("accumulator[{1'b0,jp_quant_lane}+5'd1];",
        "lp_sum[{1'b0,jp_quant_lane}+5'd1]+lp_expand_carry(lp_carry[{1'b0,jp_quant_lane}+5'd1]);")
    a=text.index('        always @(posedge accumulator_clk or negedge rst_n)begin')
    b=text.index('        always @(posedge shift_register_clk',a)
    text=text[:a]+'''        wire signed [31:0] lp_product=$signed(jp_input_return[jp_row*16+:16])*weight_value;
        wire [35:0] lp_product_extended={{4{lp_product[31]}},lp_product};
        wire [35:0] lp_next_sum;
        wire [7:0] lp_next_carry;
        for(genvar lp_segment=0;lp_segment<9;lp_segment=lp_segment+1)begin: segmented_mac
            wire [4:0] old_carry;
            if(lp_segment==0)assign old_carry=5'd0;
            else assign old_carry={4'd0,lp_carry[jp_lane][lp_segment-1]};
            wire [4:0] temporary_sum={1'b0,lp_sum[jp_lane][lp_segment*4+:4]}+
                {1'b0,lp_product_extended[lp_segment*4+:4]}+old_carry;
            assign lp_next_sum[lp_segment*4+:4]=temporary_sum[3:0];
            if(lp_segment<8)assign lp_next_carry[lp_segment]=temporary_sum[4];
        end
        always @(posedge accumulator_clk or negedge rst_n)begin
            if(!rst_n)begin lp_sum[jp_lane]<=0;lp_carry[jp_lane]<=0;end
            else if(seed_update)begin
                lp_sum[jp_lane]<=36'($signed(bias_pair[(jp_column%2)*64+:64]));
                lp_carry[jp_lane]<=0;
            end else if(mac_update)begin lp_sum[jp_lane]<=lp_next_sum;lp_carry[jp_lane]<=lp_next_carry;end
        end
'''+text[b:]
    return text

def input_return(text):
    text=text.replace('    wire [31:0] ap_input_rdata;',
        '    wire [31:0] ap_input_rdata;\n    reg [31:0] jp_input_return;')
    marker='        wire memory_clk;\n        kwt_ffn_clock_gate gate'
    text=text.replace(marker,'''        wire lp_return_clock;
        kwt_ffn_clock_gate return_gate(.clk(clk),.enable(read_enable),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(lp_return_clock));
        always_latch if(lp_return_clock)jp_input_return[ap_row*16+:16]<=ap_input_rdata[ap_row*16+:16];
'''+marker,1)
    text=text.replace('    reg [31:0] jp_input_return;\n    reg [15:0] jp_shift_return;',
        '    reg [15:0] jp_shift_return;')
    return text.replace('    always_latch if(clk)jp_input_return<=ap_input_rdata;\n','')

def data_quiet(text):
    return text.replace('.addr(memory_addr),.wdata(load_data),.rdata(ap_input_rdata',
        ".addr(memory_addr),.wdata(write_enable?load_data:16'b0),.rdata(ap_input_rdata",1)

def transform(text,changes):
    if 'C4' in changes:text=c4(text)
    if 'IR' in changes:text=input_return(text)
    if 'DQ' in changes:text=data_quiet(text)
    return text
