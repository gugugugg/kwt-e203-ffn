"""Two rows by eight columns, fixed sixteen MACs and three output macros."""
from area_power_compute import _replace


def transform_wrapper(text):
    marker = '    assign pio_cmd_ready=slot_available&&!pack_pending&&!pair_wait&&'
    replacement = '''    wire jp_input_wait=!pio_cmd_read&&aligned&&(pio_cmd_wmask==4'hf)&&
        (load_kind==0)&&stream_mode&&core_busy&&!core_layer_request&&!core_error&&!done_sticky&&
        ((pio_cmd_addr==8'h10&&load_address<16'd6336)||
         (pio_cmd_addr==8'h30&&load_address<16'd6335))&&!dma_core_load_capacity_ready;
    assign pio_cmd_ready=slot_available&&!pack_pending&&!pair_wait&&!jp_input_wait&&'''
    return _replace(text, marker, replacement)


def transform_core(text, fine_gates=False):
    start = text.index('    localparam integer ROW_GROUP=')
    end = text.index('    wire prefetch=', start)
    text = text[:start] + '''    localparam integer ROW_GROUP=1,INPUT_SLOTS=2,STREAM_INPUT=1,
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
''' + text[end:]
    start = text.index('    wire prefetch=')
    end = text.index('    reg [7:0] sp_en', start)
    text = text[:start] + '''    wire prefetch=(state==B_MAC)&&(inner<63);
    wire [5:0] request_inner=6'({1'b0,inner}+7'(prefetch));
    function automatic [5:0] ap_gray6(input [5:0] value);
        begin ap_gray6=value^(value>>1);end
    endfunction
    wire [12:0] ap_weight_read_address={3'b000,ap_gray6(request_inner),tile[4:1]};
    wire [15:0] bias_address=16'(int'(ap_bias_tile)*32+int'(ap_bias_pair)*8);
''' + text[end:]
    start = text.index('    wire row_cache_ready=')
    end = text.index('    wire [35:0] quant_bits=', start)
    text = text[:start] + '''    wire row_cache_ready=input_complete;
    wire input_loading=loading&&(load_kind==0);
    wire ap_input_read=((state==A_REQ)&&row_cache_ready)||prefetch;
    wire [31:0] ap_input_rdata;
    generate for(genvar ap_row=0;ap_row<2;ap_row=ap_row+1)begin: ap_input_rows
        wire write_enable=input_loading&&(load_addr[6]==1'(ap_row));
        wire read_enable=ap_input_read&&((ap_row==0)||(row<98));
        wire memory_enable=write_enable||read_enable;
        wire [6:0] memory_addr=write_enable?{load_addr[7],load_addr[5:0]}:{row[1],request_inner};
        wire memory_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(memory_enable),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(memory_enable),.we(write_enable),
            .addr(memory_addr),.wdata(load_data),.rdata(ap_input_rdata[ap_row*16+:16]));
    end endgenerate
    reg [31:0] jp_input_return;
    reg [15:0] jp_shift_return;
    always_latch if(clk)jp_input_return<=ap_input_rdata;
    always_latch if(!clk)jp_shift_return=shift_rdata;
    wire [3:0] jp_quant_lane={emit_row,lane};
''' + text[end:]
    text = text.replace('accumulator[lane]', 'accumulator[jp_quant_lane]').replace('shifts[lane]', 'shifts[jp_quant_lane]')
    text = text.replace("{1'b0,lane}+5'd1", "{1'b0,jp_quant_lane}+5'd1")
    start = text.index('    wire stash_write=')
    end = text.index('    assign start_ready=', start)
    block = '''    kwt_joint_output_queue output_queue(.clk(clk),.rst_n(rst_n),.clock_test_enable(clock_test_enable),
        .restart(layer_start_valid&&layer_start_ready),.push_valid(emission),.push_row1(emit_row),
        .push_low(result_word),.push_high(tp_result_high),.push_ready(jp_quant_ready),.item(item),
        .out_ready(out_ready),.out_pair_ready(out_pair_ready),.out_valid(out_valid),.out_pair_valid(out_pair_valid),
        .out_data(out_data),.out_high(out_high),.pop_count(pop_count),.fifo_count(fifo_count));
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
        wire signed [16:0] activation=$signed(jp_input_return[jp_row*16+:16]);
        wire signed [15:0] weight_value=$signed(pm_rdata[(int'(tile[0])*8+jp_column)*16+:16]);
        wire accumulator_clk,shift_register_clk;
        JP_GATES
        always @(posedge accumulator_clk or negedge rst_n)begin
            if(!rst_n)accumulator[jp_lane]<=0;
            else if(seed_update)accumulator[jp_lane]<=36'($signed(bias_pair[(jp_column%2)*64+:64]));
            else if(mac_update)accumulator[jp_lane]<=accumulator[jp_lane]+36'(activation*weight_value);
        end
        always @(posedge shift_register_clk or negedge rst_n)begin
            if(!rst_n)shifts[jp_lane]<=0;
            else if(seed_update)shifts[jp_lane]<=$signed(jp_shift_return[(jp_column%2)*8+:8]);
        end
    end endgenerate
'''
    if fine_gates:
        gates = '''if(jp_column%2==0)begin: pair_gate
            kwt_ffn_clock_gate acc_gate(.clk(clk),.enable(mac_update||seed_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(accumulator_clk));
            kwt_ffn_clock_gate shift_gate(.clk(clk),.enable(seed_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(shift_register_clk));
        end else begin
            assign accumulator_clk=jp_mac_lanes[jp_lane-1].accumulator_clk;
            assign shift_register_clk=jp_mac_lanes[jp_lane-1].shift_register_clk;
        end'''
    else:
        # Match X's shared datapath-clock scope; the separate H mechanism is absent.
        gates = '''if(jp_lane==0)begin: shared_gate
            kwt_ffn_clock_gate gate(.clk(clk),.enable(bias_capture||(state==B_MAC)||jp_quant_commit),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(accumulator_clk));
        end else assign accumulator_clk=jp_mac_lanes[0].accumulator_clk;
        assign shift_register_clk=accumulator_clk;'''
    text = text[:start] + block.replace('JP_GATES', gates) + text[end:]
    text = _replace(text, "({1'b0,input_count}<((14'({1'b0,row})+14'd2)<<6))", "({1'b0,input_count}<((14'({1'b0,row})+14'd4)<<6))&&!ap_input_read")
    start = text.index('    assign out_valid=')
    end = text.index('    function automatic [12:0] ld_parameter_address', start)
    text = text[:start] + '''    assign out_index=item;
    assign trace_valid=pop_count!=0;
    assign trace_pair_valid=pop_count==2;
    assign trace_layer=0;assign trace_stage=9;
    assign trace_index=item;
    assign trace_data={{48{out_data[15]}},out_data};
    assign trace_high={{48{out_high[15]}},out_high};
''' + text[end:]
    text = _replace(text, "pm_en='1;for(b=0;b<LANES;b=b+1) pm_addr[b*13+:13]=ap_weight_read_address;",
                    "for(b=0;b<LANES;b=b+1)if((b/8)==int'(tile[0]))begin pm_en[b]=1;pm_addr[b*13+:13]=ap_weight_read_address;end")
    text = text.replace("int'(ap_bias_tile)*(LANES/2)", "int'(ap_bias_tile)*4")
    start = text.index('    always @(posedge clk or negedge rst_n) begin', text.index('    always @* begin'))
    text = text[:start] + '''    always @(posedge clk or negedge rst_n)begin
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
'''
    return text
