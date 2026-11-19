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
    localparam integer ROW_GROUP=1, INPUT_SLOTS=2, STREAM_INPUT=1,
        SMALL_INPUT=1, USE_ROW_CACHE=1, ZERO_CLEAR=0, BIAS32=1, BIAS_BANKS=4;
    localparam integer TILES=256/LANES, GROUPS=ROW_GROUP;
    localparam [4:0] CLEAR=0,IDLE=1,WAIT_LAYER=2,MAC_INIT=3,BIAS_REQ=4,BIAS_CAP=5,
        A_REQ=6,B_MAC=7,EMIT=8,ROW1_MAC=9,EMIT_STASH=10,STASH_REQ=11,DRAIN=12,STASH_OUT=13,ADVANCE=14,WAIT_INPUT=15;
    reg [4:0] state;
    reg [13:0] clear_index;
    reg [12:0] input_count;
    reg [14:0] parameter_count;
    reg [7:0] shift_count;
    integer row,tile,inner,lane,chunk,item,mac_group,emit_group,stash_pointer;
    integer address,bank_index,b,k,offset;
    wire [2:0] block_rows=3'((99-row<ROW_GROUP)?99-row:ROW_GROUP);
    wire loading=load_valid&&load_ready;
    wire [1:0] load_count=(FAST_PAIR&&load_pair&&load_kind!=5)?2:1;
    wire input_complete=int'(input_count)>=(row+int'(block_rows))*64;
    reg signed [35:0] accumulator[0:ROW_GROUP*LANES-1];
    reg signed [7:0] shifts[0:ROW_GROUP*LANES-1];
    reg [15:0] fifo[0:15];
    reg [3:0] fifo_write,fifo_read;
    reg [4:0] fifo_count;
    wire pair_pop=FAST_PAIR&&out_pair_ready&&(fifo_count>=2);
    wire single_pop=out_ready&&(fifo_count!=0)&&!pair_pop;
    wire [1:0] pop_count=pair_pop?2:(single_pop?1:0);
    wire emission=(state==EMIT)||(state==STASH_OUT);
    wire fifo_push=emission&&((fifo_count<16)||(pop_count!=0));
    wire bias_request=state==BIAS_REQ,bias_capture=state==BIAS_CAP;
    wire prefetch=((state==B_MAC)||(state==ROW1_MAC))&&(mac_group==int'(block_rows)-1)&&(inner<63);
    wire [5:0] request_inner=6'(inner+int'(prefetch));
    wire [15:0] weight_address=16'(int'(request_inner)*256+tile*LANES);
    wire [15:0] bias_address=16'(tile*LANES*4+chunk*8);
    wire [5:0] bias_tile=6'(tile);
    wire [3:0] bias_chunk=4'(chunk);
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
    reg signed [15:0] row_cache[0:INPUT_SLOTS*ROW_GROUP*64-1];
    reg row_cache_valid,row_cache_pending;
    integer row_cache_request,row_cache_chunk;
    wire row_cache_ready=USE_ROW_CACHE?(SMALL_INPUT?input_complete:row_cache_valid):1'b1;
    wire row_cache_issue=USE_ROW_CACHE&&!SMALL_INPUT&&(state==A_REQ)&&!row_cache_valid&&(row_cache_request<int'(block_rows)*8);
    wire input_loading=loading&&(load_kind==0)&&SMALL_INPUT;
    wire row_cache_clk;
    kwt_ffn_clock_gate row_input_gate(.clk(clk),.enable(input_loading||row_cache_pending),
        .test_enable(clock_test_enable||!rst_n),.gated_clk(row_cache_clk));
    integer cache_bank,cache_word;
    always @(posedge row_cache_clk) begin
        if(input_loading) for(cache_word=0;cache_word<2;cache_word=cache_word+1)
            if(cache_word<int'(load_count)) row_cache[(int'(load_addr)+cache_word)%(INPUT_SLOTS*ROW_GROUP*64)]<=cache_word==0?load_data:load_high;
        if(row_cache_pending) for(cache_bank=0;cache_bank<8;cache_bank=cache_bank+1)
            row_cache[row_cache_chunk*8+cache_bank]<=sp_rdata[cache_bank*16+:16];
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin row_cache_valid<=0;row_cache_pending<=0;row_cache_request<=0;row_cache_chunk<=0;end
        else if(state==CLEAR||state==ADVANCE) begin row_cache_valid<=0;row_cache_pending<=0;row_cache_request<=0;end
        else begin
            row_cache_pending<=row_cache_issue;
            if(!USE_ROW_CACHE&&((state==A_REQ)||prefetch||(((state==B_MAC)||(state==ROW1_MAC))&&mac_group<int'(block_rows)-1))) begin
            address=(row+(((state==B_MAC)||(state==ROW1_MAC))&&!prefetch?mac_group+1:0))*64+int'(request_inner);
            bank_index=address%8;sp_en[bank_index]=1;sp_addr[bank_index*13+:13]=13'(address/8);
        end
        if(row_cache_issue) begin row_cache_chunk<=row_cache_request;row_cache_request<=row_cache_request+1;end
            if(row_cache_pending&&row_cache_chunk==int'(block_rows)*8-1) row_cache_valid<=1;
        end
    end
    wire signed [16:0] mac_a=USE_ROW_CACHE?$signed(row_cache[(SMALL_INPUT?((row/ROW_GROUP)%INPUT_SLOTS)*ROW_GROUP*64:0)+mac_group*64+inner]):$signed({sp_rdata[(inner%8)*16+15],sp_rdata[(inner%8)*16+:16]});
    wire [35:0] quant_bits=accumulator[emit_group*LANES+lane];
    wire signed [63:0] quant_value={{28{quant_bits[35]}},quant_bits};
    wire signed [15:0] result_word;
    kwt_ffn_requantize quantizer(.value(quant_value),.shift(shifts[emit_group*LANES+lane]),.result(result_word));
    wire stash_write=state==EMIT_STASH;
    wire stash_read=(state==STASH_REQ)||((state==STASH_OUT)&&fifo_push&&stash_pointer<255);
    wire [7:0] stash_column=8'(tile*LANES+lane);
    wire [7:0] stash_address=8'((state==STASH_OUT)?stash_pointer+1:stash_pointer);
    wire [16*2*((ROW_GROUP>1)?ROW_GROUP-1:1)-1:0] stash_rdata;
    generate if(ROW_GROUP==1) assign stash_rdata=0;endgenerate
    generate for(genvar stash_bank=0;stash_bank<2*(ROW_GROUP-1);stash_bank=stash_bank+1) begin: row_stash
        wire clearing=!ZERO_CLEAR&&(state==CLEAR)&&(clear_index<128);
        wire writing=stash_write&&((emit_group-1)*2+int'(stash_column[0])==stash_bank);
        wire reading=stash_read&&((emit_group-1)*2+int'(stash_address[0])==stash_bank);
        wire memory_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(clearing||writing||reading),.test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(clearing||writing||reading),.we(clearing||writing),
            .addr(clearing?clear_index[6:0]:(writing?stash_column[7:1]:stash_address[7:1])),
            .wdata(clearing?16'd0:result_word),.rdata(stash_rdata[stash_bank*16+:16]));
    end endgenerate
    wire [15:0] fifo_word=(state==STASH_OUT)?stash_rdata[((emit_group-1)*2+(stash_pointer%2))*16+:16]:result_word;
    wire datapath_clk;
    kwt_ffn_clock_gate datapath_gate(.clk(clk),.enable(bias_capture||(state==B_MAC)||(state==ROW1_MAC)||fifo_push),
        .test_enable(clock_test_enable||!rst_n),.gated_clk(datapath_clk));
    generate for(genvar group_id=0;group_id<ROW_GROUP;group_id=group_id+1) begin: row_accumulators
        wire bias_update=bias_capture&&(group_id<int'(block_rows));
        wire mac_update=((state==B_MAC)||(state==ROW1_MAC))&&(mac_group==group_id);
        wire register_clk;
        if(0) begin: fine_gate
            kwt_ffn_clock_gate gate(.clk(clk),.enable(bias_update||mac_update),.test_enable(clock_test_enable||!rst_n),.gated_clk(register_clk));
        end else assign register_clk=datapath_clk;
        for(genvar lane_id=0;lane_id<LANES;lane_id=lane_id+1) begin: lane_registers
            always @(posedge register_clk or negedge rst_n) begin
                if(!rst_n) begin accumulator[group_id*LANES+lane_id]<=0;shifts[group_id*LANES+lane_id]<=0;end
                else begin
                    if(bias_update&&chunk==lane_id/2) begin
                        accumulator[group_id*LANES+lane_id]<=36'($signed(bias_pair[(lane_id%2)*64+:64]));
                        shifts[group_id*LANES+lane_id]<=$signed(shift_rdata[(lane_id%2)*8+:8]);
                    end
                    if(mac_update) accumulator[group_id*LANES+lane_id]<=accumulator[group_id*LANES+lane_id]+36'(mac_a*$signed(pm_rdata[lane_id*16+:16]));
                end
            end
        end
    end endgenerate
    generate for(genvar fifo_bank=0;fifo_bank<8;fifo_bank=fifo_bank+1) begin: fifo_write_banks
        wire bank_write=fifo_push&&(fifo_write[3:1]==3'(fifo_bank));
        wire bank_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(bank_write),.test_enable(clock_test_enable||!rst_n),.gated_clk(bank_clk));
        for(genvar word_id=0;word_id<2;word_id=word_id+1) begin: fifo_words
            always @(posedge bank_clk) if(bank_write&&fifo_write[0]==1'(word_id))
                fifo[fifo_bank*2+word_id]<=fifo_word;
        end
    end endgenerate
    assign start_ready=state==IDLE;
    assign layer_request=state==WAIT_LAYER;
    assign layer_start_ready=layer_request&&(parameter_count==17408)&&(shift_count==128);
    assign load_ready=!start_valid&&!layer_start_valid&&
        (((state==WAIT_LAYER)&&((load_kind==1)||(load_kind==5)))||
         ((load_kind==0)&&((!STREAM_INPUT&&(state==IDLE))||(STREAM_INPUT&&(state>=3)&&(input_count<6336)&&
             (int'(input_count)<(row+ROW_GROUP*INPUT_SLOTS)*64)))));
    assign busy=state!=IDLE;
    assign layer_index=0;
    assign out_valid=fifo_count!=0;
    assign out_pair_valid=fifo_count>=2;
    assign out_data=$signed(fifo[fifo_read]);
    wire [3:0] next_read=fifo_read+1'b1;
    assign out_high=$signed(fifo[next_read]);
    assign out_index=15'(item);
    assign trace_valid=fifo_push;
    assign trace_layer=0;assign trace_stage=9;
    assign trace_index=15'((row+((state==STASH_OUT)?emit_group:0))*256+((state==STASH_OUT)?stash_pointer:tile*LANES+lane));
    assign trace_data={{48{fifo_word[15]}},fifo_word};
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
                    pm_addr[bank_index*13+:13]=13'(address/LANES);pm_wdata[bank_index*16+:16]=k==0?load_data:load_high;
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
        if(row_cache_issue) begin
            sp_en='1;for(b=0;b<8;b=b+1) sp_addr[b*13+:13]=13'(row*8+row_cache_request);
        end
        if((state==A_REQ&&row_cache_ready)||prefetch) begin
            pm_en='1;for(b=0;b<LANES;b=b+1) pm_addr[b*13+:13]=13'(int'(weight_address)/LANES);
        end
        if(bias_request) begin
            bias_en='1;
            for(b=0;b<BIAS_BANKS;b=b+1) bias_addr[b*7+:7]=7'(BIAS32?(tile*(LANES/2)+chunk):(int'(bias_address)/BIAS_BANKS));
            shift_en=1;shift_addr=7'(tile*(LANES/2)+chunk);
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=CLEAR;clear_index<=0;input_count<=0;parameter_count<=0;shift_count<=0;
            row<=0;tile<=0;inner<=0;lane<=0;chunk<=0;item<=0;mac_group<=0;emit_group<=0;stash_pointer<=0;
            fifo_write<=0;fifo_read<=0;fifo_count<=0;done<=0;error<=0;layer_done<=0;
        end else begin
            done<=0;layer_done<=0;
            if(fifo_push) fifo_write<=fifo_write+1'b1;
            if(pop_count!=0) begin
                fifo_read<=fifo_read+4'(pop_count);
                if(item+int'(pop_count)==25344) begin done<=1;input_count<=0;parameter_count<=0;shift_count<=0;clear_index<=0;state<=CLEAR;end
                else item<=item+int'(pop_count);
            end
            fifo_count<=fifo_count+5'(fifo_push)-5'(pop_count);
            if(loading) case(load_kind)
                0:if(load_addr==16'(input_count)&&input_count<6336) input_count<=input_count+13'(load_count);else error<=1;
                1:if(load_addr==16'(parameter_count)&&parameter_count<17408) parameter_count<=parameter_count+15'(load_count);else error<=1;
                5:if(load_addr==16'(shift_count)&&shift_count<128) shift_count<=shift_count+1'b1;else error<=1;
            endcase
            case(state)
                CLEAR:if(ZERO_CLEAR||clear_index==0) begin clear_index<=0;state<=IDLE;end else clear_index<=clear_index+1'b1;
                IDLE:if(start_valid) begin
                    error<=0;
                    if((!STREAM_INPUT&&input_count!=6336)||!linear_mode) begin error<=1;done<=1;end
                    else begin parameter_count<=0;shift_count<=0;state<=WAIT_LAYER;end
                end
                WAIT_LAYER:if(layer_start_valid&&layer_start_ready) begin row<=0;tile<=0;item<=0;lane<=0;inner<=0;state<=WAIT_INPUT;end
                WAIT_INPUT:if(input_complete) state<=MAC_INIT;
                MAC_INIT:begin chunk<=0;state<=BIAS_REQ;end
                BIAS_REQ:state<=BIAS_CAP;
                BIAS_CAP:if(chunk==LANES/2-1) begin inner<=0;mac_group<=0;state<=A_REQ;end else begin chunk<=chunk+1;state<=BIAS_REQ;end
                A_REQ:if(row_cache_ready) state<=B_MAC;
                B_MAC,ROW1_MAC:if(mac_group<int'(block_rows)-1) begin mac_group<=mac_group+1;state<=ROW1_MAC;end
                    else begin mac_group<=0;if(inner==63) begin lane<=0;emit_group<=0;state<=EMIT;end else begin inner<=inner+1;state<=B_MAC;end end
                EMIT:if(fifo_push) begin
                    if(lane<LANES-1) lane<=lane+1;
                    else if(block_rows>1) begin emit_group<=1;lane<=0;state<=EMIT_STASH;end
                    else if(tile<TILES-1) begin tile<=tile+1;state<=MAC_INIT;end else state<=ADVANCE;
                end
                EMIT_STASH:if(lane<LANES-1) lane<=lane+1;
                    else if(emit_group<int'(block_rows)-1) begin emit_group<=emit_group+1;lane<=0;end
                    else if(tile<TILES-1) begin tile<=tile+1;state<=MAC_INIT;end
                    else begin emit_group<=1;stash_pointer<=0;state<=STASH_REQ;end
                STASH_REQ:state<=STASH_OUT;
                STASH_OUT:if(fifo_push) begin
                    if(stash_pointer<255) stash_pointer<=stash_pointer+1;
                    else if(emit_group<int'(block_rows)-1) begin emit_group<=emit_group+1;stash_pointer<=0;state<=STASH_REQ;end
                    else state<=ADVANCE;
                end
                ADVANCE:if(row+int'(block_rows)==99) begin layer_done<=1;state<=DRAIN;end
                    else begin row<=row+ROW_GROUP;tile<=0;lane<=0;state<=WAIT_INPUT;end
                DRAIN:begin end
                default:begin error<=1;done<=1;state<=CLEAR;end
            endcase
        end
    end
endmodule
