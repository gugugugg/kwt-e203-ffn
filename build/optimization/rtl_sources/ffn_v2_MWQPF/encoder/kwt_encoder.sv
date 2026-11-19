module kwt_encoder #(
    parameter integer COMPACT=1,
    parameter integer SMALL_SHIFT=1,ACC_WIDTH=36,NARROW_QUANT=1,
    parameter integer PIPE_MAC=1,STREAM_OUTPUT=1,ROW_PAIR=0
)(
    input wire clk,rst_n,linear_mode,load_valid,
    output wire load_ready,
    input wire [2:0] load_kind,
    input wire [15:0] load_addr,load_data,
    input wire start_valid,
    output wire start_ready,layer_request,
    output wire [3:0] layer_index,
    input wire layer_start_valid,
    output wire layer_start_ready,busy,
    output reg done,error,layer_done,
    output wire out_valid,
    input wire out_ready,
    output wire [14:0] out_index,
    output wire signed [15:0] out_data,
    output wire trace_valid,
    output wire [3:0] trace_layer,trace_stage,
    output wire [14:0] trace_index,
    output wire signed [63:0] trace_data
);
    localparam integer SCRATCH_LEAVES=STREAM_OUTPUT?1:(COMPACT?4:5),PARAM_LEAVES=COMPACT?3:7;
    localparam integer ROWS=ROW_PAIR?2:1;
    localparam integer PARAM_BASE=COMPACT?0:17408,OUTPUT_BASE=6336;
    localparam [3:0] CLEAR=0,IDLE=1,WAIT_LAYER=2,MAC_INIT=3,BIAS_REQ=4,
        BIAS_CAP=5,A_REQ=6,B_MAC=7,EMIT=8,OUT_REQ=9,OUT_CAP=10,OUT_HOLD=11,DRAIN=12;
    reg [3:0] state;
    reg [13:0] clear_index;
    reg [12:0] input_count;
    reg [14:0] parameter_count;
    reg [7:0] shift_count;
    integer row,tile,inner,lane,chunk,item,b,i,r,row_slot;
    reg signed [ACC_WIDTH-1:0] accumulator[0:ROWS*8-1];
    reg signed [7:0] shifts[0:7];
    reg [7:0] sp_en,sp_we,pm_en,pm_we;
    reg [103:0] sp_addr,pm_addr;
    reg [127:0] sp_wdata,pm_wdata;
    wire [127:0] sp_rdata,pm_rdata;
    reg row_en;
    reg [5:0] row_we;
    reg [6:0] row_addr;
    reg [95:0] row_wdata;
    wire [95:0] row_rdata;
    wire loading=load_valid&&load_ready;
    reg signed [15:0] buffered_out_data;
    reg [15:0] fifo[0:15];
    reg [3:0] fifo_write,fifo_read;
    reg [4:0] fifo_count;
    wire fifo_pop=STREAM_OUTPUT&&(fifo_count!=0)&&out_ready;
    wire fifo_push=STREAM_OUTPUT&&(state==EMIT)&&((fifo_count<16)||fifo_pop);
    wire emit_accept=!STREAM_OUTPUT||fifo_push;
    wire second_row=ROW_PAIR&&(row<98);
    wire prefetch=PIPE_MAC&&(state==B_MAC)&&(inner<63);
    wire [5:0] request_inner=6'(inner+int'(prefetch));
    wire [15:0] load_parameter_address=load_addr+16'(PARAM_BASE);
    wire [15:0] parameter_address=16'(PARAM_BASE+((state==BIAS_REQ)?16384+tile*32+chunk*8:int'(request_inner)*256+tile*8));
    wire [14:0] input_address=15'((row+row_slot)*64+inner);
    wire [14:0] output_address=15'(OUTPUT_BASE+(row+row_slot)*256+tile*8+lane);
    wire [14:0] read_address=(state==OUT_REQ)?15'(OUTPUT_BASE+item):15'((row+row_slot)*64+int'(request_inner));
    wire signed [16:0] mac_a=$signed({sp_rdata[(input_address%8)*16+15],sp_rdata[(input_address%8)*16+:16]});
    wire signed [15:0] result_word;
    wire signed [63:0] quant_value=state==EMIT?64'($signed(accumulator[row_slot*8+lane])):64'sd0;
    generate if(NARROW_QUANT) begin: specialized_quant
        kwt_ffn_requantize quantizer(.value(quant_value),.shift(shifts[lane]),.result(result_word));
    end else begin: general_quant
        kwt_requantize quantizer(.value(quant_value),.shift(state==EMIT?shifts[lane]:8'sd0),.result(result_word));
    end endgenerate
    kwt_encoder_memory #(.BANK_LEAVES(SCRATCH_LEAVES)) scratch(
        .clk(clk),.en(sp_en),.we(sp_we),.addr(sp_addr),.wdata(sp_wdata),.rdata(sp_rdata));
    kwt_encoder_memory #(.BANK_LEAVES(PARAM_LEAVES)) parameters(
        .clk(clk),.en(pm_en),.we(pm_we),.addr(pm_addr),.wdata(pm_wdata),.rdata(pm_rdata));
    generate if(SMALL_SHIFT) begin: shift_only
        kwt_encoder_sram16x128 memory(.clk(clk),.en(row_en),.we(row_we[0]),
            .addr(row_addr),.wdata(row_wdata[15:0]),.rdata(row_rdata[15:0]));
        assign row_rdata[95:16]=0;
    end else begin: wide_shift
        kwt_encoder_row_memory workspace(.clk(clk),.en(row_en),.we(row_we),
            .addr(row_addr),.wdata(row_wdata),.rdata(row_rdata));
    end endgenerate
    assign start_ready=state==IDLE;
    assign layer_request=state==WAIT_LAYER;
    assign layer_start_ready=layer_request&&parameter_count==17408&&shift_count==128;
    assign load_ready=((state==IDLE&&load_kind==0)||
        (state==WAIT_LAYER&&(load_kind==1||load_kind==5)))&&!start_valid&&!layer_start_valid;
    assign busy=state!=IDLE;
    assign layer_index=0;
    assign out_valid=STREAM_OUTPUT?(fifo_count!=0):(state==OUT_HOLD);
    assign out_data=STREAM_OUTPUT?$signed(fifo[fifo_read]):buffered_out_data;
    assign out_index=15'(item);
    assign trace_valid=(state==EMIT)&&emit_accept;
    assign trace_layer=0;
    assign trace_stage=9;
    assign trace_index=15'((row+row_slot)*256+tile*8+lane);
    assign trace_data={{48{result_word[15]}},result_word};
    always @* begin
        sp_en=0;sp_we=0;sp_addr=0;sp_wdata=0;
        pm_en=0;pm_we=0;pm_addr=0;pm_wdata=0;
        row_en=0;row_we=0;row_addr=0;row_wdata=0;
        if(state==CLEAR) begin
            if(clear_index<SCRATCH_LEAVES*1024) begin sp_en='1;sp_we='1;end
            if(clear_index<PARAM_LEAVES*1024) begin pm_en='1;pm_we='1;end
            for(b=0;b<8;b=b+1) begin sp_addr[b*13+:13]=clear_index[12:0];pm_addr[b*13+:13]=clear_index[12:0];end
            if(clear_index<128) begin row_en=1;row_we=1;row_addr=clear_index[6:0];end
        end
        if(loading) begin
            if(load_kind==0&&load_addr=={3'b0,input_count}&&input_count<6336) begin
                sp_en[load_addr[2:0]]=1;sp_we[load_addr[2:0]]=1;
                sp_addr[load_addr[2:0]*13+:13]=load_addr[15:3];sp_wdata[load_addr[2:0]*16+:16]=load_data;
            end
            if(load_kind==1&&load_addr==parameter_count&&parameter_count<17408) begin
                pm_en[load_addr[2:0]]=1;pm_we[load_addr[2:0]]=1;
                pm_addr[load_addr[2:0]*13+:13]=load_parameter_address[15:3];pm_wdata[load_addr[2:0]*16+:16]=load_data;
            end
            if(load_kind==5&&load_addr=={8'b0,shift_count}&&shift_count<128) begin
                row_en=1;row_we=1;row_addr=load_addr[6:0];row_wdata[15:0]=load_data;
            end
        end
        if(state==A_REQ||prefetch||(!STREAM_OUTPUT&&state==OUT_REQ)) begin
            sp_en[read_address%8]=1;sp_addr[(read_address%8)*13+:13]=13'(read_address/8);
        end
        if((state==A_REQ&&row_slot==0)||prefetch||state==BIAS_REQ) begin
            pm_en='1;
            for(b=0;b<8;b=b+1) pm_addr[b*13+:13]=13'(parameter_address/8);
        end
        if(state==BIAS_REQ) begin row_en=1;row_addr=7'(tile*4+chunk);end
        if(state==EMIT&&!STREAM_OUTPUT) begin
            sp_en[output_address%8]=1;sp_we[output_address%8]=1;
            sp_addr[(output_address%8)*13+:13]=13'(output_address/8);sp_wdata[(output_address%8)*16+:16]=result_word;
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=CLEAR;clear_index<=0;input_count<=0;parameter_count<=0;shift_count<=0;
            row<=0;tile<=0;inner<=0;lane<=0;chunk<=0;item<=0;row_slot<=0;
            done<=0;error<=0;layer_done<=0;buffered_out_data<=0;
            fifo_write<=0;fifo_read<=0;fifo_count<=0;
            for(i=0;i<ROWS*8;i=i+1) accumulator[i]<=0;
            for(i=0;i<8;i=i+1) shifts[i]<=0;
        end else begin
            done<=0;layer_done<=0;
            if(fifo_push) begin fifo[fifo_write]<=result_word;fifo_write<=fifo_write+1'b1;end
            if(fifo_pop) begin
                fifo_read<=fifo_read+1'b1;
                if(item==25343) begin
                    done<=1;input_count<=0;parameter_count<=0;shift_count<=0;clear_index<=0;state<=CLEAR;
                end else item<=item+1;
            end
            case({fifo_push,fifo_pop})
                2'b10:fifo_count<=fifo_count+1'b1;
                2'b01:fifo_count<=fifo_count-1'b1;
                default:begin end
            endcase
            if(loading) begin
                case(load_kind)
                    0: if(load_addr=={3'b0,input_count}&&input_count<6336) input_count<=input_count+1'b1;else error<=1;
                    1: if(load_addr==parameter_count&&parameter_count<17408) parameter_count<=parameter_count+1'b1;else error<=1;
                    5: if(load_addr=={8'b0,shift_count}&&shift_count<128) shift_count<=shift_count+1'b1;else error<=1;
                endcase
            end
            case(state)
                CLEAR: if(clear_index==8193) begin clear_index<=0;state<=IDLE;end else clear_index<=clear_index+1'b1;
                IDLE: if(start_valid) begin
                    error<=0;
                    if(input_count!=6336||!linear_mode) begin error<=1;done<=1;end
                    else begin parameter_count<=0;shift_count<=0;state<=WAIT_LAYER;end
                end
                WAIT_LAYER: if(layer_start_valid&&layer_start_ready) begin row<=0;tile<=0;item<=0;state<=MAC_INIT;end
                MAC_INIT: begin chunk<=0;row_slot<=0;state<=BIAS_REQ;end
                BIAS_REQ: state<=BIAS_CAP;
                BIAS_CAP: begin
                    shifts[chunk*2]<=$signed(row_rdata[7:0]);shifts[chunk*2+1]<=$signed(row_rdata[15:8]);
                    for(r=0;r<ROWS;r=r+1) begin
                        accumulator[r*8+chunk*2]<=ACC_WIDTH'($signed(pm_rdata[63:0]));
                        accumulator[r*8+chunk*2+1]<=ACC_WIDTH'($signed(pm_rdata[127:64]));
                    end
                    if(chunk==3) begin inner<=0;state<=A_REQ;end else begin chunk<=chunk+1;state<=BIAS_REQ;end
                end
                A_REQ: state<=B_MAC;
                B_MAC: begin
                    for(i=0;i<8;i=i+1) accumulator[row_slot*8+i]<=accumulator[row_slot*8+i]+ACC_WIDTH'(mac_a*$signed(pm_rdata[i*16+:16]));
                    if(second_row&&row_slot==0) begin row_slot<=1;state<=A_REQ;end
                    else begin
                        row_slot<=0;
                        if(inner==63) begin lane<=0;state<=EMIT;end
                        else begin inner<=inner+1;state<=PIPE_MAC?B_MAC:A_REQ;end
                    end
                end
                EMIT: if(emit_accept) begin
                    if(lane<7) lane<=lane+1;
                    else if(second_row&&row_slot==0) begin row_slot<=1;lane<=0;end
                    else if(tile<31) begin tile<=tile+1;state<=MAC_INIT;end
                    else if(row+(second_row?1:0)<98) begin tile<=0;row<=row+ROWS;state<=MAC_INIT;end
                    else begin
                        layer_done<=1;
                        if(STREAM_OUTPUT) state<=DRAIN;else begin item<=0;state<=OUT_REQ;end
                    end
                end
                OUT_REQ: state<=OUT_CAP;
                OUT_CAP: begin buffered_out_data<=sp_rdata[((OUTPUT_BASE+item)%8)*16+:16];state<=OUT_HOLD;end
                DRAIN: begin end
                OUT_HOLD: if(out_ready) begin
                    if(item==25343) begin done<=1;input_count<=0;parameter_count<=0;shift_count<=0;clear_index<=0;state<=CLEAR;end
                    else begin item<=item+1;state<=OUT_REQ;end
                end
                default: begin error<=1;done<=1;state<=CLEAR;end
            endcase
        end
    end
endmodule
