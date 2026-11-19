// Complete fixed16-v1 PostNorm encoder, 12 sequential layers, one parameter cache.
// Hardware owns all attention/FFN/residual/nonlinear arithmetic. No CPU math hooks.
module kwt_encoder(
    input wire clk,rst_n,
    input wire linear_mode,
    input wire load_valid,
    output wire load_ready,
    input wire [2:0] load_kind, // 0=input, 1=layer words, 2=config, 3=exp, 4=GELU
    input wire [15:0] load_addr,
    input wire [15:0] load_data,
    input wire start_valid,
    output wire start_ready,
    output wire layer_request,
    output reg [3:0] layer_index,
    input wire layer_start_valid,
    output wire layer_start_ready,
    output wire busy,
    output reg done,error,layer_done,
    output wire out_valid,
    input wire out_ready,
    output wire [14:0] out_index,
    output reg signed [15:0] out_data,
    // Observation only; these ports cannot supply answers or alter execution.
    output reg trace_valid,
    output wire [3:0] trace_layer,
    output reg [3:0] trace_stage,
    output reg [14:0] trace_index,
    output reg signed [63:0] trace_data
);
    `include "kwt_encoder_functions.svh"
    localparam integer X=0,Q=6336,K=12672,V=19328,C=25664,F=0,T=32000;
    localparam integer SCRATCH_LEAVES=5,LINEAR_F=6336;
    localparam integer FAST_MAC=1;
    localparam [5:0] CLEAR=0,IDLE=1,WAIT_LAYER=2,MAC_INIT=3,BIAS_REQ=4,BIAS_CAP=5,
        A_REQ=6,A_CAP=7,B_REQ=8,B_MAC=9,EMIT=10,EXP_REQ=11,EXP_CAP=12,
        LUT_AREQ=13,LUT_ACAP=14,LUT_BREQ=15,LUT_BCAP=16,LUT_WRITE=17,
        PROB_REQ=18,PROB_CAP=19,PROB_START=20,PROB_WAIT=21,PROB_WRITE=22,
        RES_AREQ=23,RES_ACAP=24,RES_BREQ=25,RES_BCAP=26,RES_WRITE=27,
        GELU_REQ=28,GELU_CAP=29,LN_LOADREQ=30,LN_LOADCAP=31,LN_VARREQ=32,
        LN_VARCAP=33,LN_SQRT_GO=34,LN_SQRT_WAIT=35,LN_AREQ=36,LN_ACAP=37,
        LN_BREQ=38,LN_BCAP=39,LN_DIVWAIT=40,LN_WRITE=41,LAYER_DONE=42,
        OUT_REQ=43,OUT_CAP=44,OUT_HOLD=45;
    reg [5:0] state;
    reg [3:0] op;
    reg task_linear;
    reg [7:0] linear_shift_count;
    reg signed [7:0] linear_shifts[0:7];
    wire [15:0] parameter_words=task_linear?16'd17408:16'd51712;
    wire [15:0] parameter_load_address=load_addr+(task_linear?16'd17408:16'd0);
    reg [15:0] cfg[0:31];
    reg [13:0] clear_index,exp_count,gelu_count;
    reg [12:0] input_count;
    reg [15:0] parameter_count;
    reg [5:0] config_count;
    integer row,tile,inner,emit_lane,bias_chunk,item,feature;
    reg signed [16:0] operand_a;
    reg signed [63:0] accumulator[0:7];
    reg signed [63:0] row_max,lut_x,lut_a,lut_interpolated,scalar_result;
    reg [15:0] x_hold,probability;
    reg [63:0] exp_sum;
    reg signed [63:0] norm_sum;
    reg [63:0] norm_squares,norm_denominator;
    reg [15:0] gamma_hold,beta_hold;
    reg signed [63:0] divide_numerator;
    reg [63:0] divide_denominator;
    wire unused_div_busy,div_done,div_error,unused_sqrt_busy,sqrt_done;
    wire signed [63:0] divide_result;
    wire [63:0] sqrt_result;
    wire div_start=(state==PROB_START)||(state==LN_BREQ);
    wire sqrt_start=state==LN_SQRT_GO;
    wire [63:0] epsilon_add=(op==8)?{cfg[26],cfg[25],cfg[24],cfg[23]}:
                                                    {cfg[30],cfg[29],cfg[28],cfg[27]};
    wire [127:0] sqrt_operand=({64'b0,norm_squares}<<16)+{64'b0,epsilon_add};
    kwt_encoder_div_bounded divider(.clk(clk),.rst_n(rst_n),.start(div_start),
        .last_bit((state==PROB_START)?5'd15:5'd23),
        .numerator(divide_numerator),.denominator(divide_denominator),
        .busy(unused_div_busy),.done(div_done),.error(div_error),.result(divide_result));
    kwt_encoder_sqrt128 square_root(.clk(clk),.rst_n(rst_n),.start(sqrt_start),
        .radicand(sqrt_operand),.busy(unused_sqrt_busy),.done(sqrt_done),.result(sqrt_result));

    reg [7:0] sp_en,sp_we,pm_en,pm_we;
    reg [103:0] sp_addr,pm_addr;
    reg [127:0] sp_wdata,pm_wdata;
    wire [127:0] sp_rdata,pm_rdata;
    wire [95:0] row_rdata;
    reg row_en;
    reg [5:0] row_we;
    reg [6:0] row_addr;
    reg [95:0] row_wdata;
    reg exp_load,gelu_load,lut_read;
    reg [13:0] table_load_addr;
    reg [15:0] table_load_data;
    reg [12:0] table_index;
    wire [31:0] exp_data,gelu_data;
    kwt_encoder_memory #(.BANK_LEAVES(SCRATCH_LEAVES)) scratch(.clk(clk),.en(sp_en),.we(sp_we),.addr(sp_addr),.wdata(sp_wdata),.rdata(sp_rdata));
    kwt_encoder_memory #(.BANK_LEAVES(7)) parameters(.clk(clk),.en(pm_en),.we(pm_we),.addr(pm_addr),.wdata(pm_wdata),.rdata(pm_rdata));
    kwt_encoder_row_memory workspace(.clk(clk),.en(row_en),.we(row_we),.addr(row_addr),.wdata(row_wdata),.rdata(row_rdata));
    kwt_encoder_lut32 exponent_table(.clk(clk),.load(exp_load),.load_addr(table_load_addr),.load_data(table_load_data),
        .read_en(lut_read&&(op!=10)),.read_index(table_index),.rdata(exp_data));
    kwt_encoder_lut32 gelu_table(.clk(clk),.load(gelu_load),.load_addr(table_load_addr),.load_data(table_load_data),
        .read_en(lut_read&&(op==10)),.read_index(table_index),.rdata(gelu_data));

    integer columns,depth,source_base,destination_base,kernel_base,bias_base,mac_shift;
    integer address_a,address_b,address_write,parameter_address,res_a_f,res_b_f,res_out_f,common_f;
    integer norm_gamma_base,norm_beta_base,norm_gamma_f,norm_beta_f,norm_output_f;
    integer lut_offset,lut_node,lut_fraction;
    integer b,j;
    reg config_legal;
    reg signed [63:0] lut_b,lut_value,gelu_value,res_total,centered,affine;
    reg [63:0] centered_square;
    reg [15:0] result_word;
    wire signed [15:0] linear_result;
    wire signed [63:0] linear_quant_value=(task_linear&&state==EMIT)?accumulator[emit_lane]:64'sd0;
    wire dense_mac=(op!=3)&&(op!=5);
    wire signed [16:0] mac_a=(FAST_MAC&&dense_mac)?
        $signed({sp_rdata[(address_a%8)*16+15],sp_rdata[(address_a%8)*16+:16]}):operand_a;
    wire signed [7:0] linear_quant_shift=task_linear?linear_shifts[emit_lane]:8'sd0;
    kwt_requantize linear_quantizer(.value(linear_quant_value),.shift(linear_quant_shift),.result(linear_result));
    always @* begin
        columns=64; depth=64; source_base=X; destination_base=Q; kernel_base=0; bias_base=4096; mac_shift=int'($signed(cfg[0]));
        case(op)
            1: begin destination_base=K; kernel_base=4352; bias_base=8448; mac_shift=int'($signed(cfg[1])); end
            2: begin destination_base=V; kernel_base=8704; bias_base=12800; mac_shift=int'($signed(cfg[2])); end
            3: begin columns=99; source_base=Q; end
            5: begin depth=99; destination_base=C; mac_shift=15+int'(cfg[9])-int'(cfg[10]); end
            6: begin source_base=C; destination_base=T; kernel_base=13056; bias_base=17152; mac_shift=int'($signed(cfg[3])); end
            9: begin columns=256; source_base=task_linear?X:C; destination_base=task_linear?LINEAR_F:F; kernel_base=17408; bias_base=33792; mac_shift=int'($signed(cfg[4])); end
            11: begin depth=256; source_base=F; destination_base=T; kernel_base=34816; bias_base=51200; mac_shift=int'($signed(cfg[5])); end
            default: begin end
        endcase
        address_a=source_base+row*depth+inner;
        address_b=(op==3)?K+inner*104+tile*8:V+inner*64+tile*8;
        address_write=destination_base+row*columns+tile*8+emit_lane;
        if(op==1) address_write=K+(tile*8+emit_lane)*104+row;
        if(state==RES_WRITE) address_write=C+item;
        if(state==LUT_WRITE&&op==10) address_write=F+item;
        if(state==LN_WRITE) address_write=((op==8)?C:X)+row*64+feature;
        parameter_address=kernel_base+inner*columns+tile*8;
        if(state==BIAS_REQ || state==BIAS_CAP) parameter_address=bias_base+tile*32+bias_chunk*8;
        res_a_f=(op==7)?int'(cfg[6]):int'(cfg[13]);
        res_b_f=(op==7)?int'(cfg[11]):int'(cfg[16]);
        res_out_f=(op==7)?int'(cfg[12]):int'(cfg[17]);
        common_f=(res_a_f>res_b_f)?res_a_f:res_b_f;
        if(state==RES_AREQ || state==RES_ACAP) address_a=((op==7)?X:C)+item;
        if(state==RES_BREQ || state==RES_BCAP) address_a=T+item;
        if(state==GELU_REQ || state==GELU_CAP) address_a=F+item;
        if(state==LN_LOADREQ || state==LN_LOADCAP) address_a=C+row*64+feature;
        if(state==OUT_REQ || state==OUT_CAP) address_a=(task_linear?LINEAR_F:X)+item;
        norm_gamma_base=(op==8)?51456:51584; norm_beta_base=(op==8)?51520:51648;
        norm_gamma_f=(op==8)?int'(cfg[19]):int'(cfg[21]);
        norm_beta_f=(op==8)?int'(cfg[20]):int'(cfg[22]);
        norm_output_f=(op==8)?int'(cfg[13]):int'(cfg[18]);
        if(state==LN_AREQ || state==LN_ACAP) parameter_address=norm_gamma_base+feature;
        if(state==LN_BREQ || state==LN_BCAP) parameter_address=norm_beta_base+feature;
        config_legal=1;
        for(j=0;j<6;j=j+1) if($signed(cfg[j])< -30 || $signed(cfg[j])>62) config_legal=0;
        for(j=6;j<23;j=j+1) if(cfg[j]>24) config_legal=0;
        if(lut_x<((op==10)?-64'sd524288:-64'sd1048576)) lut_offset=0;
        else if(lut_x>((op==10)?64'sd524288:64'sd0)) lut_offset=1048576;
        else lut_offset=int'(lut_x)+((op==10)?524288:1048576);
        lut_node=(lut_offset>>8); if(lut_node>4095) lut_node=4095;
        lut_fraction=lut_offset-(lut_node<<8);
        lut_b=(op==10)?{{32{gelu_data[31]}},gelu_data}:{32'b0,exp_data};
        lut_value=rne(lut_a*(64'sd256-64'(lut_fraction))+lut_b*64'(lut_fraction),8);
        gelu_value=lut_interpolated;
        if(lut_x<= -524288) gelu_value=0;
        if(lut_x>=524288) gelu_value=rne(sx16(x_hold),int'(cfg[14])-20);
        res_total=rne(sx16(x_hold),res_a_f-common_f)+rne(sx16(sp_rdata[(address_a%8)*16+:16]),res_b_f-common_f);
        centered=(sx16(row_rdata[15:0])<<<6)-norm_sum;
        centered_square=64'(centered*centered);
        affine=divide_result*sx16(gamma_hold)+rne(sx16(beta_hold),norm_beta_f-(20+norm_gamma_f));
        result_word=task_linear?linear_result:sat(rne(accumulator[emit_lane],mac_shift));
    end

    assign start_ready=state==IDLE;
    assign layer_request=state==WAIT_LAYER;
    assign layer_start_ready=layer_request&&(parameter_count==parameter_words)&&
        (task_linear?(linear_shift_count==128):(config_count==32));
    assign load_ready=((state==IDLE&&((load_kind==0)||(load_kind==3)||(load_kind==4))) ||
                       (state==WAIT_LAYER&&((load_kind==1)||(load_kind==2)||(task_linear&&load_kind==5))))&&!start_valid&&!layer_start_valid;
    assign busy=state!=IDLE;
    assign out_valid=state==OUT_HOLD;
    assign out_index=15'(item);
    assign trace_layer=layer_index;
    wire loading=load_valid&&load_ready;

    always @* begin
        b=0;
        sp_en=0; sp_we=0; sp_addr=0; sp_wdata=0;
        pm_en=0; pm_we=0; pm_addr=0; pm_wdata=0;
        row_en=0; row_we=0; row_addr=0; row_wdata=0;
        exp_load=0; gelu_load=0; table_load_addr=load_addr[13:0]; table_load_data=load_data;
        lut_read=0; table_index=13'(lut_node);
        trace_valid=0; trace_stage=op; trace_index=0; trace_data=0;
        if(state==CLEAR) begin
            if(clear_index<SCRATCH_LEAVES*1024) begin sp_en='1; sp_we='1; end
            if(clear_index<7168) begin pm_en='1; pm_we='1; end
            for(b=0;b<8;b=b+1) begin sp_addr[b*13+:13]=clear_index[12:0]; pm_addr[b*13+:13]=clear_index[12:0]; end
            exp_load=1; gelu_load=1; table_load_addr=clear_index; table_load_data=0;
            if(clear_index<128) begin row_en=1; row_we='1; row_addr=clear_index[6:0]; end
        end
        if(loading) begin
            if(load_kind==0 && load_addr=={3'b0,input_count} && input_count<6336) begin
                sp_en[load_addr[2:0]]=1; sp_we[load_addr[2:0]]=1;
                sp_addr[load_addr[2:0]*13+:13]=load_addr[15:3]; sp_wdata[load_addr[2:0]*16+:16]=load_data;
            end
            if(load_kind==1 && load_addr==parameter_count && parameter_count<parameter_words) begin
                pm_en[load_addr[2:0]]=1; pm_we[load_addr[2:0]]=1;
                pm_addr[load_addr[2:0]*13+:13]=parameter_load_address[15:3]; pm_wdata[load_addr[2:0]*16+:16]=load_data;
            end
            if(load_kind==5&&task_linear&&load_addr=={8'b0,linear_shift_count}&&linear_shift_count<128) begin
                row_en=1; row_we=6'h01; row_addr=load_addr[6:0]; row_wdata[15:0]=load_data;
            end
            if(load_kind==3 && load_addr=={2'b0,exp_count} && exp_count<8194) exp_load=1;
            if(load_kind==4 && load_addr=={2'b0,gelu_count} && gelu_count<8194) gelu_load=1;
        end
        if((state==A_REQ&&op!=5)||state==RES_AREQ||state==RES_BREQ||state==GELU_REQ||state==LN_LOADREQ||state==OUT_REQ) begin
            sp_en[address_a%8]=1; sp_addr[(address_a%8)*13+:13]=13'(address_a/8);
        end
        if(state==BIAS_REQ || ((FAST_MAC?(state==A_REQ):(state==B_REQ))&&dense_mac)) begin
            pm_en='1;
            for(b=0;b<8;b=b+1) pm_addr[b*13+:13]=13'(parameter_address/8);
        end
        if(task_linear&&state==BIAS_REQ) begin
            row_en=1; row_addr=7'(tile*4+bias_chunk);
        end
        if((FAST_MAC?(state==A_CAP):(state==B_REQ))&&(op==3||op==5)) begin
            sp_en='1;
            for(b=0;b<8;b=b+1) sp_addr[b*13+:13]=13'(address_b/8);
        end
        if(state==A_REQ&&op==5) begin row_en=1; row_addr=7'(inner); end
        if(state==EMIT && tile*8+emit_lane<columns) begin
            trace_valid=1; trace_index=15'(row*columns+tile*8+emit_lane);
            trace_data=(op==3)?accumulator[emit_lane]:sx16(result_word);
            if(op==3) begin row_en=1; row_we=6'h0f; row_addr=7'(tile*8+emit_lane); row_wdata[63:0]=accumulator[emit_lane]; end
            else begin
                sp_en[address_write%8]=1; sp_we[address_write%8]=1;
                sp_addr[(address_write%8)*13+:13]=13'(address_write/8); sp_wdata[(address_write%8)*16+:16]=result_word;
            end
        end
        if(state==EXP_REQ || state==PROB_REQ) begin row_en=1; row_addr=7'(item); end
        if(state==LUT_AREQ || state==LUT_BREQ) begin lut_read=1; table_index=13'(lut_node+int'(state==LUT_BREQ)); end
        if(state==LUT_WRITE&&op!=10) begin
            row_en=1; row_addr=7'(item); row_we=6'h30;
            row_wdata[95:64]=(lut_x< -1048576)?32'b0:lut_interpolated[31:0];
        end
        if(state==PROB_WRITE) begin
            row_en=1; row_addr=7'(item); row_we=6'h01; row_wdata[15:0]=probability;
            trace_valid=1; trace_stage=4; trace_index=15'(row*99+item); trace_data={48'b0,probability};
        end
        if(state==RES_WRITE || (state==LUT_WRITE&&op==10) || state==LN_WRITE) begin
            sp_en[address_write%8]=1; sp_we[address_write%8]=1;
            sp_addr[(address_write%8)*13+:13]=13'(address_write/8);
            sp_wdata[(address_write%8)*16+:16]=(state==LUT_WRITE)?sat(rne(gelu_value,20-int'(cfg[15]))):sat(scalar_result);
            trace_valid=1; trace_index=(state==LN_WRITE)?15'(row*64+feature):15'(item);
            trace_data=sx16(sp_wdata[(address_write%8)*16+:16]);
        end
        if(state==LN_LOADCAP) begin
            row_en=1; row_we=6'h01; row_addr=7'(feature); row_wdata[15:0]=sp_rdata[(address_a%8)*16+:16];
        end
        if(state==LN_VARREQ || state==LN_AREQ) begin row_en=1; row_addr=7'(feature); end
        if(state==LN_AREQ || state==LN_BREQ) begin
            pm_en[parameter_address%8]=1; pm_addr[(parameter_address%8)*13+:13]=13'(parameter_address/8);
        end
    end

    integer i;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=CLEAR; clear_index<=0; input_count<=0; parameter_count<=0; config_count<=0; exp_count<=0; gelu_count<=0;
            task_linear<=0; linear_shift_count<=0;
            layer_index<=0; op<=0; done<=0; error<=0; layer_done<=0; out_data<=0;
            row<=0; tile<=0; inner<=0; emit_lane<=0; bias_chunk<=0; item<=0; feature<=0;
            operand_a<=0; row_max<=0; lut_x<=0; lut_a<=0; lut_interpolated<=0; scalar_result<=0;
            x_hold<=0; probability<=0; exp_sum<=0; norm_sum<=0; norm_squares<=0; norm_denominator<=1;
            gamma_hold<=0; beta_hold<=0; divide_numerator<=0; divide_denominator<=1;
            for(i=0;i<8;i=i+1) begin accumulator[i]<=0; linear_shifts[i]<=0; end
            for(i=0;i<32;i=i+1) cfg[i]<=0;
        end else begin
            done<=0; layer_done<=0;
            if(loading) begin
                case(load_kind)
                    0: if(load_addr=={3'b0,input_count}&&input_count<6336) input_count<=input_count+1'b1; else error<=1;
                    1: if(load_addr==parameter_count&&parameter_count<parameter_words) parameter_count<=parameter_count+1'b1; else error<=1;
                    2: if(load_addr=={10'b0,config_count}&&config_count<32) begin cfg[config_count[4:0]]<=load_data; config_count<=config_count+1'b1; end else error<=1;
                    5: if(task_linear&&load_addr=={8'b0,linear_shift_count}&&linear_shift_count<128) linear_shift_count<=linear_shift_count+1'b1; else error<=1;
                    3: if(load_addr=={2'b0,exp_count}&&exp_count<8194) exp_count<=exp_count+1'b1; else error<=1;
                    4: if(load_addr=={2'b0,gelu_count}&&gelu_count<8194) gelu_count<=gelu_count+1'b1; else error<=1;
                    default: error<=1;
                endcase
            end
            case(state)
                CLEAR: begin
                    input_count<=0; parameter_count<=0; config_count<=0; exp_count<=0; gelu_count<=0; linear_shift_count<=0;
                    if(clear_index==8193) begin clear_index<=0; state<=IDLE; end else clear_index<=clear_index+1'b1;
                end
                IDLE: if(start_valid) begin
                    error<=0;
                    if(input_count!=6336||(!linear_mode&&(exp_count!=8194||gelu_count!=8194))) begin error<=1; done<=1; end
                    else begin task_linear<=linear_mode; layer_index<=0; parameter_count<=0; config_count<=0; linear_shift_count<=0; state<=WAIT_LAYER; end
                end
                WAIT_LAYER: if(layer_start_valid&&layer_start_ready) begin
                    if(!task_linear&&!config_legal) begin error<=1; done<=1; state<=CLEAR; end
                    else begin op<=task_linear?4'd9:4'd0; row<=0; tile<=0; state<=MAC_INIT; end
                end
                MAC_INIT: begin
                    if(op==3||op==5) begin
                        for(i=0;i<8;i=i+1) accumulator[i]<=0;
                        inner<=0; state<=A_REQ;
                    end else begin bias_chunk<=0; state<=BIAS_REQ; end
                end
                BIAS_REQ: state<=BIAS_CAP;
                BIAS_CAP: begin
                    if(task_linear) begin
                        linear_shifts[bias_chunk*2]<=$signed(row_rdata[7:0]);
                        linear_shifts[bias_chunk*2+1]<=$signed(row_rdata[15:8]);
                    end
                    accumulator[bias_chunk*2]<=$signed(pm_rdata[63:0]);
                    accumulator[bias_chunk*2+1]<=$signed(pm_rdata[127:64]);
                    if(bias_chunk==3) begin inner<=0; state<=A_REQ; end
                    else begin bias_chunk<=bias_chunk+1; state<=BIAS_REQ; end
                end
                A_REQ: state<=(FAST_MAC&&dense_mac)?B_MAC:A_CAP;
                A_CAP: begin
                    operand_a<=(op==5)?$signed({1'b0,row_rdata[15:0]}):$signed({sp_rdata[(address_a%8)*16+15],sp_rdata[(address_a%8)*16+:16]});
                    state<=FAST_MAC?B_MAC:B_REQ;
                end
                B_REQ: state<=B_MAC;
                B_MAC: begin
                    for(i=0;i<8;i=i+1) accumulator[i]<=accumulator[i]+64'(mac_a*$signed((op==3||op==5)?sp_rdata[i*16+:16]:pm_rdata[i*16+:16]));
                    if(inner==depth-1) begin emit_lane<=0; state<=EMIT; end
                    else begin inner<=inner+1; state<=A_REQ; end
                end
                EMIT: begin
                    if(op==3&&tile*8+emit_lane<99&&accumulator[emit_lane]>row_max) row_max<=accumulator[emit_lane];
                    if(emit_lane<7) emit_lane<=emit_lane+1;
                    else if(tile<(columns+7)/8-1) begin tile<=tile+1; state<=MAC_INIT; end
                    else begin
                        tile<=0;
                        if(op==3) begin item<=0; exp_sum<=0; state<=EXP_REQ; end
                        else if(op==5) begin
                            if(row<98) begin row<=row+1; op<=3; row_max<=64'sh8000000000000000; state<=MAC_INIT; end
                            else begin row<=0; op<=6; state<=MAC_INIT; end
                        end else if(row<98) begin row<=row+1; state<=MAC_INIT; end
                        else begin
                            row<=0;
                            case(op)
                                0: begin op<=1; state<=MAC_INIT; end
                                1: begin op<=2; state<=MAC_INIT; end
                                2: begin op<=3; row_max<=64'sh8000000000000000; state<=MAC_INIT; end
                                6: begin op<=7; item<=0; state<=RES_AREQ; end
                                9: begin item<=0; if(task_linear) begin layer_done<=1; state<=OUT_REQ; end else begin op<=10; state<=GELU_REQ; end end
                                11: begin op<=12; item<=0; state<=RES_AREQ; end
                                default: begin error<=1; done<=1; state<=CLEAR; end
                            endcase
                        end
                    end
                end
                EXP_REQ: state<=EXP_CAP;
                EXP_CAP: begin lut_x<=rne($signed(row_rdata[63:0])-row_max,int'(cfg[7])+int'(cfg[8])+3-16); state<=LUT_AREQ; end
                LUT_AREQ: state<=LUT_ACAP;
                LUT_ACAP: begin lut_a<=lut_b; state<=LUT_BREQ; end
                LUT_BREQ: state<=LUT_BCAP;
                LUT_BCAP: begin lut_interpolated<=lut_value; state<=LUT_WRITE; end
                LUT_WRITE: begin
                    if(op==10) begin
                        if(item==25343) begin op<=11; row<=0; tile<=0; state<=MAC_INIT; end
                        else begin item<=item+1; state<=GELU_REQ; end
                    end else begin
                        exp_sum<=exp_sum+((lut_x< -1048576)?64'd0:$unsigned(lut_interpolated));
                        if(item==98) begin item<=0; state<=PROB_REQ; end
                        else begin item<=item+1; state<=EXP_REQ; end
                    end
                end
                PROB_REQ: state<=PROB_CAP;
                PROB_CAP: begin divide_numerator<=$signed({32'b0,row_rdata[95:64]})<<<15; divide_denominator<=exp_sum; state<=PROB_START; end
                PROB_START: state<=PROB_WAIT;
                PROB_WAIT: if(div_done) begin
                    if(div_error) begin error<=1; done<=1; state<=CLEAR; end
                    else begin probability<=divide_result[15:0]; state<=PROB_WRITE; end
                end
                PROB_WRITE: if(item==98) begin op<=5; tile<=0; state<=MAC_INIT; end else begin item<=item+1; state<=PROB_REQ; end
                RES_AREQ: state<=RES_ACAP;
                RES_ACAP: begin x_hold<=sp_rdata[(address_a%8)*16+:16]; state<=RES_BREQ; end
                RES_BREQ: state<=RES_BCAP;
                RES_BCAP: begin scalar_result<=rne(res_total,common_f-res_out_f); state<=RES_WRITE; end
                RES_WRITE: if(item==6335) begin
                    op<=(op==7)?4'd8:4'd13; row<=0; feature<=0; norm_sum<=0; norm_squares<=0; state<=LN_LOADREQ;
                end else begin item<=item+1; state<=RES_AREQ; end
                GELU_REQ: state<=GELU_CAP;
                GELU_CAP: begin x_hold<=sp_rdata[(address_a%8)*16+:16]; lut_x<=rne(sx16(sp_rdata[(address_a%8)*16+:16]),int'(cfg[14])-16); state<=LUT_AREQ; end
                LN_LOADREQ: state<=LN_LOADCAP;
                LN_LOADCAP: begin
                    norm_sum<=norm_sum+sx16(sp_rdata[(address_a%8)*16+:16]);
                    if(feature==63) begin feature<=0; state<=LN_VARREQ; end
                    else begin feature<=feature+1; state<=LN_LOADREQ; end
                end
                LN_VARREQ: state<=LN_VARCAP;
                LN_VARCAP: begin
                    norm_squares<=norm_squares+centered_square;
                    if(feature==63) state<=LN_SQRT_GO;
                    else begin feature<=feature+1; state<=LN_VARREQ; end
                end
                LN_SQRT_GO: state<=LN_SQRT_WAIT;
                LN_SQRT_WAIT: if(sqrt_done) begin
                    if(sqrt_result==0) begin error<=1; done<=1; state<=CLEAR; end
                    else begin norm_denominator<=sqrt_result; feature<=0; state<=LN_AREQ; end
                end
                LN_AREQ: state<=LN_ACAP;
                LN_ACAP: begin
                    gamma_hold<=pm_rdata[(parameter_address%8)*16+:16]; divide_numerator<=centered<<<31; divide_denominator<=norm_denominator; state<=LN_BREQ;
                end
                LN_BREQ: state<=LN_BCAP;
                LN_BCAP: begin beta_hold<=pm_rdata[(parameter_address%8)*16+:16]; state<=LN_DIVWAIT; end
                LN_DIVWAIT: if(div_done) begin
                    if(div_error) begin error<=1; done<=1; state<=CLEAR; end
                    else begin scalar_result<=rne(affine,20+norm_gamma_f-norm_output_f); state<=LN_WRITE; end
                end
                LN_WRITE: if(feature<63) begin feature<=feature+1; state<=LN_AREQ; end
                else if(row<98) begin row<=row+1; feature<=0; norm_sum<=0; norm_squares<=0; state<=LN_LOADREQ; end
                else if(op==8) begin op<=9; row<=0; tile<=0; state<=MAC_INIT; end
                else state<=LAYER_DONE;
                LAYER_DONE: begin
                    layer_done<=1;
                    if(layer_index==11) begin item<=0; state<=OUT_REQ; end
                    else begin layer_index<=layer_index+1'b1; parameter_count<=0; config_count<=0; state<=WAIT_LAYER; end
                end
                OUT_REQ: state<=OUT_CAP;
                OUT_CAP: begin out_data<=sp_rdata[(address_a%8)*16+:16]; state<=OUT_HOLD; end
                OUT_HOLD: if(out_ready) begin
                    if(item==(task_linear?25343:6335)) begin
                        done<=1; input_count<=0; parameter_count<=0; config_count<=0; exp_count<=0; gelu_count<=0; clear_index<=0; state<=CLEAR;
                    end else begin item<=item+1; state<=OUT_REQ; end
                end
                default: begin error<=1; done<=1; state<=CLEAR; end
            endcase
        end
    end
endmodule
