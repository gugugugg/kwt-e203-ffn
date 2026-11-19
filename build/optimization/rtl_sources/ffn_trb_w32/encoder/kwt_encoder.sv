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
    output wire layer_start_ready,busy,prologue_config_ready,
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
        A_REQ=6,B_MAC=7,EMIT=8,ROW1_MAC=9,B_FILL=10,ADVANCE=14,WAIT_INPUT=15,DRAIN=12,WP_BOOT=16;
    reg [4:0] state;
    reg [13:0] clear_index;
    reg [12:0] input_count;
    reg [1:0] w32_input_ready;
    reg [7:0] w32_seed_captured;
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
    wire input_complete=w32_input_ready[input_read_generation]&&{1'b0,input_count}>=((14'({1'b0,row})+14'(block_rows))<<6);
    reg signed [35:0] accumulator[0:MAC_LANES-1];
    reg signed [7:0] shifts[0:MAC_LANES-1];
    wire [1:0] pop_count;
    localparam IW_FUSED=1'b1;
    // Command fields are MAC valid, emit valid, tile and inner. The four
    // quartets see the same schedule, one edge apart. Read -> capture -> MAC.
    reg [3:0] iw_request_tile;
    reg [6:0] iw_request_inner;
    reg iw_request_done;
    reg [13:0] iw_pipe[0:4];
    // Each batch contains 256 committed weight halfwords in four banks.
    // Two input generations use that batch before advancing to the next quartet.
    wire wp_boot=state==WP_BOOT;
    reg [14:0] wp_weight_count;
    reg [13:0] wp_count;
    reg [1:0] wp_reserved;
    wire [3:0] wp_tile=wp_count[12:9];
    wire [1:0] wp_quartet=wp_count[8:7];
    wire wp_generation=wp_count[6];
    wire [5:0] wp_k=wp_count[5:0];
    wire wp_issue=wp_boot&&wp_reserved==2&&!wp_count[13]&&
                  wp_weight_count[14:8]>{1'b0,wp_tile,wp_quartet}&&
                  w32_seed_captured>={1'b0,wp_tile,wp_quartet,1'b0}+8'd2;
    wire [12:0] wp_weight_address={3'b000,ap_gray6(wp_k),wp_tile};
    reg [13:0] wp_capture_token,wp_execute_token;
    reg [7:0] wp_emit_token;
    wire wp_capture=wp_capture_token[13];
    wire wp_execute=wp_execute_token[13];
    wire wp_emit=wp_emit_token[7];
    wire wp_emit_generation=wp_emit_token[6];
    wire wp_reserve=wp_boot&&wp_reserved!=2;
    wire wp_weight_conflict=wp_issue&&
        (wp_weight_count[9:8]==wp_quartet||
         (wp_weight_count[7:0]==8'hff&&wp_weight_count[9:8]+2'd1==wp_quartet));
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            wp_count<=0;wp_reserved<=0;
            wp_capture_token<=0;wp_execute_token<=0;wp_emit_token<=0;
        end else if(layer_start_valid&&layer_start_ready)begin
            wp_count<=0;wp_reserved<=0;
            wp_capture_token<=0;wp_execute_token<=0;wp_emit_token<=0;
        end else if(wp_boot)begin
            wp_capture_token<={wp_issue,wp_count[12:0]};
            wp_execute_token<=wp_capture_token;
            wp_emit_token<={wp_execute&&wp_execute_token[5:0]==63,
                           wp_execute_token[6],wp_execute_token[12:9],wp_execute_token[8:7]};
            if(wp_issue)wp_count<=wp_count+1'b1;
            if(wp_reserve)wp_reserved<=wp_reserved+1'b1;
        end
    end
    wire iw_first=(state==A_REQ)&&input_complete;
    wire iw_second=state==B_FILL;
    wire reuse_block;
    wire iw_run=(state==B_MAC)&&!iw_request_done&&!reuse_block;
    wire next_generation_empty;
    reg iw_join_inflight,iw_join_first;
    wire [13:0] iw_next_input_end=(row==7'd92)?14'd6336:input_window_limit;
    wire iw_join=IW_FUSED&&iw_run&&!iw_join_inflight&&row<7'd96&&
                 iw_request_tile==4'd15&&iw_request_inner==7'd63&&
                 {1'b0,input_count}>=iw_next_input_end&&w32_input_ready[!input_read_generation]&&next_generation_empty;
    wire iw_request_generation=input_read_generation^iw_join_inflight;
    wire iw_request_tail=iw_join_inflight?(row==7'd92):(row==7'd96);
    // Use retired words at the start of the cycle, excluding held and pending.
    wire would_emit=(iw_request_inner==64)||
        (IW_FUSED&&iw_request_inner==0&&(iw_request_tile!=0||iw_join_first));
    wire retire_second=iw_join_first?(row==7'd12):
        (iw_join_inflight?(row==7'd8):(row==7'd12));
    wire retire_first=iw_join_first?(row==7'd8):
        (iw_join_inflight?(row==7'd4):(row==7'd8));
    wire [3:0] retire_tile=(iw_request_inner==64)?iw_request_tile:iw_request_tile-4'd1;
    wire old_slot_released=(item[14:10]>5'(retire_second))||
        (item[14:10]==5'(retire_second)&&item[9:6]>retire_tile);
    assign reuse_block=(state==B_MAC)&&would_emit&&(retire_first||retire_second)&&!old_slot_released;
    wire iw_issue_mac=iw_first||iw_second||(iw_run&&iw_request_inner<64);
    wire iw_issue_emit=iw_run&&(iw_request_inner==64||
        (IW_FUSED&&iw_request_inner==0&&(iw_request_tile!=0||iw_join_first)));
    wire [3:0] iw_issue_tile=(iw_first||iw_second)?4'd0:iw_request_tile;
    wire [5:0] request_inner=iw_first?6'd0:iw_second?6'd1:iw_request_inner[5:0];
    wire [13:0] iw_issue={iw_request_tail,iw_request_generation,
                          iw_issue_mac,iw_issue_emit,iw_issue_tile,request_inner};
    wire [3:0] iw_mac_valid,iw_emit_valid,iw_capture;
    wire [3:0] iw_mac_tail,iw_emit_tail,iw_capture_tail,iw_emit_generation,iw_mac_generation;
    wire quant_tail=|(iw_emit_valid&iw_emit_tail);
    wire [2:0] quant_valid_rows=quant_tail?3'd3:3'd4;
    wire quant_generation=|(iw_emit_valid&iw_emit_generation);
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
    wire ap_er_first_request=!wp_boot&&iw_mac_valid[0]&&(inner==55)&&ap_er_has_next;
    wire ap_er_next_request=!wp_boot&&iw_mac_valid[0]&&(inner>=56)&&(inner<63)&&ap_er_has_next;
    wire ap_er_request=ap_er_first_request||ap_er_next_request;
    wire ap_er_reseed=!wp_boot&&jp_quant_commit&&((row<96)||(tile<15));
    wire [3:0] ap_er_target_tile=ap_er_reseed?tile+4'd1:iw_mac_tile[0]+4'd1;
    wire [2:0] ap_er_request_pair=inner[2:0]+3'd1;
    wire [3:0] ap_bias_tile=ap_er_request?iw_mac_tile[0]+4'd1:4'd0;
    wire [2:0] ap_bias_pair=ap_er_request?ap_er_request_pair:chunk;
    wire bias_request=(state==BIAS_REQ)||ap_er_request;
    wire bias_capture=state==BIAS_CAP;
    wire pf2_capture=!wp_boot&&iw_emit_valid[3]&&(iw_emit_tile[3]<15);
    wire [MAC_LANES-1:0] jp_seed_mask,jp_mac_mask,jp_quant_mask;
    function automatic [5:0] ap_gray6(input [5:0] value);
        begin ap_gray6=value^(value>>1);end
    endfunction
    genvar wave_q;
    generate for(wave_q=0;wave_q<4;wave_q=wave_q+1)begin: wave_schedule
        wire [13:0] req;
        if(wave_q==0)assign req=iw_issue;
        else assign req=iw_pipe[wave_q-1];
        wire [13:0] execute=iw_pipe[wave_q+1];
        // The fused tile-zero token retires the preceding generation.
        wire fused_join=execute[11]&&execute[10]&&execute[9:6]==4'd0;
        assign iw_mac_tail[wave_q]=!wp_boot&&execute[13];
        assign iw_capture_tail[wave_q]=!wp_boot&&iw_pipe[wave_q][13];
        assign iw_mac_generation[wave_q]=wp_boot?wp_execute_token[6]:execute[12];
        reg [6:0] emit_capture,emit_delayed;
        wire raw_valid=wp_boot?(wp_emit&&wp_emit_token[1:0]==2'(wave_q)):execute[10];
        wire raw_tail=!wp_boot&&execute[13]&&!fused_join;
        wire raw_generation=wp_boot?wp_emit_generation:(execute[12]^fused_join);
        wire [3:0] raw_tile=wp_boot?wp_emit_token[5:2]:(execute[11]?execute[9:6]-4'd1:execute[9:6]);
        always @(posedge clk or negedge rst_n)begin
            if(!rst_n)begin emit_capture<=0;emit_delayed<=0;end
            else begin
                emit_capture<={raw_valid,raw_tail,raw_generation,raw_tile};
                emit_delayed<=emit_capture;
            end
        end
        assign {iw_emit_valid[wave_q],iw_emit_tail[wave_q],
                iw_emit_generation[wave_q],iw_emit_tile[wave_q]}=emit_delayed;
        assign iw_weight_read[wave_q]=wp_boot?(wp_issue&&wp_quartet==2'(wave_q)):req[11];
        assign iw_weight_address[wave_q]=wp_boot?wp_weight_address:{3'b000,ap_gray6(req[5:0]),req[9:6]};
        assign iw_capture[wave_q]=wp_boot?(wp_capture&&wp_capture_token[8:7]==2'(wave_q)):iw_pipe[wave_q][11];
        assign iw_mac_valid[wave_q]=wp_boot?(wp_execute&&wp_execute_token[8:7]==2'(wave_q)):execute[11];
        assign iw_mac_tile[wave_q]=wp_boot?wp_execute_token[12:9]:execute[9:6];
        assign iw_mac_inner[wave_q]=wp_boot?wp_execute_token[5:0]:execute[5:0];
    end endgenerate
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            iw_join_inflight<=0;
            iw_join_first<=0;
        end else begin
            if(!reuse_block)iw_join_first<=iw_join;
            if(layer_start_valid&&layer_start_ready)iw_join_inflight<=0;
            else if(iw_join)iw_join_inflight<=1;
            else if(!wp_boot&&output_group_done)iw_join_inflight<=0;
        end
    end
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
            else if(!wp_boot&&output_group_done&&row<96&&!iw_join_inflight)ap_er_next_seed_ready<=1;
            if(iw_second)begin
                iw_request_tile<=0;iw_request_inner<=2;iw_request_done<=0;
            end else if(iw_run)begin
                if(iw_request_inner==64)begin
                    if(iw_request_tile==15)iw_request_done<=1;
                    else begin iw_request_tile<=iw_request_tile+4'd1;iw_request_inner<=0;end
                end else if(IW_FUSED&&iw_request_inner==63&&(iw_request_tile<15||iw_join))begin
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
    wire ap_input_read=iw_issue_mac||wp_issue;
    wire input_request_generation=wp_boot?wp_generation:iw_request_generation;
    wire input_capture_generation=wp_boot?wp_capture_token[6]:iw_pipe[0][12];
    wire [5:0] input_request_inner=wp_boot?wp_k:request_inner;
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
        wire read_row=(ap_row!=3)||!iw_request_tail||wp_boot;
        assign ap_input_rdata[ap_row*16+:16]=generation_data[input_capture_generation*16+:16];
        for(genvar gen=0;gen<2;gen=gen+1)begin: generations
            wire low_write=input_loading&&(input_write_cursor[8]==1'(gen))&&(input_write_cursor[1:0]==2'(ap_row));
            wire high_write=input_loading&&(load_count==2)&&(input_high_cursor[8]==1'(gen))&&(input_high_cursor[1:0]==2'(ap_row));
            wire write_enable=low_write||high_write;
            wire read_enable=ap_input_read&&read_row&&(input_request_generation==1'(gen));
            wire memory_enable=write_enable||read_enable;
            wire [5:0] offset=write_enable?(high_write?input_high_cursor[7:2]:input_write_cursor[7:2]):input_request_inner;
            wire memory_clk;
            kwt_ffn_clock_gate gate(.clk(clk),.enable(memory_enable),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
            kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(memory_enable),.we(write_enable),
                .addr({1'b0,offset}),.wdata(high_write?load_high:load_data),.rdata(generation_data[gen*16+:16]));
        end
        for(genvar cp_copy=0;cp_copy<4;cp_copy=cp_copy+1)begin: return_copies
            wire lp_return_clock;
            wire capture_row=iw_capture[cp_copy]&&((ap_row!=3)||!iw_capture_tail[cp_copy]);
            wire [15:0] capture_value;
            if(cp_copy==0)assign capture_value=ap_input_rdata[ap_row*16+:16];
            else assign capture_value=wp_boot?ap_input_rdata[ap_row*16+:16]:jp_input_return[(ap_row*4+cp_copy-1)*16+:16];
            kwt_ffn_clock_gate return_gate(.clk(clk),.enable(capture_row),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(lp_return_clock));
            always @(posedge lp_return_clock)if(capture_row)
                jp_input_return[(ap_row*4+cp_copy)*16+:16]<=capture_value;
        end
    end endgenerate
    reg [15:0] jp_shift_return;
    always_latch if(!clk)jp_shift_return=shift_rdata;
    wire q16_shadow_capture=!wp_boot&&iw_mac_valid[0]&&(inner>=56)&&ap_er_has_next;
    // The same two correction lanes accept either an input beat or a weight beat.
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
    reg [7:0] w32_seed_requested;
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
    reg [79:0] q16_seed_shadow[0:7];
    generate for(genvar pair_id=0;pair_id<8;pair_id=pair_id+1)begin: q16_shadow_pairs
        wire write_shadow=(bias_capture&&chunk==3'(pair_id))||
            (q16_shadow_capture&&inner[2:0]==3'(pair_id));
        wire shadow_clk;
        if(CLOCK_GATING) begin: gated
            kwt_ffn_clock_gate gate(.clk(clk),.enable(write_shadow),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(shadow_clk));
        end else assign shadow_clk=clk;
        always @(posedge shadow_clk) if(write_shadow)
            q16_seed_shadow[pair_id]<={2'b00,w32_seed_word};
    end endgenerate
    wire [255:0] quant_words;
    generate for(genvar qr=0;qr<4;qr=qr+1)begin: quant_rows
        for(genvar qc=0;qc<4;qc=qc+1)begin: quant_columns
            wire active=jp_quant_commit&&(3'(qr)<quant_valid_rows);
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
        .restart(layer_start_valid&&layer_start_ready),.reserve(output_reserve||wp_reserve||iw_join),
        .query_generation(input_read_generation),.next_generation_empty(next_generation_empty),
        .reserve_generation(wp_boot?wp_reserved[0]:(input_read_generation^iw_join)),
        .compute_generation(quant_generation),.write_transposed(wp_boot),
        .query_reuse(row==7'd8||row==7'd12),.next_query_reuse(row==7'd4||row==7'd8),
        .group_done(output_group_done),.commit(jp_quant_commit),.valid_rows(quant_valid_rows),
        .write_address({tile,lane[3:2]}),.write_words(quant_words),.generation_empty(output_generation_empty),
        .item(item),.out_ready(out_ready),.out_pair_ready(out_pair_ready),.out_valid(out_valid),
        .out_pair_valid(out_pair_valid),.out_data(out_data),.out_high(out_high),.pop_count(pop_count));
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
    assign start_ready=state==IDLE;
    assign layer_request=state==WAIT_LAYER;
    assign layer_start_ready=layer_request&&(parameter_count==512)&&(shift_count==128)&&(input_count==512)&&(&w32_input_ready);
    assign prologue_config_ready=wp_boot||(state==WAIT_INPUT&&row==8);
    wire [13:0] active_input_limit=(layer_request||wp_boot)?14'd512:input_window_limit;
    assign load_capacity_ready=((state==WAIT_LAYER)&&
         ((load_kind==1&&parameter_count<512)||(load_kind==5&&shift_count<128)))||
         (wp_boot&&load_kind==1&&wp_weight_count<16384&&!wp_weight_conflict)||
         (load_kind==0&&(layer_request||state>=3)&&(input_count<6336)&&
          ({1'b0,input_count}<active_input_limit));
    assign input_pair_capacity_ready=(input_count<6335)&&
        (({1'b0,input_count}+14'd1)<active_input_limit);
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
                    bank_index=int'({address[9:8],address[1:0]});pm_en[bank_index]=1;pm_we[bank_index]=1;
                    pm_addr[bank_index*13+:13]={3'b000,ap_gray6(address[7:2]),address[13:10]};pm_wdata[bank_index*16+:16]=k==0?load_data:load_high;
                end else begin
                    address=address-16384;
                    bank_index=address%BIAS_BANKS;bias_en[bank_index]=1;bias_we[bank_index]=1;
                    bias_addr[bank_index*7+:7]=7'(address/BIAS_BANKS);bias_wdata[bank_index*16+:16]=k==0?load_data:load_high;
                end
            end
            if(load_kind==5) begin shift_en=1;shift_we=1;shift_addr=load_addr[6:0];shift_wdata={5'd0,w32_encode_shift(load_data[15:8]),5'd0,w32_encode_shift(load_data[7:0])};end
        end
        for(b=0;b<LANES;b=b+1)if(iw_weight_read[b/4])begin
            pm_en[b]=1;pm_addr[b*13+:13]=iw_weight_address[b/4];
        end
        if(w32_bias_write||w32_seed_read||w32_raw_read)begin
            bias_en='1;shift_en=1;
            for(b=0;b<BIAS_BANKS;b=b+1)bias_addr[b*7+:7]=w32_bias_address;
            shift_addr=w32_bias_address;
            if(w32_bias_write)begin
                bias_we='1;shift_we=1;
                bias_wdata={w32_bias_high[31:0],w32_bias_low[31:0]};
                shift_wdata={1'b0,w32_bias_high[35:32],w32_raw_pair[74:72],
                            1'b0,w32_bias_low[35:32],w32_raw_pair[66:64]};
            end
        end
        if(bias_request) begin
            bias_en='1;
            for(b=0;b<BIAS_BANKS;b=b+1) bias_addr[b*7+:7]=7'(BIAS32?(int'(ap_bias_tile)*8+int'(ap_bias_pair)):(int'(bias_address)/BIAS_BANKS));
            shift_en=1;shift_addr=7'(int'(ap_bias_tile)*8+int'(ap_bias_pair));
        end
    end
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            state<=CLEAR;clear_index<=0;input_count<=0;parameter_count<=0;shift_count<=0;wp_weight_count<=0;
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
                1:if(wp_boot&&load_addr==16'(wp_weight_count)&&wp_weight_count<16384)
                    wp_weight_count<=wp_weight_count+15'(load_count);
                else if(layer_request&&load_addr==16'd16384+16'(parameter_count)&&parameter_count<512)
                    parameter_count<=parameter_count+15'(load_count);
                else error<=1;
                5:if(load_addr==16'(shift_count)&&shift_count<128)shift_count<=shift_count+1'b1;else error<=1;
            endcase
            case(state)
                CLEAR:begin clear_index<=0;state<=IDLE;end
                IDLE:if(start_valid)begin
                    error<=0;if(!linear_mode)begin error<=1;done<=1;end
                    else begin parameter_count<=0;shift_count<=0;wp_weight_count<=0;state<=WAIT_LAYER;end
                end
                WAIT_LAYER:if(layer_start_valid&&layer_start_ready)begin
                    row<=0;item<=0;state<=WP_BOOT;input_read_generation<=0;
                end
                WP_BOOT:if(output_group_done&&quant_generation)begin
                    row<=8;state<=WAIT_INPUT;
                end
                WAIT_INPUT:if(output_reserve)state<=MAC_INIT;
                MAC_INIT:begin chunk<=0;if(ap_er_next_seed_ready)state<=A_REQ;else state<=BIAS_REQ;end
                BIAS_REQ:state<=BIAS_CAP;
                BIAS_CAP:if(chunk==7)state<=A_REQ;else begin chunk<=chunk+1'b1;state<=BIAS_REQ;end
                A_REQ:if(input_complete)state<=B_FILL;
                B_FILL:state<=B_MAC;
                B_MAC:if(output_group_done)begin
                    if(iw_join_inflight)begin
                        row<=row+7'd4;
                        input_read_generation<=!input_read_generation;
                    end else state<=ADVANCE;
                end
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
