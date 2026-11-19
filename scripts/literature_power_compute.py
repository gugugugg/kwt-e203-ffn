"""Lossless storage coding, controlled Booth directions and exact M28 state."""

def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError('Inspect accepted IR source fragment: '+old[:90])
    return text.replace(old,new,1)

def csa_tree():
    lines=[]
    names=['lit_terms[%d]'%i for i in range(8)]+['accumulator[jp_lane]']
    for stage in range(4):
        next_names=[]
        for group in range(len(names)//3):
            a,b,c=names[group*3:group*3+3]
            s='lit_csa_%d_%d_s'%(stage,group);v='lit_csa_%d_%d_c'%(stage,group)
            lines+=['        wire [35:0] %s=%s^%s^%s;'%(s,a,b,c),
                    '        wire [35:0] %s=((%s&%s)|(%s&%s)|(%s&%s))<<1;'%(v,a,b,a,c,b,c)]
            next_names.extend([s,v])
        next_names.extend(names[(len(names)//3)*3:]);names=next_names
    if len(names)!=2:raise ValueError('The fixed nine-term compressor must end at two operands')
    lines.append('        wire [35:0] lit_mac_next=%s+%s;'%tuple(names))
    return '\n'.join(lines)+'\n'

def shared_booth(direction):
    count=2 if direction=='BA' else 8
    value='lit_input_values[lit_source*16+:16]' if direction=='BA' else 'lit_weight_values[lit_source*16+:16]'
    return '''    wire [23:0] lit_booth_code[0:COUNT-1];
    generate for(genvar lit_source=0;lit_source<COUNT;lit_source=lit_source+1)begin: lit_shared_booth
        wire [16:0] extended={VALUE,1'b0};
        for(genvar digit=0;digit<8;digit=digit+1)begin: digits
            assign lit_booth_code[lit_source][digit*3+:3]=extended[digit*2+:3];
        end
    end endgenerate
'''.replace('COUNT',str(count)).replace('VALUE',value)

def shared_multiplicands(direction):
    count=8 if direction=='BA' else 2
    values='lit_weight_values' if direction=='BA' else 'lit_input_values'
    return '''    wire [COUNT*18-1:0] lit_pp_positive,lit_pp_negative;
    generate for(genvar lit_operand=0;lit_operand<COUNT;lit_operand=lit_operand+1)begin: lit_shared_multiplicands
        wire signed [17:0] positive=18'($signed(VALUES[lit_operand*16+:16]));
        assign lit_pp_positive[lit_operand*18+:18]=positive;
        assign lit_pp_negative[lit_operand*18+:18]=-positive;
    end endgenerate
'''.replace('COUNT',str(count)).replace('VALUES',values)


def transform(text,changes):
    declarations='''    function automatic [15:0] lit_code(input [15:0] value);
        begin lit_code={value[15],value[14:0]^{15{value[15]}}};end
    endfunction
    wire [31:0] lit_input_values;
    wire [127:0] lit_weight_values;
    generate for(genvar lit_input=0;lit_input<2;lit_input=lit_input+1)begin: lit_input_decode
        assign lit_input_values[lit_input*16+:16]=INPUT_VALUE;
    end endgenerate
    generate for(genvar lit_column=0;lit_column<8;lit_column=lit_column+1)begin: lit_weight_decode
        wire [15:0] selected=pm_rdata[(int'(tile[0])*8+lit_column)*16+:16];
        assign lit_weight_values[lit_column*16+:16]=WEIGHT_VALUE;
    end endgenerate
'''
    declarations=declarations.replace('INPUT_VALUE','lit_code(jp_input_return[lit_input*16+:16])' if 'IE' in changes else 'jp_input_return[lit_input*16+:16]')
    declarations=declarations.replace('WEIGHT_VALUE','lit_code(selected)' if 'WE' in changes else 'selected')
    text=replace_once(text,'    wire [3:0] jp_quant_lane={emit_row,lane};',declarations+'    wire [3:0] jp_quant_lane={emit_row,lane};')
    text=replace_once(text,'activation=$signed(jp_input_return[jp_row*16+:16]);','activation=$signed(lit_input_values[jp_row*16+:16]);')
    text=replace_once(text,"weight_value=$signed(pm_rdata[(int'(tile[0])*8+jp_column)*16+:16]);",'weight_value=$signed(lit_weight_values[jp_column*16+:16]);')
    if 'WE' in changes:
        text=replace_once(text,'.wdata(pm_wdata[bank*16+:16]),.rdata(pm_rdata[bank*16+:16]));',
            '.wdata(lit_code(pm_wdata[bank*16+:16])),.rdata(pm_rdata[bank*16+:16]));')
    if 'IE' in changes:
        text=replace_once(text,'.addr(memory_addr),.wdata(load_data),.rdata(ap_input_rdata',
            '.addr(memory_addr),.wdata(lit_code(load_data)),.rdata(ap_input_rdata')
    direction=next((v for v in ['BA','BW'] if v in changes),None)
    if direction:
        text=replace_once(text,'    generate for(genvar jp_lane=0;jp_lane<16;jp_lane=jp_lane+1)begin: jp_mac_lanes',
            shared_booth(direction)+shared_multiplicands(direction)+'    generate for(genvar jp_lane=0;jp_lane<16;jp_lane=jp_lane+1)begin: jp_mac_lanes')
        source='jp_row' if direction=='BA' else 'jp_column'
        operand='jp_column' if direction=='BA' else 'jp_row'
        block='''        wire signed [17:0] lit_multiplicand=$signed(lit_pp_positive[OPERAND*18+:18]);
        wire signed [17:0] lit_negative=$signed(lit_pp_negative[OPERAND*18+:18]);
        wire [35:0] lit_terms[0:7];
        for(genvar lit_digit=0;lit_digit<8;lit_digit=lit_digit+1)begin: booth_partial_products
            reg signed [17:0] unshifted;
            always @*begin
                case(lit_booth_code[SOURCE][lit_digit*3+:3])
                    3'b001,3'b010:unshifted=lit_multiplicand;
                    3'b011:unshifted=lit_multiplicand<<<1;
                    3'b100:unshifted=lit_negative<<<1;
                    3'b101,3'b110:unshifted=lit_negative;
                    default:unshifted=0;
                endcase
            end
            assign lit_terms[lit_digit]=36'($signed(unshifted))<<<(lit_digit*2);
        end
'''.replace('OPERAND',operand).replace('SOURCE',source)+csa_tree()
        text=replace_once(text,'        always @(posedge accumulator_clk or negedge rst_n)begin',block+'        always @(posedge accumulator_clk or negedge rst_n)begin')
        text=replace_once(text,"accumulator[jp_lane]+36'(activation*weight_value)",'lit_mac_next')
    if 'M28' in changes:
        text=replace_once(text,'    reg signed [35:0] accumulator[0:15];',
            '    reg signed [35:0] accumulator[0:15];\n    reg signed [27:0] lit_narrow[0:15];\n    wire [15:0] lit_wide_need;')
        text=replace_once(text,'wire [35:0] quant_bits=accumulator[jp_quant_lane];',
            "wire [35:0] quant_bits=accumulator[jp_quant_lane]+36'($signed(lit_narrow[jp_quant_lane]));")
        text=replace_once(text,"wire [35:0] tp_high_quant_bits=accumulator[{1'b0,jp_quant_lane}+5'd1];",
            "wire [35:0] tp_high_quant_bits=accumulator[{1'b0,jp_quant_lane}+5'd1]+36'($signed(lit_narrow[{1'b0,jp_quant_lane}+5'd1]));")
        start=text.index('        always @(posedge accumulator_clk or negedge rst_n)begin')
        end=text.index('        always @(posedge shift_register_clk',start)
        text=text[:start]+'''        wire signed [31:0] lit_product=$signed(lit_input_values[jp_row*16+:16])*weight_value;
        wire lit_product_fits=(lit_product[31:27]=={5{lit_product[27]}});
        wire signed [28:0] lit_narrow_sum={lit_narrow[jp_lane][27],lit_narrow[jp_lane]}+
            {lit_product[27],lit_product[27:0]};
        wire lit_flush=lit_product_fits&&(lit_narrow_sum[28]!=lit_narrow_sum[27]);
        assign lit_wide_need[jp_lane]=seed_update||(mac_update&&(!lit_product_fits||lit_flush));
        wire lit_wide_clk;
        if(jp_column%2==0)begin: wide_pair
            kwt_ffn_clock_gate gate(.clk(clk),.enable(|lit_wide_need[jp_lane+:2]),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(lit_wide_clk));
        end else assign lit_wide_clk=jp_mac_lanes[jp_lane-1].lit_wide_clk;
        always @(posedge accumulator_clk or negedge rst_n)begin
            if(!rst_n)lit_narrow[jp_lane]<=0;
            else if(seed_update)lit_narrow[jp_lane]<=0;
            else if(mac_update&&lit_product_fits)
                lit_narrow[jp_lane]<=lit_flush?lit_product[27:0]:lit_narrow_sum[27:0];
        end
        always @(posedge lit_wide_clk or negedge rst_n)begin
            if(!rst_n)accumulator[jp_lane]<=0;
            else if(seed_update)accumulator[jp_lane]<=36'($signed(bias_pair[(jp_column%2)*64+:64]));
            else if(mac_update&&!lit_product_fits)accumulator[jp_lane]<=accumulator[jp_lane]+36'($signed(lit_product));
            else if(mac_update&&lit_flush)accumulator[jp_lane]<=accumulator[jp_lane]+36'($signed(lit_narrow[jp_lane]));
        end
'''+text[end:]
    return text
