// FFN implementation for independent storage, transport and scheduling ablations.
module kwt_encoder #(
    parameter integer SPLIT_BIAS=1, FAST_PAIR=1, OVERLAP=0, LANES=16, CLOCK_GATING=1
)(
    input wire clk,rst_n,clock_test_enable,linear_mode,load_valid,load_pair,
    output wire load_ready,load_capacity_ready,input_pair_capacity_ready,
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
    localparam integer TILES=16,GROUPS=1,MAC_LANES=64,MAC_COLUMNS=16;
    localparam [4:0] CLEAR=0,IDLE=1,WAIT_LAYER=2,MAC_INIT=3,BIAS_REQ=4,BIAS_CAP=5,
        A_REQ=6,B_MAC=7,EMIT=8,ROW1_MAC=9,B_FILL=10,ADVANCE=14,WAIT_INPUT=15,DRAIN=12;
    reg [4:0] state;
    reg [13:0] clear_index;
    reg [12:0] input_count;
    reg [14:0] parameter_count;
    reg [7:0] shift_count;
    reg [6:0] row;
    reg [2:0] chunk;
    reg [14:0] item;
    // Full input groups pack four rows; the last group packs three.
    reg [8:0] input_write_cursor;
    reg input_read_generation;
    function automatic [8:0] advance_input_cursor(input [8:0] cursor,input tail);
        reg [6:0] index;
        begin
            index = cursor[8:2];
            if(cursor[1:0]==(tail?2'd2:2'd3)) advance_input_cursor={index+7'd1,2'd0};
            else advance_input_cursor={index,cursor[1:0]+2'd1};
        end
    endfunction
    wire [8:0] input_high_cursor=advance_input_cursor(input_write_cursor,input_count>=13'd6144);
    wire [13:0] input_window_limit=(14'({1'b0,row})+14'd8)<<6;
    integer address,bank_index,b,k,offset;
    localparam integer mac_group=0,emit_group=0;
    wire [2:0] block_rows=(row==7'd96)?3'd3:3'd4;
    wire loading=load_valid&&load_ready;
    wire [1:0] load_count=(FAST_PAIR&&load_pair&&load_kind!=5)?2:1;
    wire input_complete={1'b0,input_count}>=((14'({1'b0,row})+14'(block_rows))<<6);
    reg signed [35:0] accumulator[0:MAC_LANES-1];
    reg signed [7:0] shifts[0:MAC_LANES-1];
    wire [1:0] pop_count;
    localparam IW_FUSED=1'b1;
    // Command fields are MAC valid, emit valid, tile and inner. The four
    // quartets see the same schedule, one edge apart. Read -> capture -> MAC.
    reg [3:0] iw_request_tile;
    reg [6:0] iw_request_inner;
    reg iw_request_done;
    reg [11:0] iw_pipe[0:4];
    wire iw_first=(state==A_REQ)&&input_complete;
    wire iw_second=state==B_FILL;
    wire iw_run=(state==B_MAC)&&!iw_request_done;
    wire iw_issue_mac=iw_first||iw_second||(iw_run&&iw_request_inner<64);
    wire iw_issue_emit=iw_run&&(iw_request_inner==64||
        (IW_FUSED&&iw_request_inner==0&&iw_request_tile!=0));
    wire [3:0] iw_issue_tile=(iw_first||iw_second)?4'd0:iw_request_tile;
    wire [5:0] request_inner=iw_first?6'd0:iw_second?6'd1:iw_request_inner[5:0];
    wire [11:0] iw_issue={iw_issue_mac,iw_issue_emit,iw_issue_tile,request_inner};
    wire [3:0] iw_mac_valid,iw_emit_valid,iw_capture;
    wire [3:0] iw_mac_tile[0:3],iw_emit_tile[0:3];
    wire [5:0] iw_mac_inner[0:3];
    wire [3:0] iw_weight_read;
    wire [12:0] iw_weight_address[0:3];
    wire [5:0] inner=iw_mac_inner[0];
    wire [3:0] tile=iw_emit_valid[0]?iw_emit_tile[0]:iw_emit_valid[1]?iw_emit_tile[1]:
                    iw_emit_valid[2]?iw_emit_tile[2]:iw_emit_valid[3]?iw_emit_tile[3]:iw_mac_tile[0];
    wire [3:0] lane={iw_emit_valid[3]||iw_emit_valid[2],iw_emit_valid[3]||iw_emit_valid[1],2'b00};
    wire emission=|iw_emit_valid;
    wire jp_quant_commit=emission;
    wire fifo_push=jp_quant_commit;
    wire output_generation_empty;
    wire output_reserve=(state==WAIT_INPUT)&&input_complete&&output_generation_empty;
    wire output_group_done=iw_emit_valid[3]&&(iw_emit_tile[3]==15);
    reg ap_er_next_seed_ready;
    wire ap_er_seed_wait=(state==MAC_INIT)&&ap_er_next_seed_ready;
    wire ap_er_has_next=(row<96)||(iw_mac_tile[0]<15);
    wire ap_er_first_request=iw_mac_valid[0]&&(inner==55)&&ap_er_has_next;
    wire ap_er_next_request=iw_mac_valid[0]&&(inner>=56)&&(inner<63)&&ap_er_has_next;
    wire ap_er_request=ap_er_first_request||ap_er_next_request;
    wire ap_er_reseed=jp_quant_commit&&((row<96)||(tile<15));
    wire [3:0] ap_er_target_tile=ap_er_reseed?tile+4'd1:iw_mac_tile[0]+4'd1;
    wire [2:0] ap_er_request_pair=inner[2:0]+3'd1;
    wire [3:0] ap_bias_tile=ap_er_request?ap_er_target_tile:4'd0;
    wire [2:0] ap_bias_pair=ap_er_request?ap_er_request_pair:chunk;
    wire bias_request=(state==BIAS_REQ)||ap_er_request;
    wire bias_capture=state==BIAS_CAP;
    wire pf2_capture=iw_emit_valid[3]&&(iw_emit_tile[3]<15);
    wire [MAC_LANES-1:0] jp_seed_mask,jp_mac_mask,jp_quant_mask;
    function automatic [5:0] ap_gray6(input [5:0] value);
        begin ap_gray6=value^(value>>1);end
    endfunction
    genvar wave_q;
    generate for(wave_q=0;wave_q<4;wave_q=wave_q+1)begin: wave_schedule
        wire [11:0] req;
        if(wave_q==0)assign req=iw_issue;
        else assign req=iw_pipe[wave_q-1];
        wire [11:0] execute=iw_pipe[wave_q+1];
        assign iw_weight_read[wave_q]=req[11];
        assign iw_weight_address[wave_q]={3'b000,ap_gray6(req[5:0]),req[9:6]};
        assign iw_capture[wave_q]=iw_pipe[wave_q][11];
        assign iw_mac_valid[wave_q]=execute[11];
        assign iw_emit_valid[wave_q]=execute[10];
        assign iw_mac_tile[wave_q]=execute[9:6];
        assign iw_mac_inner[wave_q]=execute[5:0];
        assign iw_emit_tile[wave_q]=execute[11]?execute[9:6]-4'd1:execute[9:6];
    end endgenerate
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            iw_request_tile<=0;iw_request_inner<=0;iw_request_done<=0;
            ap_er_next_seed_ready<=0;
            for(integer d=0;d<5;d=d+1)iw_pipe[d]<=0;
        end else begin
            iw_pipe[0]<=iw_issue;
            for(integer d=1;d<5;d=d+1)iw_pipe[d]<=iw_pipe[d-1];
            if(layer_start_valid&&layer_start_ready)ap_er_next_seed_ready<=0;
            else if(ap_er_seed_wait)ap_er_next_seed_ready<=0;
            else if(output_group_done&&row<96)ap_er_next_seed_ready<=1;
            if(iw_second)begin
                iw_request_tile<=0;iw_request_inner<=2;iw_request_done<=0;
            end else if(iw_run)begin
                if(iw_request_inner==64)begin
                    if(iw_request_tile==15)iw_request_done<=1;
                    else begin iw_request_tile<=iw_request_tile+4'd1;iw_request_inner<=0;end
                end else if(IW_FUSED&&iw_request_inner==63&&iw_request_tile<15)begin
                    iw_request_tile<=iw_request_tile+4'd1;iw_request_inner<=0;
                end else iw_request_inner<=iw_request_inner+7'd1;
            end
        end
    end
    wire [15:0] bias_address=16'(int'(ap_bias_tile)*64+int'(ap_bias_pair)*8);
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
    wire input_loading=loading&&(load_kind==0)&&(load_addr==16'(input_count));
    wire ap_input_read=iw_issue_mac;
    wire [63:0] ap_input_rdata;
    reg [255:0] jp_input_return;
    reg [16*LANES-1:0] operand_weight;
    generate for(genvar qw=0;qw<4;qw=qw+1)begin: wave_weight_stage
        wire operand_weight_clk;
        kwt_ffn_clock_gate weight_stage_gate(.clk(clk),.enable(iw_capture[qw]),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(operand_weight_clk));
        always @(posedge operand_weight_clk)if(iw_capture[qw])operand_weight[qw*64+:64]<=pm_rdata[qw*64+:64];
    end endgenerate
    generate for(genvar ap_row=0;ap_row<4;ap_row=ap_row+1)begin: ap_input_rows
        wire [31:0] generation_data;
        wire row_valid=3'(ap_row)<block_rows;
        assign ap_input_rdata[ap_row*16+:16]=generation_data[input_read_generation*16+:16];
        for(genvar gen=0;gen<2;gen=gen+1)begin: generations
            wire low_write=input_loading&&(input_write_cursor[8]==1'(gen))&&(input_write_cursor[1:0]==2'(ap_row));
            wire high_write=input_loading&&(load_count==2)&&(input_high_cursor[8]==1'(gen))&&(input_high_cursor[1:0]==2'(ap_row));
            wire write_enable=low_write||high_write;
            wire read_enable=ap_input_read&&row_valid&&(input_read_generation==1'(gen));
            wire memory_enable=write_enable||read_enable;
            wire [5:0] offset=write_enable?(high_write?input_high_cursor[7:2]:input_write_cursor[7:2]):request_inner;
            wire memory_clk;
            kwt_ffn_clock_gate gate(.clk(clk),.enable(memory_enable),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
            kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(memory_enable),.we(write_enable),
                .addr({1'b0,offset}),.wdata(high_write?load_high:load_data),.rdata(generation_data[gen*16+:16]));
        end
        for(genvar cp_copy=0;cp_copy<4;cp_copy=cp_copy+1)begin: return_copies
            wire lp_return_clock;
            wire capture_row=iw_capture[cp_copy]&&row_valid;
            wire [15:0] capture_value;
            if(cp_copy==0)assign capture_value=ap_input_rdata[ap_row*16+:16];
            else assign capture_value=jp_input_return[(ap_row*4+cp_copy-1)*16+:16];
            kwt_ffn_clock_gate return_gate(.clk(clk),.enable(capture_row),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(lp_return_clock));
            always @(posedge lp_return_clock)if(capture_row)
                jp_input_return[(ap_row*4+cp_copy)*16+:16]<=capture_value;
        end
    end endgenerate
    reg [15:0] jp_shift_return;
    always_latch if(!clk)jp_shift_return=shift_rdata;
    wire q16_shadow_capture=iw_mac_valid[0]&&(inner>=56)&&ap_er_has_next;
    reg [79:0] q16_seed_shadow[0:7];
    generate for(genvar pair_id=0;pair_id<8;pair_id=pair_id+1)begin: q16_shadow_pairs
        wire write_shadow=q16_shadow_capture&&(inner[2:0]==3'(pair_id));
        wire shadow_clk;
        if(CLOCK_GATING) begin: gated
            kwt_ffn_clock_gate gate(.clk(clk),.enable(write_shadow),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(shadow_clk));
        end else assign shadow_clk=clk;
        always @(posedge shadow_clk) if(write_shadow)
            q16_seed_shadow[pair_id]<={jp_shift_return,bias_rdata};
    end endgenerate
    wire [255:0] quant_words;
    generate for(genvar qr=0;qr<4;qr=qr+1)begin: quant_rows
        for(genvar qc=0;qc<4;qc=qc+1)begin: quant_columns
            wire active=jp_quant_commit&&(3'(qr)<block_rows);
            wire [35:0] value;
            wire [7:0] scale;
            wire [3:0] select_quartet;
            for(genvar q=0;q<4;q=q+1)begin: select_input
                assign select_quartet[q]=active&&(lane[3:2]==2'(q));
            end
            assign value=({36{select_quartet[0]}}&accumulator[qr*16+qc]) |
                         ({36{select_quartet[1]}}&accumulator[qr*16+qc+4]) |
                         ({36{select_quartet[2]}}&accumulator[qr*16+qc+8]) |
                         ({36{select_quartet[3]}}&accumulator[qr*16+qc+12]);
            assign scale=({8{select_quartet[0]}}&shifts[qr*16+qc]) |
                         ({8{select_quartet[1]}}&shifts[qr*16+qc+4]) |
                         ({8{select_quartet[2]}}&shifts[qr*16+qc+8]) |
                         ({8{select_quartet[3]}}&shifts[qr*16+qc+12]);
            kwt_ffn_requantize quantizer(.value({{28{value[35]}},value}),.shift(scale),
                .result(quant_words[(qr*4+qc)*16+:16]));
        end
    end endgenerate
    kwt_joint_output_queue output_queue(.clk(clk),.rst_n(rst_n),.clock_test_enable(clock_test_enable),
        .restart(layer_start_valid&&layer_start_ready),.reserve(output_reserve),.compute_generation(input_read_generation),
        .group_done(output_group_done),.commit(jp_quant_commit),.valid_rows(block_rows),
        .write_address({tile,lane[3:2]}),.write_words(quant_words),.generation_empty(output_generation_empty),
        .item(item),.out_ready(out_ready),.out_pair_ready(out_pair_ready),.out_valid(out_valid),
        .out_pair_valid(out_pair_valid),.out_data(out_data),.out_high(out_high),.pop_count(pop_count));
    generate for(genvar jp_lane=0;jp_lane<MAC_LANES;jp_lane=jp_lane+1)begin: jp_mac_lanes
        localparam integer jp_row=jp_lane/MAC_COLUMNS;
        localparam integer jp_column=jp_lane%MAC_COLUMNS;
        wire row_valid=3'(jp_row)<block_rows;
        wire next_row_valid=(jp_row!=3)||((tile==15)?(row<7'd92):row_valid);
        wire seed_update=(row_valid&&bias_capture&&(chunk==3'(jp_column/2)))||
            (next_row_valid&&ap_er_reseed&&(lane[3:2]==2'(jp_column/4)));
        wire signed [31:0] seed_bias=ap_er_reseed?
            q16_seed_shadow[jp_column/2][(jp_column%2)*32+:32]:bias_rdata[(jp_column%2)*32+:32];
        wire signed [7:0] seed_shift=ap_er_reseed?
            q16_seed_shadow[jp_column/2][64+(jp_column%2)*8+:8]:jp_shift_return[(jp_column%2)*8+:8];
        wire mac_update=iw_mac_valid[jp_column/4]&&row_valid;
        wire quant_commit=jp_quant_commit&&row_valid&&(lane[3:2]==2'(jp_column/4));
        assign jp_seed_mask[jp_lane]=seed_update;
        assign jp_mac_mask[jp_lane]=mac_update;
        assign jp_quant_mask[jp_lane]=quant_commit;
        wire signed [16:0] activation=$signed(jp_input_return[(jp_row*4+jp_column/4)*16+:16]);
        wire signed [15:0] weight_value=$signed(operand_weight[jp_column*16+:16]);
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
        always @(posedge accumulator_clk)begin
            if(mac_update)accumulator[jp_lane]<=
                (seed_update?36'(seed_bias):accumulator[jp_lane])+36'(activation*weight_value);
            else if(seed_update)accumulator[jp_lane]<=36'(seed_bias);
        end
        always @(posedge shift_register_clk)begin
            if(seed_update)shifts[jp_lane]<=seed_shift;
        end
    end endgenerate
    assign start_ready=state==IDLE;
    assign layer_request=state==WAIT_LAYER;
    assign layer_start_ready=layer_request&&(parameter_count==16896)&&(shift_count==128);
    assign load_capacity_ready=(((state==WAIT_LAYER)&&((load_kind==1)||(load_kind==5)))||
         ((load_kind==0)&&((!STREAM_INPUT&&(state==IDLE))||(STREAM_INPUT&&(state>=3)&&(input_count<6336)&&
             ({1'b0,input_count}<input_window_limit)))));
    assign input_pair_capacity_ready=(input_count<6335)&&
        (({1'b0,input_count}+14'd1)<input_window_limit);
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
                    bank_index=address%BIAS_BANKS;bias_en[bank_index]=1;bias_we[bank_index]=1;
                    bias_addr[bank_index*7+:7]=7'(address/BIAS_BANKS);bias_wdata[bank_index*16+:16]=k==0?load_data:load_high;
                end
            end
            if(load_kind==5) begin shift_en=1;shift_we=1;shift_addr=load_addr[6:0];shift_wdata=load_data;end
        end
        for(b=0;b<LANES;b=b+1)if(iw_weight_read[b/4])begin
            pm_en[b]=1;pm_addr[b*13+:13]=iw_weight_address[b/4];
        end
        if(bias_request) begin
            bias_en='1;
            for(b=0;b<BIAS_BANKS;b=b+1) bias_addr[b*7+:7]=7'(BIAS32?(int'(ap_bias_tile)*8+int'(ap_bias_pair)):(int'(bias_address)/BIAS_BANKS));
            shift_en=1;shift_addr=7'(int'(ap_bias_tile)*8+int'(ap_bias_pair));
        end
    end
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            state<=CLEAR;clear_index<=0;input_count<=0;parameter_count<=0;shift_count<=0;
            row<=0;chunk<=0;item<=0;
            input_write_cursor<=0;input_read_generation<=0;
            done<=0;error<=0;layer_done<=0;
        end else begin
            done<=0;layer_done<=0;
            if(loading)case(load_kind)
                0:if(load_addr==16'(input_count)&&input_count<6336)begin
                    input_count<=input_count+13'(load_count);
                    input_write_cursor<=(load_count==2)?
                        advance_input_cursor(input_high_cursor,input_count>=13'd6143):input_high_cursor;
                end else error<=1;
                1:if(load_addr==16'(parameter_count)&&parameter_count<16896)parameter_count<=parameter_count+15'(load_count);else error<=1;
                5:if(load_addr==16'(shift_count)&&shift_count<128)shift_count<=shift_count+1'b1;else error<=1;
            endcase
            case(state)
                CLEAR:begin clear_index<=0;state<=IDLE;end
                IDLE:if(start_valid)begin
                    error<=0;if(!linear_mode)begin error<=1;done<=1;end
                    else begin parameter_count<=0;shift_count<=0;state<=WAIT_LAYER;end
                end
                WAIT_LAYER:if(layer_start_valid&&layer_start_ready)begin
                    row<=0;item<=0;state<=WAIT_INPUT;
                    input_write_cursor<=0;input_read_generation<=0;
                end
                WAIT_INPUT:if(output_reserve)state<=MAC_INIT;
                MAC_INIT:begin chunk<=0;if(ap_er_next_seed_ready)state<=A_REQ;else state<=BIAS_REQ;end
                BIAS_REQ:state<=BIAS_CAP;
                BIAS_CAP:if(chunk==7)state<=A_REQ;else begin chunk<=chunk+1'b1;state<=BIAS_REQ;end
                A_REQ:if(input_complete)state<=B_FILL;
                B_FILL:state<=B_MAC;
                B_MAC:if(output_group_done)state<=ADVANCE;
                ADVANCE:if(row==96)begin layer_done<=1;state<=DRAIN;end
                    else begin row<=row+7'd4;input_read_generation<=!input_read_generation;state<=WAIT_INPUT;end
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
