    // The same two correction lanes accept either an input beat or a weight beat.
    reg [1:0] w32_input_ready;
    reg [6:0] w32_weight_ready;
    reg signed [15:0] w32_even[0:11];
    reg signed [35:0] w32_correction[0:11];
    reg signed [35:0] w32_final_weight[0:3];
    wire w32_input_load=input_loading&&input_count<6336;
    wire w32_weight_load=loading&&wp_boot&&load_kind==1&&load_addr==16'(wp_weight_count);
    wire [1:0] w32_even_write,w32_term_write;
    wire [3:0] w32_load_index[0:1],w32_term_index[0:1];
    wire [15:0] w32_load_value[0:1];
    wire [31:0] w32_term[0:1];
    wire [1:0] w32_term_start,w32_input_end,w32_weight_end,w32_weight_last;
    wire [1:0] w32_input_begin;
    function automatic [2:0] w32_encode_shift(input [7:0] raw);
        case(raw)
            8'd13:w32_encode_shift=1; 8'd14:w32_encode_shift=2;
            8'd15:w32_encode_shift=3; 8'd16:w32_encode_shift=4;
            8'd17:w32_encode_shift=5; 8'd18:w32_encode_shift=6;
            default:w32_encode_shift=0;
        endcase
    endfunction
    function automatic [7:0] w32_decode_shift(input [2:0] code);
        w32_decode_shift=(code==0||code==7)?8'd0:8'd12+8'(code);
    endfunction

    generate for(genvar half=0;half<2;half=half+1)begin: w32_load_correction
        wire accept_half=(half==0)||load_count==2;
        wire [8:0] cursor=(half==0)?input_write_cursor:input_high_cursor;
        wire [15:0] address=load_addr+16'(half);
        wire [5:0] k_index=w32_input_load?cursor[7:2]:address[7:2];
        wire issue=(w32_input_load||w32_weight_load)&&accept_half;
        assign w32_load_index[half]=w32_input_load?{1'b0,cursor[8],cursor[1:0]}:{2'b10,address[1:0]};
        assign w32_load_value[half]=(half==0)?load_data:load_high;
        assign w32_even_write[half]=issue&&!k_index[0];
        wire multiply=issue&&k_index[0];
        assign w32_input_begin[half]=issue&&w32_input_load&&cursor[7:0]==0;
        wire signed [15:0] left=multiply?w32_even[w32_load_index[half]]:16'sd0;
        wire signed [15:0] right=multiply?w32_load_value[half]:16'sd0;
        reg valid,first,input_end,weight_end,weight_last;
        reg [3:0] dest;
        reg signed [31:0] product;
        wire capture_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(multiply),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(capture_clk));
        always @(posedge capture_clk)if(multiply)begin
            product<=left*right;
            dest<=w32_load_index[half];
            first<=k_index==1;
            input_end<=w32_input_load&&k_index==63&&
                (address>=6144?cursor[1:0]==2:cursor[1:0]==3);
            weight_end<=w32_weight_load&&k_index==63;
            weight_last<=w32_weight_load&&address[7:0]==8'hff;
        end
        always @(posedge clk or negedge rst_n)begin
            if(!rst_n)valid<=0;
            else valid<=multiply;
        end
        assign w32_term_write[half]=valid;
        assign w32_term_index[half]=dest;
        assign w32_term[half]=product;
        assign w32_term_start[half]=first;
        assign w32_input_end[half]=input_end;
        assign w32_weight_end[half]=weight_end;
        assign w32_weight_last[half]=weight_last;
    end endgenerate

    generate for(genvar slot=0;slot<12;slot=slot+1)begin: w32_correction_slots
        wire even_low=w32_even_write[0]&&w32_load_index[0]==4'(slot);
        wire even_high=w32_even_write[1]&&w32_load_index[1]==4'(slot);
        wire term_low=w32_term_write[0]&&w32_term_index[0]==4'(slot);
        wire term_high=w32_term_write[1]&&w32_term_index[1]==4'(slot);
        wire signed [31:0] term=term_high?w32_term[1]:w32_term[0];
        wire first=term_high?w32_term_start[1]:w32_term_start[0];
        wire signed [35:0] next_sum=(first?36'sd0:w32_correction[slot])+36'(term);
        wire even_clk,term_clk;
        kwt_ffn_clock_gate even_gate(.clk(clk),.enable(even_low||even_high),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(even_clk));
        kwt_ffn_clock_gate term_gate(.clk(clk),.enable(term_low||term_high),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(term_clk));
        always @(posedge even_clk)if(even_low||even_high)
            w32_even[slot]<=even_high?w32_load_value[1]:w32_load_value[0];
        always @(posedge term_clk)if(term_low||term_high)begin
            w32_correction[slot]<=next_sum;
            if(slot>=8)begin
                if(term_high?w32_weight_end[1]:w32_weight_end[0])
                    w32_final_weight[slot-8]<=next_sum;
            end
        end
    end endgenerate
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin w32_input_ready<=0;w32_weight_ready<=0;end
        else if(start_ready&&start_valid)begin w32_input_ready<=0;w32_weight_ready<=0;end
        else begin
            if((w32_term_write[0]&&w32_weight_last[0])||(w32_term_write[1]&&w32_weight_last[1]))
                w32_weight_ready<=w32_weight_ready+1'b1;
            for(integer j=0;j<2;j=j+1)begin
                if(w32_input_begin[j])w32_input_ready[w32_load_index[j][2]]<=0;
                if(w32_term_write[j]&&w32_input_end[j])w32_input_ready[w32_term_index[j][2]]<=1;
            end
        end
    end

    // Corrected pairs overwrite the original bias and shift words in place.
    reg [7:0] w32_raw_requested,w32_raw_captured,w32_corrected;
    reg [7:0] w32_seed_requested,w32_seed_captured;
    reg w32_bias_pending,w32_bias_is_seed;
    reg [1:0] w32_bias_return_slot;
    reg [79:0] w32_raw_bias[0:1];
    reg [77:0] w32_boot_seed[0:3];
    wire w32_bias_write=wp_boot&&w32_corrected<w32_raw_captured&&
                        w32_corrected[7:1]<w32_weight_ready;
    wire w32_seed_read=wp_boot&&!w32_bias_write&&w32_seed_requested<w32_corrected&&
                       !wp_count[13]&&w32_seed_requested[7:1]<=7'(wp_count[12:7])+7'd1;
    wire w32_raw_read=wp_boot&&!w32_bias_write&&!w32_seed_read&&w32_raw_requested<128&&
                      w32_raw_requested[7:1]==w32_corrected[7:1]&&
                      wp_weight_count>{w32_raw_requested[7:1],8'b0};
    wire [6:0] w32_bias_address=w32_bias_write?w32_corrected[6:0]:
                     w32_seed_read?w32_seed_requested[6:0]:w32_raw_requested[6:0];
    wire [79:0] w32_raw_pair=w32_raw_bias[w32_corrected[0]];
    wire signed [35:0] w32_bias_low=36'($signed(w32_raw_pair[31:0]))-
        w32_final_weight[{w32_corrected[0],1'b0}];
    wire signed [35:0] w32_bias_high=36'($signed(w32_raw_pair[63:32]))-
        w32_final_weight[{w32_corrected[0],1'b1}];
    wire [77:0] w32_seed_word={jp_shift_return[10:8],jp_shift_return[2:0],
        jp_shift_return[14:11],bias_rdata[63:32],jp_shift_return[6:3],bias_rdata[31:0]};
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            w32_raw_requested<=0;w32_raw_captured<=0;w32_corrected<=0;
            w32_seed_requested<=0;w32_seed_captured<=0;w32_bias_pending<=0;
            w32_bias_is_seed<=0;w32_bias_return_slot<=0;
        end else if(layer_start_valid&&layer_start_ready)begin
            w32_raw_requested<=0;w32_raw_captured<=0;w32_corrected<=0;
            w32_seed_requested<=0;w32_seed_captured<=0;w32_bias_pending<=0;
        end else if(wp_boot)begin
            w32_bias_pending<=w32_raw_read||w32_seed_read;
            if(w32_bias_write)w32_corrected<=w32_corrected+1'b1;
            if(w32_raw_read)begin
                w32_bias_is_seed<=0;w32_bias_return_slot<={1'b0,w32_raw_requested[0]};
                w32_raw_requested<=w32_raw_requested+1'b1;
            end
            if(w32_seed_read)begin
                w32_bias_is_seed<=1;w32_bias_return_slot<=w32_seed_requested[1:0];
                w32_seed_requested<=w32_seed_requested+1'b1;
            end
            if(w32_bias_pending)begin
                if(w32_bias_is_seed)w32_seed_captured<=w32_seed_captured+1'b1;
                else w32_raw_captured<=w32_raw_captured+1'b1;
            end
        end
    end
    generate for(genvar slot=0;slot<4;slot=slot+1)begin: w32_seed_slots
        wire take_seed=w32_bias_pending&&w32_bias_is_seed&&w32_bias_return_slot==2'(slot);
        wire seed_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(take_seed),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(seed_clk));
        always @(posedge seed_clk)if(take_seed)w32_boot_seed[slot]<=w32_seed_word;
        if(slot<2)begin: raw
            wire take_raw=w32_bias_pending&&!w32_bias_is_seed&&w32_bias_return_slot==2'(slot);
            wire raw_clk;
            kwt_ffn_clock_gate gate(.clk(clk),.enable(take_raw),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(raw_clk));
            always @(posedge raw_clk)if(take_raw)w32_raw_bias[slot]<={jp_shift_return,bias_rdata};
        end
    end endgenerate
