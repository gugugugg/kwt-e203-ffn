    wire [3:0] w32_product_valid,w32_product_upper,w32_product_first,w32_product_tail;
    wire [35:0] w32_next_value[0:31];
    wire [7:0] w32_next_shift[0:15];
    generate for(genvar q=0;q<4;q=q+1)begin: w32_columns
        wire accept_even=iw_mac_valid[q]&&!iw_mac_inner[q][0];
        wire accept_odd=iw_mac_valid[q]&&iw_mac_inner[q][0];
        wire accept_first=accept_odd&&iw_mac_inner[q]==1;
        reg upper_pending,product_valid,product_upper,first_pair,product_first,tail,product_tail;
        reg [63:0] even_input,even_weight,odd_input,odd_weight;
        reg [143:0] seed_bias;
        reg [11:0] seed_shift;
        reg [143:0] seed_correction;
        wire even_clk,odd_clk,seed_clk,preadder_clk;
        wire [63:0] current_input;
        for(genvar r=0;r<4;r=r+1)begin: row_input
            assign current_input[16*r+:16]=jp_input_return[(4*r+q)*16+:16];
        end
        wire [63:0] current_weight=operand_weight[64*q+:64];
        wire [77:0] seed0=wp_boot?w32_boot_seed[(q%2)*2]:q16_seed_shadow[2*q];
        wire [77:0] seed1=wp_boot?w32_boot_seed[(q%2)*2+1]:q16_seed_shadow[2*q+1];

        kwt_ffn_clock_gate even_gate(.clk(clk),.enable(accept_even),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(even_clk));
        kwt_ffn_clock_gate odd_gate(.clk(clk),.enable(accept_odd),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(odd_clk));
        kwt_ffn_clock_gate seed_gate(.clk(clk),.enable(accept_first),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(seed_clk));
        kwt_ffn_clock_gate preadder_gate(.clk(clk),.enable(accept_odd||upper_pending),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(preadder_clk));
        always @(posedge even_clk)if(accept_even)begin
            even_input<=current_input;even_weight<=current_weight;
        end
        always @(posedge odd_clk)if(accept_odd)begin
            odd_input<=current_input;odd_weight<=current_weight;
        end
        always @(posedge seed_clk)if(accept_first)begin
            seed_bias<={seed1[71:0],seed0[71:0]};
            seed_shift<={seed1[77:72],seed0[77:72]};
            for(integer r=0;r<4;r=r+1)
                seed_correction[r*36+:36]<=-w32_correction[{1'b0,iw_mac_generation[q],2'(r)}];
        end
        always @(posedge clk or negedge rst_n)begin
            if(!rst_n)begin
                upper_pending<=0;product_valid<=0;product_upper<=0;
                first_pair<=0;product_first<=0;tail<=0;product_tail<=0;
            end else begin
                upper_pending<=accept_odd;
                product_valid<=accept_odd||upper_pending;
                product_upper<=upper_pending;
                if(accept_odd)begin first_pair<=accept_first;tail<=iw_mac_tail[q];end
                if(accept_odd||upper_pending)begin
                    product_first<=upper_pending?first_pair:accept_first;
                    product_tail<=upper_pending?tail:iw_mac_tail[q];
                end
            end
        end
        assign w32_product_valid[q]=product_valid;
        assign w32_product_upper[q]=product_upper;
        assign w32_product_first[q]=product_first;
        assign w32_product_tail[q]=product_tail;
        for(genvar col=0;col<4;col=col+1)begin: shift_values
            assign w32_next_shift[q*4+col]=w32_decode_shift(seed_shift[3*col+:3]);
        end

        for(genvar p=0;p<8;p=p+1)begin: paired_mac
            localparam integer R=p/4,C=p%4;
            localparam integer L0=16*R+4*q+C,L1=L0+32;
            wire signed [15:0] a_even=upper_pending?even_input[16*(R+2)+:16]:even_input[16*R+:16];
            wire signed [15:0] a_odd=upper_pending?odd_input[16*(R+2)+:16]:current_input[16*R+:16];
            wire signed [15:0] w_even=even_weight[16*C+:16];
            wire signed [15:0] w_odd=upper_pending?odd_weight[16*C+:16]:current_weight[16*C+:16];
            reg signed [16:0] x,y;
            always @(posedge preadder_clk)if(accept_odd||upper_pending)begin
                x<=17'(a_even)+17'(w_odd);
                y<=17'(a_odd)+17'(w_even);
            end
            wire signed [33:0] product=x*y;
            wire [35:0] value=36'(product);
            wire [35:0] feedback=product_upper?accumulator[L1]:accumulator[L0];
            wire [35:0] a=product_first?seed_bias[36*C+:36]:feedback;
            wire [35:0] b=product_first?(product_upper?
                seed_correction[36*(R+2)+:36]:seed_correction[36*R+:36]):36'd0;
            wire [35:0] carry=((a&b)|(a&value)|(b&value))<<1;
            assign w32_next_value[q*8+p]=(a^b^value)+carry;
        end
    end endgenerate

    generate for(genvar jp_lane=0;jp_lane<MAC_LANES;jp_lane=jp_lane+1)begin: jp_mac_lanes
        localparam integer jp_row=jp_lane/MAC_COLUMNS;
        localparam integer jp_column=jp_lane%MAC_COLUMNS;
        localparam integer Q=jp_column/4,P=(jp_row%2)*4+jp_column%4;
        wire mac_update=w32_product_valid[Q]&&(w32_product_upper[Q]==(jp_row>=2))&&
                        (jp_row!=3||!w32_product_tail[Q]);
        wire seed_update=mac_update&&w32_product_first[Q];
        wire [7:0] seed_shift=w32_next_shift[jp_column];
        wire quant_commit=jp_quant_commit&&(3'(jp_row)<quant_valid_rows)&&(lane[3:2]==2'(Q));
        assign jp_seed_mask[jp_lane]=seed_update;
        assign jp_mac_mask[jp_lane]=mac_update;
        assign jp_quant_mask[jp_lane]=quant_commit;
        wire accumulator_clk,shift_register_clk;
        if(jp_column%2==0)begin: pair_gate
            kwt_ffn_clock_gate acc_gate(.clk(clk),.enable(mac_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(accumulator_clk));
            kwt_ffn_clock_gate shift_gate(.clk(clk),.enable(seed_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(shift_register_clk));
        end else begin
            assign accumulator_clk=jp_mac_lanes[jp_lane-1].accumulator_clk;
            assign shift_register_clk=jp_mac_lanes[jp_lane-1].shift_register_clk;
        end
        always @(posedge accumulator_clk)if(mac_update)accumulator[jp_lane]<=w32_next_value[Q*8+P];
        always @(posedge shift_register_clk)if(seed_update)shifts[jp_lane]<=seed_shift;
    end endgenerate
