// FFN implementation for independent storage, transport and scheduling ablations.
module kwt_encoder #(
    parameter integer SPLIT_BIAS=1, FAST_PAIR=1, OVERLAP=0, LANES=16, CLOCK_GATING=1
)(
    input wire clk,rst_n,clock_test_enable,linear_mode,load_valid,load_pair,
    output wire load_ready,load_capacity_ready,
    input wire [2:0] load_kind,
    input wire [15:0] load_addr,load_data,load_high,
    input wire start_valid,
    output wire start_ready,layer_request,
    output wire [3:0] layer_index,
    input wire layer_start_valid,
    output wire layer_start_ready,busy,
    output reg done,error,layer_done,
    output wire out_valid,out_pair_valid,
    input wire out_ready,out_pair_ready,
    output wire [14:0] out_index,
    output wire signed [15:0] out_data,out_high,
    output wire trace_valid,
    output wire [3:0] trace_layer,trace_stage,
    output wire [14:0] trace_index,
    output wire signed [63:0] trace_data,
    output wire trace_pair_valid,
    output wire signed [63:0] trace_high
);
    localparam integer ROW_GROUP=1,INPUT_SLOTS=2,STREAM_INPUT=1,
        SMALL_INPUT=1,USE_ROW_CACHE=1,ZERO_CLEAR=0,BIAS32=1,BIAS_BANKS=4;
    localparam integer TILES=32,GROUPS=1;
    localparam [4:0] CLEAR=0,IDLE=1,WAIT_LAYER=2,MAC_INIT=3,BIAS_REQ=4,BIAS_CAP=5,
        A_REQ=6,B_MAC=7,EMIT=8,ROW1_MAC=9,ADVANCE=14,WAIT_INPUT=15,DRAIN=12;
    reg [4:0] state;
    reg [13:0] clear_index;
    reg [12:0] input_count;
    reg [14:0] parameter_count;
    reg [7:0] shift_count;
    reg [6:0] row;
    reg [4:0] tile;
    reg [2:0] lane;
    reg [1:0] chunk;
    reg [5:0] inner;
    reg [14:0] item;
    reg emit_row;
    integer address,bank_index,b,k,offset;
    localparam integer mac_group=0,emit_group=0;
    wire [2:0] block_rows=row==98?3'd1:3'd2;
    wire loading=load_valid&&load_ready;
    wire [1:0] load_count=(FAST_PAIR&&load_pair&&load_kind!=5)?2:1;
    wire input_complete={1'b0,input_count}>=((14'({1'b0,row})+14'(block_rows))<<6);
    reg signed [35:0] accumulator[0:15];
    reg signed [7:0] shifts[0:15];
    wire [4:0] fifo_count;
    wire [1:0] pop_count;
    wire emission=state==EMIT;
    wire jp_quant_ready;
    wire jp_quant_commit=emission&&jp_quant_ready;
    wire fifo_push=jp_quant_commit&&!emit_row;
    wire [1:0] tp_push_count=fifo_push?2'd2:2'd0;
    reg ap_er_next_seed_ready;
    wire ap_er_seed_wait=(state==MAC_INIT)&&ap_er_next_seed_ready;
    wire ap_er_has_next=(row<98)||(tile<31);
    wire jp_next_row1=(tile==31)?(row<96):(row<98);
    wire ap_er_first_request=(state==B_MAC)&&(inner==63)&&ap_er_has_next;
    wire jp_last_emit_row=emit_row||(row==98);
    wire ap_er_reseed=jp_quant_commit&&ap_er_has_next;
    wire ap_er_next_request=ap_er_reseed&&jp_last_emit_row&&(lane<6);
    wire ap_er_request=ap_er_first_request||ap_er_next_request;
    wire [4:0] ap_er_target_tile=tile==31?5'd0:tile+5'd1;
    wire [1:0] ap_er_request_pair=ap_er_first_request?2'd0:lane[2:1]+2'd1;
    wire [4:0] ap_bias_tile=ap_er_request?ap_er_target_tile:tile;
    wire [1:0] ap_bias_pair=ap_er_request?ap_er_request_pair:chunk;
    wire bias_request=(state==BIAS_REQ)||ap_er_request;
    wire bias_capture=state==BIAS_CAP;
    wire [15:0] jp_seed_mask,jp_mac_mask,jp_quant_mask;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)ap_er_next_seed_ready<=0;
        else if(layer_start_valid&&layer_start_ready)ap_er_next_seed_ready<=0;
        else begin
            if(ap_er_seed_wait)ap_er_next_seed_ready<=0;
            if(ap_er_reseed&&jp_last_emit_row&&lane==6)ap_er_next_seed_ready<=1;
        end
    end
    wire prefetch=(state==B_MAC)&&(inner<63);
    wire [5:0] request_inner=6'({1'b0,inner}+7'(prefetch));
    function automatic [5:0] ap_gray6(input [5:0] value);
        begin ap_gray6=value^(value>>1);end
    endfunction
    wire [12:0] ap_weight_read_address={3'b000,ap_gray6(request_inner),tile[4:1]};
    wire [15:0] bias_address=16'(int'(ap_bias_tile)*32+int'(ap_bias_pair)*8);
    reg [7:0] sp_en,sp_we;
    reg [103:0] sp_addr;
    reg [127:0] sp_wdata;
    wire [127:0] sp_rdata;
    reg [LANES-1:0] pm_en,pm_we;
    reg [13*LANES-1:0] pm_addr;
    reg [16*LANES-1:0] pm_wdata;
    wire [16*LANES-1:0] pm_rdata;
    reg [BIAS_BANKS-1:0] bias_en,bias_we;
    reg [7*BIAS_BANKS-1:0] bias_addr;
    reg [16*BIAS_BANKS-1:0] bias_wdata;
    wire [16*BIAS_BANKS-1:0] bias_rdata;
    wire [127:0] bias_pair;
    generate if(BIAS32) begin
        assign bias_pair={{32{bias_rdata[63]}},bias_rdata[63:32],{32{bias_rdata[31]}},bias_rdata[31:0]};
    end else assign bias_pair=bias_rdata[(chunk*8%BIAS_BANKS)*16+:128];endgenerate
    reg shift_en,shift_we;
    reg [6:0] shift_addr;
    reg [15:0] shift_wdata;
    wire [15:0] shift_rdata;

    generate if(!SMALL_INPUT) begin: full_input_storage
        kwt_encoder_memory #(.BANK_LEAVES(1)) scratch(.clk(clk),.en(sp_en),.we(sp_we),
            .addr(sp_addr),.wdata(sp_wdata),.rdata(sp_rdata));
    end else assign sp_rdata=0;endgenerate
    generate for(genvar bank=0;bank<LANES;bank=bank+1) begin: parameter_banks
        wire weight_clk;
        if(CLOCK_GATING) begin: gated
            kwt_ffn_clock_gate gate(.clk(clk),.enable(pm_en[bank]),.test_enable(clock_test_enable||!rst_n),.gated_clk(weight_clk));
        end else assign weight_clk=clk;
        kwt_spmem16 #(.ADDR_WIDTH(13),.BANKS(16/LANES)) weights(.clk(weight_clk),
            .en(pm_en[bank]),.we(pm_we[bank]),.addr(pm_addr[bank*13+:13]),
            .wdata(pm_wdata[bank*16+:16]),.rdata(pm_rdata[bank*16+:16]));
    end endgenerate
    generate for(genvar bank=0;bank<BIAS_BANKS;bank=bank+1) begin: compact_bias_banks
        wire bias_clk;
        if(CLOCK_GATING) begin: gated
            kwt_ffn_clock_gate gate(.clk(clk),.enable(bias_en[bank]),.test_enable(clock_test_enable||!rst_n),.gated_clk(bias_clk));
        end else assign bias_clk=clk;
        kwt_encoder_sram16x128 memory(.clk(bias_clk),.en(bias_en[bank]),.we(bias_we[bank]),
            .addr(bias_addr[bank*7+:7]),.wdata(bias_wdata[bank*16+:16]),.rdata(bias_rdata[bank*16+:16]));
    end endgenerate
    wire shift_clk;
    generate if(CLOCK_GATING) begin: gate_shift
        kwt_ffn_clock_gate gate(.clk(clk),.enable(shift_en),.test_enable(clock_test_enable||!rst_n),.gated_clk(shift_clk));
    end else assign shift_clk=clk;endgenerate
    kwt_encoder_sram16x128 shift_memory(.clk(shift_clk),.en(shift_en),.we(shift_we),.addr(shift_addr),.wdata(shift_wdata),.rdata(shift_rdata));
    wire row_cache_ready=input_complete;
    wire input_loading=loading&&(load_kind==0);
    wire ap_input_read=((state==A_REQ)&&row_cache_ready)||prefetch;
    wire [31:0] ap_input_rdata;
    reg [31:0] jp_input_return;
    generate for(genvar ap_row=0;ap_row<2;ap_row=ap_row+1)begin: ap_input_rows
        wire write_enable=input_loading&&(load_addr[6]==1'(ap_row));
        wire read_enable=ap_input_read&&((ap_row==0)||(row<98));
        wire memory_enable=write_enable||read_enable;
        wire [6:0] memory_addr=write_enable?{load_addr[7],load_addr[5:0]}:{row[1],request_inner};
        wire lp_return_clock;
        kwt_ffn_clock_gate return_gate(.clk(clk),.enable(read_enable),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(lp_return_clock));
        always_latch if(lp_return_clock)jp_input_return[ap_row*16+:16]<=ap_input_rdata[ap_row*16+:16];
        wire memory_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(memory_enable),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(memory_enable),.we(write_enable),
            .addr(memory_addr),.wdata(load_data),.rdata(ap_input_rdata[ap_row*16+:16]));
    end endgenerate
    reg [15:0] jp_shift_return;
    always_latch if(!clk)jp_shift_return=shift_rdata;
    function automatic [15:0] lit_code(input [15:0] value);
        begin lit_code={value[15],value[14:0]^{15{value[15]}}};end
    endfunction
    wire [31:0] lit_input_values;
    wire [127:0] lit_weight_values;
    generate for(genvar lit_input=0;lit_input<2;lit_input=lit_input+1)begin: lit_input_decode
        assign lit_input_values[lit_input*16+:16]=jp_input_return[lit_input*16+:16];
    end endgenerate
    generate for(genvar lit_column=0;lit_column<8;lit_column=lit_column+1)begin: lit_weight_decode
        wire [15:0] selected=pm_rdata[(int'(tile[0])*8+lit_column)*16+:16];
        assign lit_weight_values[lit_column*16+:16]=selected;
    end endgenerate
    wire [3:0] jp_quant_lane={emit_row,lane};
    wire [35:0] quant_bits=accumulator[jp_quant_lane];
    wire signed [63:0] quant_value={{28{quant_bits[35]}},quant_bits};
    wire signed [15:0] result_word;
    kwt_ffn_requantize quantizer(.value(quant_value),.shift(shifts[jp_quant_lane]),.result(result_word));
    wire [35:0] tp_high_quant_bits=accumulator[{1'b0,jp_quant_lane}+5'd1];
    wire signed [63:0] tp_high_quant_value={{28{tp_high_quant_bits[35]}},tp_high_quant_bits};
    wire signed [15:0] tp_result_high;
    kwt_ffn_requantize tp_high_quantizer(.value(tp_high_quant_value),
        .shift(shifts[{1'b0,jp_quant_lane}+5'd1]),.result(tp_result_high));
    kwt_joint_output_queue output_queue(.clk(clk),.rst_n(rst_n),.clock_test_enable(clock_test_enable),
        .restart(layer_start_valid&&layer_start_ready),.push_valid(emission),.push_row1(emit_row),
        .push_low(result_word),.push_high(tp_result_high),.push_ready(jp_quant_ready),.item(item),
        .out_ready(out_ready),.out_pair_ready(out_pair_ready),.out_valid(out_valid),.out_pair_valid(out_pair_valid),
        .out_data(out_data),.out_high(out_high),.pop_count(pop_count),.fifo_count(fifo_count));
    wire [23:0] lit_booth_code[0:2-1];
    generate for(genvar lit_source=0;lit_source<2;lit_source=lit_source+1)begin: lit_shared_booth
        wire [16:0] extended={lit_input_values[lit_source*16+:16],1'b0};
        for(genvar digit=0;digit<8;digit=digit+1)begin: digits
            assign lit_booth_code[lit_source][digit*3+:3]=extended[digit*2+:3];
        end
    end endgenerate
    generate for(genvar jp_lane=0;jp_lane<16;jp_lane=jp_lane+1)begin: jp_mac_lanes
        localparam integer jp_row=jp_lane/8;
        localparam integer jp_column=jp_lane%8;
        wire seed_update=(bias_capture&&(chunk==2'(jp_column/2))&&((jp_row==0)||(row<98)))||
            (ap_er_reseed&&(emit_row==1'(jp_row))&&(lane[2:1]==2'(jp_column/2))&&
             ((jp_row==0)||jp_next_row1));
        wire mac_update=(state==B_MAC)&&((jp_row==0)||(row<98));
        wire quant_commit=jp_quant_commit&&(emit_row==1'(jp_row))&&(lane[2:1]==2'(jp_column/2));
        assign jp_seed_mask[jp_lane]=seed_update;
        assign jp_mac_mask[jp_lane]=mac_update;
        assign jp_quant_mask[jp_lane]=quant_commit;
        wire signed [16:0] activation=$signed(lit_input_values[jp_row*16+:16]);
        wire signed [15:0] weight_value=$signed(lit_weight_values[jp_column*16+:16]);
        wire accumulator_clk,shift_register_clk;
        if(jp_column%2==0)begin: pair_gate
            kwt_ffn_clock_gate acc_gate(.clk(clk),.enable(mac_update||seed_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(accumulator_clk));
            kwt_ffn_clock_gate shift_gate(.clk(clk),.enable(seed_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(shift_register_clk));
        end else begin
            assign accumulator_clk=jp_mac_lanes[jp_lane-1].accumulator_clk;
            assign shift_register_clk=jp_mac_lanes[jp_lane-1].shift_register_clk;
        end
        wire signed [35:0] lit_multiplicand=36'($signed(weight_value));
        wire [35:0] lit_terms[0:7];
        for(genvar lit_digit=0;lit_digit<8;lit_digit=lit_digit+1)begin: booth_partial_products
            reg signed [35:0] unshifted;
            always @*begin
                case(lit_booth_code[jp_row][lit_digit*3+:3])
                    3'b001,3'b010:unshifted=lit_multiplicand;
                    3'b011:unshifted=lit_multiplicand<<<1;
                    3'b100:unshifted=-(lit_multiplicand<<<1);
                    3'b101,3'b110:unshifted=-lit_multiplicand;
                    default:unshifted=0;
                endcase
            end
            assign lit_terms[lit_digit]=unshifted<<<(lit_digit*2);
        end
        wire [35:0] lit_csa_0_0_s=lit_terms[0]^lit_terms[1]^lit_terms[2];
        wire [35:0] lit_csa_0_0_c=((lit_terms[0]&lit_terms[1])|(lit_terms[0]&lit_terms[2])|(lit_terms[1]&lit_terms[2]))<<1;
        wire [35:0] lit_csa_0_1_s=lit_terms[3]^lit_terms[4]^lit_terms[5];
        wire [35:0] lit_csa_0_1_c=((lit_terms[3]&lit_terms[4])|(lit_terms[3]&lit_terms[5])|(lit_terms[4]&lit_terms[5]))<<1;
        wire [35:0] lit_csa_0_2_s=lit_terms[6]^lit_terms[7]^accumulator[jp_lane];
        wire [35:0] lit_csa_0_2_c=((lit_terms[6]&lit_terms[7])|(lit_terms[6]&accumulator[jp_lane])|(lit_terms[7]&accumulator[jp_lane]))<<1;
        wire [35:0] lit_csa_1_0_s=lit_csa_0_0_s^lit_csa_0_0_c^lit_csa_0_1_s;
        wire [35:0] lit_csa_1_0_c=((lit_csa_0_0_s&lit_csa_0_0_c)|(lit_csa_0_0_s&lit_csa_0_1_s)|(lit_csa_0_0_c&lit_csa_0_1_s))<<1;
        wire [35:0] lit_csa_1_1_s=lit_csa_0_1_c^lit_csa_0_2_s^lit_csa_0_2_c;
        wire [35:0] lit_csa_1_1_c=((lit_csa_0_1_c&lit_csa_0_2_s)|(lit_csa_0_1_c&lit_csa_0_2_c)|(lit_csa_0_2_s&lit_csa_0_2_c))<<1;
        wire [35:0] lit_csa_2_0_s=lit_csa_1_0_s^lit_csa_1_0_c^lit_csa_1_1_s;
        wire [35:0] lit_csa_2_0_c=((lit_csa_1_0_s&lit_csa_1_0_c)|(lit_csa_1_0_s&lit_csa_1_1_s)|(lit_csa_1_0_c&lit_csa_1_1_s))<<1;
        wire [35:0] lit_csa_3_0_s=lit_csa_2_0_s^lit_csa_2_0_c^lit_csa_1_1_c;
        wire [35:0] lit_csa_3_0_c=((lit_csa_2_0_s&lit_csa_2_0_c)|(lit_csa_2_0_s&lit_csa_1_1_c)|(lit_csa_2_0_c&lit_csa_1_1_c))<<1;
        wire [35:0] lit_mac_next=lit_csa_3_0_s+lit_csa_3_0_c;
        always @(posedge accumulator_clk or negedge rst_n)begin
            if(!rst_n)accumulator[jp_lane]<=0;
            else if(seed_update)accumulator[jp_lane]<=36'($signed(bias_pair[(jp_column%2)*64+:64]));
            else if(mac_update)accumulator[jp_lane]<=lit_mac_next;
        end
        always @(posedge shift_register_clk or negedge rst_n)begin
            if(!rst_n)shifts[jp_lane]<=0;
            else if(seed_update)shifts[jp_lane]<=$signed(jp_shift_return[(jp_column%2)*8+:8]);
        end
    end endgenerate
    assign start_ready=state==IDLE;
    assign layer_request=state==WAIT_LAYER;
    assign layer_start_ready=layer_request&&(parameter_count==17408)&&(shift_count==128);
    assign load_capacity_ready=(((state==WAIT_LAYER)&&((load_kind==1)||(load_kind==5)))||
         ((load_kind==0)&&((!STREAM_INPUT&&(state==IDLE))||(STREAM_INPUT&&(state>=3)&&(input_count<6336)&&
             ({1'b0,input_count}<((14'({1'b0,row})+14'd4)<<6))&&!ap_input_read))));
    assign load_ready=!start_valid&&!layer_start_valid&&load_capacity_ready;
    assign busy=state!=IDLE;
    assign layer_index=0;
    assign out_index=item;
    assign trace_valid=pop_count!=0;
    assign trace_pair_valid=pop_count==2;
    assign trace_layer=0;assign trace_stage=9;
    assign trace_index=item;
    assign trace_data={{48{out_data[15]}},out_data};
    assign trace_high={{48{out_high[15]}},out_high};
    function automatic [12:0] ld_parameter_address(input [12:0] packed_address);
        begin ld_parameter_address={3'b000,ap_gray6(packed_address[5:0]),packed_address[9:6]};end
    endfunction
    always @* begin
        sp_en=0;sp_we=0;sp_addr=0;sp_wdata=0;pm_en=0;pm_we=0;pm_addr=0;pm_wdata=0;
        bias_en=0;bias_we=0;bias_addr=0;bias_wdata=0;shift_en=0;shift_we=0;shift_addr=0;shift_wdata=0;
        address=0;bank_index=0;offset=0;
        if(state==CLEAR&&!ZERO_CLEAR) begin
            if(!SMALL_INPUT&&clear_index<1024) begin sp_en='1;sp_we='1;end
            if(clear_index<16384/LANES) begin pm_en='1;pm_we='1;end
            if(clear_index<128) begin bias_en='1;bias_we='1;shift_en=1;shift_we=1;end
            for(b=0;b<8;b=b+1) sp_addr[b*13+:13]=clear_index[12:0];
            for(b=0;b<LANES;b=b+1) pm_addr[b*13+:13]=clear_index[12:0];
            for(b=0;b<BIAS_BANKS;b=b+1) bias_addr[b*7+:7]=clear_index[6:0];
            shift_addr=clear_index[6:0];
        end
        if(loading) for(k=0;k<2;k=k+1) if(k<int'(load_count)) begin
            address=int'(load_addr)+k;
            if(load_kind==0&&!SMALL_INPUT) begin
                bank_index=address%8;sp_en[bank_index]=1;sp_we[bank_index]=1;
                sp_addr[bank_index*13+:13]=13'(address/8);sp_wdata[bank_index*16+:16]=k==0?load_data:load_high;
            end
            if(load_kind==1) begin
                if(address<16384) begin
                    bank_index=address%LANES;pm_en[bank_index]=1;pm_we[bank_index]=1;
                    pm_addr[bank_index*13+:13]=ld_parameter_address(13'(address/LANES));pm_wdata[bank_index*16+:16]=k==0?load_data:load_high;
                end else begin
                    address=address-16384;
                    if(!BIAS32||address%4<2) begin
                        if(BIAS32) address=(address/4)*2+address%4;
                        bank_index=address%BIAS_BANKS;bias_en[bank_index]=1;bias_we[bank_index]=1;
                        bias_addr[bank_index*7+:7]=7'(address/BIAS_BANKS);bias_wdata[bank_index*16+:16]=k==0?load_data:load_high;
                    end
                end
            end
            if(load_kind==5) begin shift_en=1;shift_we=1;shift_addr=load_addr[6:0];shift_wdata=load_data;end
        end
        if(!USE_ROW_CACHE&&((state==A_REQ)||prefetch||(((state==B_MAC)||(state==ROW1_MAC))&&mac_group<int'(block_rows)-1))) begin
            address=(row+(((state==B_MAC)||(state==ROW1_MAC))&&!prefetch?mac_group+1:0))*64+int'(request_inner);
            bank_index=address%8;sp_en[bank_index]=1;sp_addr[bank_index*13+:13]=13'(address/8);
        end
        if((state==A_REQ&&row_cache_ready)||prefetch) begin
            for(b=0;b<LANES;b=b+1)if((b/8)==int'(tile[0]))begin pm_en[b]=1;pm_addr[b*13+:13]=ap_weight_read_address;end
        end
        if(bias_request) begin
            bias_en='1;
            for(b=0;b<BIAS_BANKS;b=b+1) bias_addr[b*7+:7]=7'(BIAS32?(int'(ap_bias_tile)*4+int'(ap_bias_pair)):(int'(bias_address)/BIAS_BANKS));
            shift_en=1;shift_addr=7'(int'(ap_bias_tile)*4+int'(ap_bias_pair));
        end
    end
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            state<=CLEAR;clear_index<=0;input_count<=0;parameter_count<=0;shift_count<=0;
            row<=0;tile<=0;lane<=0;inner<=0;chunk<=0;item<=0;emit_row<=0;
            done<=0;error<=0;layer_done<=0;
        end else begin
            done<=0;layer_done<=0;
            if(loading)case(load_kind)
                0:if(load_addr==16'(input_count)&&input_count<6336)input_count<=input_count+13'(load_count);else error<=1;
                1:if(load_addr==16'(parameter_count)&&parameter_count<17408)parameter_count<=parameter_count+15'(load_count);else error<=1;
                5:if(load_addr==16'(shift_count)&&shift_count<128)shift_count<=shift_count+1'b1;else error<=1;
            endcase
            case(state)
                CLEAR:begin clear_index<=0;state<=IDLE;end
                IDLE:if(start_valid)begin
                    error<=0;if(!linear_mode)begin error<=1;done<=1;end
                    else begin parameter_count<=0;shift_count<=0;state<=WAIT_LAYER;end
                end
                WAIT_LAYER:if(layer_start_valid&&layer_start_ready)begin
                    row<=0;tile<=0;item<=0;lane<=0;inner<=0;emit_row<=0;state<=WAIT_INPUT;
                end
                WAIT_INPUT:if(input_complete)state<=MAC_INIT;
                MAC_INIT:begin chunk<=0;if(ap_er_next_seed_ready)begin inner<=0;state<=A_REQ;end else state<=BIAS_REQ;end
                BIAS_REQ:state<=BIAS_CAP;
                BIAS_CAP:if(chunk==3)begin inner<=0;state<=A_REQ;end else begin chunk<=chunk+1'b1;state<=BIAS_REQ;end
                A_REQ:if(input_complete)state<=B_MAC;
                B_MAC:if(inner==63)begin lane<=0;emit_row<=0;state<=EMIT;end else inner<=inner+1'b1;
                EMIT:if(jp_quant_commit)begin
                    if(!jp_last_emit_row)emit_row<=1;
                    else begin
                        emit_row<=0;
                        if(lane<6)lane<=lane+3'd2;
                        else if(tile<31)begin tile<=tile+1'b1;state<=MAC_INIT;end
                        else state<=ADVANCE;
                    end
                end
                ADVANCE:if(row==98)begin layer_done<=1;state<=DRAIN;end
                    else begin row<=row+7'd2;tile<=0;lane<=0;state<=WAIT_INPUT;end
                DRAIN:begin end
                default:begin error<=1;done<=1;state<=CLEAR;end
            endcase
            if(pop_count!=0)begin
                if({1'b0,item}+16'(pop_count)==16'd25344)begin
                    done<=1;input_count<=0;parameter_count<=0;shift_count<=0;state<=CLEAR;clear_index<=0;
                end else item<=item+15'(pop_count);
            end
        end
    end
endmodule
