// FFN implementation for independent storage, transport and scheduling ablations.
module kwt_encoder #(
    parameter integer SPLIT_BIAS=1, FAST_PAIR=1, OVERLAP=0, LANES=16, CLOCK_GATING=1
)(
    input wire clk,rst_n,clock_test_enable,linear_mode,load_valid,load_pair,
    output wire load_ready,
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
    output wire signed [63:0] trace_data
);
    localparam integer TILES=256/LANES, GROUPS=2;
    localparam [3:0] CLEAR=0,IDLE=1,WAIT_LAYER=2,MAC_INIT=3,
        BIAS_REQ=4,BIAS_CAP=5,A_REQ=6,B_MAC=7,EMIT=8,DRAIN=12;
    localparam [4:0] ROW1_MAC=9,EMIT_STASH=10,STASH_REQ=11,STASH_OUT=13;
    reg [4:0] state;
    reg [13:0] clear_index;
    reg [12:0] input_count;
    reg [14:0] parameter_count;
    reg [7:0] shift_count;
    integer row,tile,inner,lane,chunk,item,b,i,k;
    reg signed [35:0] accumulator[0:GROUPS*LANES-1];
    reg signed [7:0] shifts[0:GROUPS*LANES-1];
    reg [15:0] fifo[0:15];
    reg [3:0] fifo_write,fifo_read;
    reg [4:0] fifo_count;
    wire pair_pop=FAST_PAIR&&out_pair_ready&&(fifo_count>=2);
    wire single_pop=out_ready&&(fifo_count!=0)&&!pair_pop;
    wire [1:0] pop_count=pair_pop?2:(single_pop?1:0);
    reg compute_group,emit_group;
    reg [1:0] ready_group;
    reg [1:0] complete_group;
    reg [6:0] group_row[0:1];
    reg [5:0] group_tile[0:1];
    reg [3:0] prep_state;
    integer prep_chunk;
    reg prep_group;
    reg [6:0] prep_row;
    reg [5:0] prep_tile;
    reg producer_finished;
    wire emission=(state==EMIT)||(state==STASH_OUT);
    wire fifo_push=emission&&((fifo_count<16)||(pop_count!=0));
    wire [35:0] quant_bits=accumulator[((state==EMIT_STASH)?LANES:0)+lane];
    wire signed [63:0] quant_value={{28{quant_bits[35]}},quant_bits};
    wire signed [15:0] result_word;
    reg [7:0] stash_pointer;
    wire [31:0] stash_rdata;
    wire [15:0] fifo_word=(state==STASH_OUT)?stash_rdata[stash_pointer[0]*16+:16]:result_word;
    wire stash_write=state==EMIT_STASH;
    wire stash_read=(state==STASH_REQ)||((state==STASH_OUT)&&fifo_push&&stash_pointer<255);
    wire [7:0] stash_address=(state==STASH_OUT)?stash_pointer+1'b1:stash_pointer;
    wire [7:0] stash_column=8'(tile*LANES+lane);

    kwt_ffn_requantize quantizer(.value(quant_value),
        .shift(shifts[((state==EMIT_STASH)?LANES:0)+lane]),.result(result_word));
    wire loading=load_valid&&load_ready;
    wire [1:0] load_count=(FAST_PAIR&&load_pair&&load_kind!=5)?2:1;
    wire prefetch=((state==ROW1_MAC)||((state==B_MAC)&&row==98))&&(inner<63);
    wire [5:0] request_inner=6'(inner+int'(prefetch));
    wire bias_request=state==BIAS_REQ;
    wire bias_capture=state==BIAS_CAP;
    wire [5:0] bias_tile=6'(tile);
    wire [3:0] bias_chunk=4'(chunk);
    wire [15:0] weight_address=16'(int'(request_inner)*256+tile*LANES);
    wire [15:0] bias_address=16'(int'(bias_tile)*LANES*4+int'(bias_chunk)*8);
    reg [7:0] sp_en,sp_we;
    reg [103:0] sp_addr;
    reg [127:0] sp_wdata;
    wire [127:0] sp_rdata;
    reg [LANES-1:0] pm_en,pm_we,bias_en,bias_we;
    reg [13*LANES-1:0] pm_addr;
    reg [7*LANES-1:0] bias_addr;
    reg [16*LANES-1:0] pm_wdata,bias_wdata;
    wire [16*LANES-1:0] pm_rdata,bias_rdata;
    reg shift_en,shift_we;
    reg [6:0] shift_addr;
    reg [15:0] shift_wdata;
    wire [15:0] shift_rdata;
    wire row_cache_ready=1'b1;
    wire [6:0] read_row=7'(row);
    wire [12:0] input_address=13'((row+int'(state==ROW1_MAC))*64+inner);
    wire signed [16:0] mac_a=$signed({sp_rdata[input_address[2:0]*16+15],sp_rdata[input_address[2:0]*16+:16]});
    kwt_encoder_memory #(.BANK_LEAVES(1)) scratch(
        .clk(clk),.en(sp_en),.we(sp_we),.addr(sp_addr),.wdata(sp_wdata),.rdata(sp_rdata));
    generate for(genvar bank=0;bank<LANES;bank=bank+1) begin: parameter_banks
        wire weight_clk,bias_clk;
        if(CLOCK_GATING) begin: gated
            kwt_ffn_clock_gate weight_gate(.clk(clk),.enable(pm_en[bank]),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(weight_clk));
            kwt_ffn_clock_gate bias_gate(.clk(clk),.enable(bias_en[bank]),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(bias_clk));
        end else begin: ungated
            assign weight_clk=clk;
            assign bias_clk=clk;
        end
        kwt_spmem16 #(.ADDR_WIDTH(13),.BANKS(SPLIT_BIAS?(16/LANES):3)) weights(
            .clk(weight_clk),.en(pm_en[bank]),.we(pm_we[bank]),.addr(pm_addr[bank*13+:13]),
            .wdata(pm_wdata[bank*16+:16]),.rdata(pm_rdata[bank*16+:16]));
        if(SPLIT_BIAS) begin: separate_bias
            kwt_encoder_sram16x128 memory(.clk(bias_clk),.en(bias_en[bank]),.we(bias_we[bank]),
                .addr(bias_addr[bank*7+:7]),.wdata(bias_wdata[bank*16+:16]),.rdata(bias_rdata[bank*16+:16]));
        end else begin: integrated_bias
            assign bias_rdata[bank*16+:16]=pm_rdata[bank*16+:16];
        end
    end endgenerate
    wire shift_clk;
    generate if(CLOCK_GATING) begin: gate_shift
        kwt_ffn_clock_gate gate(.clk(clk),.enable(shift_en),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(shift_clk));
    end else assign shift_clk=clk;
    endgenerate
    kwt_encoder_sram16x128 shift_memory(.clk(shift_clk),.en(shift_en),.we(shift_we),
        .addr(shift_addr),.wdata(shift_wdata),.rdata(shift_rdata));
    assign start_ready=state==IDLE;
    assign layer_request=state==WAIT_LAYER;
    assign layer_start_ready=layer_request&&parameter_count==17408&&shift_count==128;
    assign load_ready=((state==IDLE&&load_kind==0)||(state==WAIT_LAYER&&(load_kind==1||load_kind==5)))&&!start_valid&&!layer_start_valid;
    assign busy=state!=IDLE;
    assign layer_index=0;
    assign out_valid=fifo_count!=0;
    assign out_pair_valid=fifo_count>=2;
    assign out_data=$signed(fifo[fifo_read]);
    wire [3:0] next_read=fifo_read+4'd1;
    assign out_high=$signed(fifo[next_read]);
    assign out_index=15'(item);
    assign trace_valid=fifo_push;
    assign trace_layer=0;
    assign trace_stage=9;
    assign trace_index=(state==STASH_OUT)?15'((row+1)*256+int'(stash_pointer)):15'(row*256+tile*LANES+lane);
    assign trace_data={{48{fifo_word[15]}},fifo_word};
    integer address,bank_index;
    always @* begin
        sp_en=0;sp_we=0;sp_addr=0;sp_wdata=0;
        pm_en=0;pm_we=0;pm_addr=0;pm_wdata=0;
        bias_en=0;bias_we=0;bias_addr=0;bias_wdata=0;
        shift_en=0;shift_we=0;shift_addr=0;shift_wdata=0;
        address=0;bank_index=0;
        if(state==CLEAR) begin
            if(clear_index<1024) begin sp_en='1;sp_we='1;end
            if(clear_index<(SPLIT_BIAS?(16384/LANES):3072)) begin pm_en='1;pm_we='1;end
            if(SPLIT_BIAS&&clear_index<128) begin bias_en='1;bias_we='1;end
            for(b=0;b<8;b=b+1) sp_addr[b*13+:13]=clear_index[12:0];
            for(b=0;b<LANES;b=b+1) begin pm_addr[b*13+:13]=clear_index[12:0];bias_addr[b*7+:7]=clear_index[6:0];end
            if(clear_index<128) begin shift_en=1;shift_we=1;shift_addr=clear_index[6:0];end
        end
        if(loading) for(k=0;k<2;k=k+1) if(k<int'(load_count)) begin
            address=int'(load_addr)+k;
            if(load_kind==0&&load_addr==16'(input_count)&&input_count<6336) begin
                bank_index=address%8;sp_en[bank_index]=1;sp_we[bank_index]=1;
                sp_addr[bank_index*13+:13]=13'(address/8);sp_wdata[bank_index*16+:16]=k==0?load_data:load_high;
            end
            if(load_kind==1&&load_addr==16'(parameter_count)&&parameter_count<17408) begin
                if(SPLIT_BIAS&&address>=16384) begin
                    address=address-16384;bank_index=address%LANES;
                    bias_en[bank_index]=1;bias_we[bank_index]=1;
                    bias_addr[bank_index*7+:7]=7'(address/LANES);bias_wdata[bank_index*16+:16]=k==0?load_data:load_high;
                end else begin
                    bank_index=address%LANES;pm_en[bank_index]=1;pm_we[bank_index]=1;
                    pm_addr[bank_index*13+:13]=13'(address/LANES);pm_wdata[bank_index*16+:16]=k==0?load_data:load_high;
                end
            end
            if(load_kind==5&&load_addr==16'(shift_count)&&shift_count<128) begin
                shift_en=1;shift_we=1;shift_addr=load_addr[6:0];shift_wdata=load_data;
            end
        end
        if((state==A_REQ)||prefetch||((state==B_MAC)&&row<98)) begin
            address=(row+int'((state==B_MAC)&&row<98))*64+int'(request_inner);bank_index=address%8;
            sp_en[bank_index]=1;sp_addr[bank_index*13+:13]=13'(address/8);
        end
        if((state==A_REQ&&row_cache_ready)||prefetch) begin
            pm_en='1;for(b=0;b<LANES;b=b+1) pm_addr[b*13+:13]=13'(int'(weight_address)/LANES);
        end
        if(bias_request) begin
            if(SPLIT_BIAS) begin
                bias_en='1;for(b=0;b<LANES;b=b+1) bias_addr[b*7+:7]=7'(int'(bias_address)/LANES);
            end else begin
                pm_en='1;for(b=0;b<LANES;b=b+1) pm_addr[b*13+:13]=13'((16384+int'(bias_address))/LANES);
            end
            shift_en=1;shift_addr=7'(int'(bias_tile)*(LANES/2)+int'(bias_chunk));
        end
    end
    generate for(genvar stash_bank=0;stash_bank<2;stash_bank=stash_bank+1) begin: row_stash
        wire clearing=(state==CLEAR)&&(clear_index<128);
        wire writing=stash_write&&(stash_column[0]==stash_bank);
        wire reading=stash_read&&(stash_address[0]==stash_bank);
        wire memory_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(clearing||writing||reading),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(clearing||writing||reading),
            .we(clearing||writing),.addr(clearing?clear_index[6:0]:(writing?stash_column[7:1]:stash_address[7:1])),
            .wdata(clearing?16'd0:result_word),.rdata(stash_rdata[stash_bank*16+:16]));
    end endgenerate
    wire datapath_enable=bias_capture||(state==B_MAC)||(state==ROW1_MAC)||fifo_push||stash_write;
    wire datapath_clk;
    generate if(CLOCK_GATING) begin: row_datapath_gate
        kwt_ffn_clock_gate gate(.clk(clk),.enable(datapath_enable),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(datapath_clk));
    end else assign datapath_clk=clk;
    endgenerate
    generate for(genvar acc_group=0;acc_group<2;acc_group=acc_group+1) begin: row_accumulators
        wire mac_update=(acc_group==0)?(state==B_MAC):(state==ROW1_MAC);
        wire bias_update=bias_capture&&((acc_group==0)||(row<98));
        wire register_clk;
        if(0) begin: fine_gate
            kwt_ffn_clock_gate gate(.clk(clk),.enable(bias_update||mac_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(register_clk));
        end else assign register_clk=datapath_clk;
        for(genvar acc_lane=0;acc_lane<LANES;acc_lane=acc_lane+1) begin: lane_registers
            always @(posedge register_clk or negedge rst_n) begin
                if(!rst_n) begin accumulator[acc_group*LANES+acc_lane]<=0;shifts[acc_group*LANES+acc_lane]<=0;end
                else begin
                    if(bias_update&&int'(bias_chunk)==acc_lane/2) begin
                        accumulator[acc_group*LANES+acc_lane]<=36'($signed(bias_rdata[(int'(bias_chunk)*8%LANES)*16+(acc_lane%2)*64+:64]));
                        shifts[acc_group*LANES+acc_lane]<=$signed(shift_rdata[(acc_lane%2)*8+:8]);
                    end
                    if(mac_update) accumulator[acc_group*LANES+acc_lane]<=
                        accumulator[acc_group*LANES+acc_lane]+36'(mac_a*$signed(pm_rdata[acc_lane*16+:16]));
                end
            end
        end
    end endgenerate
    wire fifo_clk;
    generate if(0) begin: row_fifo_gate
        kwt_ffn_clock_gate gate(.clk(clk),.enable(fifo_push),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(fifo_clk));
    end else assign fifo_clk=datapath_clk;
    endgenerate
    always @(posedge fifo_clk) if(fifo_push) fifo[fifo_write]<=fifo_word;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=CLEAR;clear_index<=0;input_count<=0;parameter_count<=0;shift_count<=0;
            row<=0;tile<=0;inner<=0;lane<=0;chunk<=0;item<=0;stash_pointer<=0;
            done<=0;error<=0;layer_done<=0;fifo_write<=0;fifo_read<=0;fifo_count<=0;
        end else begin
            done<=0;layer_done<=0;
            if(fifo_push) fifo_write<=fifo_write+1'b1;
            if(pop_count!=0) begin
                fifo_read<=fifo_read+4'(pop_count);
                if(item+int'(pop_count)==25344) begin
                    done<=1;input_count<=0;parameter_count<=0;shift_count<=0;clear_index<=0;state<=CLEAR;
                end else item<=item+int'(pop_count);
            end
            fifo_count<=fifo_count+5'(fifo_push)-5'(pop_count);
            if(loading) case(load_kind)
                0: if(load_addr==16'(input_count)&&input_count<6336) input_count<=input_count+13'(load_count);else error<=1;
                1: if(load_addr==16'(parameter_count)&&parameter_count<17408) parameter_count<=parameter_count+15'(load_count);else error<=1;
                5: if(load_addr==16'(shift_count)&&shift_count<128) shift_count<=shift_count+1'b1;else error<=1;
            endcase
            case(state)
                CLEAR: if(clear_index==1023) begin clear_index<=0;state<=IDLE;end else clear_index<=clear_index+1'b1;
                IDLE: if(start_valid) begin
                    error<=0;
                    if(input_count!=6336||!linear_mode) begin error<=1;done<=1;end
                    else begin parameter_count<=0;shift_count<=0;state<=WAIT_LAYER;end
                end
                WAIT_LAYER: if(layer_start_valid&&layer_start_ready) begin
                    row<=0;tile<=0;item<=0;lane<=0;inner<=0;state<=MAC_INIT;
                end
                MAC_INIT: begin chunk<=0;state<=BIAS_REQ;end
                BIAS_REQ: state<=BIAS_CAP;
                BIAS_CAP: if(chunk==LANES/2-1) begin inner<=0;state<=A_REQ;end
                          else begin chunk<=chunk+1;state<=BIAS_REQ;end
                A_REQ: if(row_cache_ready) state<=B_MAC;
                B_MAC: if(row<98) state<=ROW1_MAC;
                       else if(inner==63) begin lane<=0;state<=EMIT;end
                       else inner<=inner+1;
                ROW1_MAC: if(inner==63) begin lane<=0;state<=EMIT;end
                          else begin inner<=inner+1;state<=B_MAC;end
                EMIT: if(fifo_push) begin
                    if(lane<LANES-1) lane<=lane+1;
                    else if(row<98) begin lane<=0;state<=EMIT_STASH;end
                    else if(tile<TILES-1) begin tile<=tile+1;state<=MAC_INIT;end
                    else begin layer_done<=1;state<=DRAIN;end
                end
                EMIT_STASH: if(lane<LANES-1) lane<=lane+1;
                            else if(tile<TILES-1) begin tile<=tile+1;state<=MAC_INIT;end
                            else begin stash_pointer<=0;state<=STASH_REQ;end
                STASH_REQ: state<=STASH_OUT;
                STASH_OUT: if(fifo_push) begin
                    if(stash_pointer<255) stash_pointer<=stash_pointer+1'b1;
                    else begin row<=row+2;tile<=0;lane<=0;state<=MAC_INIT;end
                end
                DRAIN: begin end
                default: begin error<=1;done<=1;state<=CLEAR;end
            endcase
        end
    end
endmodule
