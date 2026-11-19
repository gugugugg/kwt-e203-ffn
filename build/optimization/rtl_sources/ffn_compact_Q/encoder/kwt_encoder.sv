module kwt_encoder #(
    parameter integer COMPACT=1
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
    output reg signed [15:0] out_data,
    output wire trace_valid,
    output wire [3:0] trace_layer,trace_stage,
    output wire [14:0] trace_index,
    output wire signed [63:0] trace_data
);
    localparam integer SCRATCH_LEAVES=COMPACT?4:5,PARAM_LEAVES=COMPACT?3:7;
    localparam integer PARAM_BASE=COMPACT?0:17408,OUTPUT_BASE=6336;
    localparam [3:0] CLEAR=0,IDLE=1,WAIT_LAYER=2,MAC_INIT=3,BIAS_REQ=4,
        BIAS_CAP=5,A_REQ=6,B_MAC=7,EMIT=8,OUT_REQ=9,OUT_CAP=10,OUT_HOLD=11;
    reg [3:0] state;
    reg [13:0] clear_index;
    reg [12:0] input_count;
    reg [14:0] parameter_count;
    reg [7:0] shift_count;
    integer row,tile,inner,lane,chunk,item,b,i;
    reg signed [63:0] accumulator[0:7];
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
    wire [15:0] load_parameter_address=load_addr+16'(PARAM_BASE);
    wire [15:0] parameter_address=16'(PARAM_BASE+((state==BIAS_REQ)?16384+tile*32+chunk*8:inner*256+tile*8));
    wire [14:0] input_address=15'(row*64+inner);
    wire [14:0] output_address=15'(OUTPUT_BASE+row*256+tile*8+lane);
    wire [14:0] read_address=(state==OUT_REQ)?15'(OUTPUT_BASE+item):input_address;
    wire signed [16:0] mac_a=$signed({sp_rdata[(input_address%8)*16+15],sp_rdata[(input_address%8)*16+:16]});
    wire signed [15:0] result_word;
    kwt_requantize quantizer(.value(state==EMIT?accumulator[lane]:64'sd0),
        .shift(state==EMIT?shifts[lane]:8'sd0),.result(result_word));
    kwt_encoder_memory #(.BANK_LEAVES(SCRATCH_LEAVES)) scratch(
        .clk(clk),.en(sp_en),.we(sp_we),.addr(sp_addr),.wdata(sp_wdata),.rdata(sp_rdata));
    kwt_encoder_memory #(.BANK_LEAVES(PARAM_LEAVES)) parameters(
        .clk(clk),.en(pm_en),.we(pm_we),.addr(pm_addr),.wdata(pm_wdata),.rdata(pm_rdata));
    kwt_encoder_row_memory workspace(.clk(clk),.en(row_en),.we(row_we),
        .addr(row_addr),.wdata(row_wdata),.rdata(row_rdata));
    assign start_ready=state==IDLE;
    assign layer_request=state==WAIT_LAYER;
    assign layer_start_ready=layer_request&&parameter_count==17408&&shift_count==128;
    assign load_ready=((state==IDLE&&load_kind==0)||
        (state==WAIT_LAYER&&(load_kind==1||load_kind==5)))&&!start_valid&&!layer_start_valid;
    assign busy=state!=IDLE;
    assign layer_index=0;
    assign out_valid=state==OUT_HOLD;
    assign out_index=15'(item);
    assign trace_valid=state==EMIT;
    assign trace_layer=0;
    assign trace_stage=9;
    assign trace_index=15'(row*256+tile*8+lane);
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
        if(state==A_REQ||state==OUT_REQ) begin
            sp_en[read_address%8]=1;sp_addr[(read_address%8)*13+:13]=13'(read_address/8);
        end
        if(state==A_REQ||state==BIAS_REQ) begin
            pm_en='1;
            for(b=0;b<8;b=b+1) pm_addr[b*13+:13]=13'(parameter_address/8);
        end
        if(state==BIAS_REQ) begin row_en=1;row_addr=7'(tile*4+chunk);end
        if(state==EMIT) begin
            sp_en[output_address%8]=1;sp_we[output_address%8]=1;
            sp_addr[(output_address%8)*13+:13]=13'(output_address/8);sp_wdata[(output_address%8)*16+:16]=result_word;
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=CLEAR;clear_index<=0;input_count<=0;parameter_count<=0;shift_count<=0;
            row<=0;tile<=0;inner<=0;lane<=0;chunk<=0;item<=0;
            done<=0;error<=0;layer_done<=0;out_data<=0;
            for(i=0;i<8;i=i+1) begin accumulator[i]<=0;shifts[i]<=0;end
        end else begin
            done<=0;layer_done<=0;
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
                WAIT_LAYER: if(layer_start_valid&&layer_start_ready) begin row<=0;tile<=0;state<=MAC_INIT;end
                MAC_INIT: begin chunk<=0;state<=BIAS_REQ;end
                BIAS_REQ: state<=BIAS_CAP;
                BIAS_CAP: begin
                    shifts[chunk*2]<=$signed(row_rdata[7:0]);shifts[chunk*2+1]<=$signed(row_rdata[15:8]);
                    accumulator[chunk*2]<=$signed(pm_rdata[63:0]);accumulator[chunk*2+1]<=$signed(pm_rdata[127:64]);
                    if(chunk==3) begin inner<=0;state<=A_REQ;end else begin chunk<=chunk+1;state<=BIAS_REQ;end
                end
                A_REQ: state<=B_MAC;
                B_MAC: begin
                    for(i=0;i<8;i=i+1) accumulator[i]<=accumulator[i]+64'(mac_a*$signed(pm_rdata[i*16+:16]));
                    if(inner==63) begin lane<=0;state<=EMIT;end else begin inner<=inner+1;state<=A_REQ;end
                end
                EMIT: begin
                    if(lane<7) lane<=lane+1;
                    else if(tile<31) begin tile<=tile+1;state<=MAC_INIT;end
                    else if(row<98) begin tile<=0;row<=row+1;state<=MAC_INIT;end
                    else begin item<=0;layer_done<=1;state<=OUT_REQ;end
                end
                OUT_REQ: state<=OUT_CAP;
                OUT_CAP: begin out_data<=sp_rdata[((OUTPUT_BASE+item)%8)*16+:16];state<=OUT_HOLD;end
                OUT_HOLD: if(out_ready) begin
                    if(item==25343) begin done<=1;input_count<=0;parameter_count<=0;shift_count<=0;clear_index<=0;state<=CLEAR;end
                    else begin item<=item+1;state<=OUT_REQ;end
                end
                default: begin error<=1;done<=1;state<=CLEAR;end
            endcase
        end
    end
endmodule
