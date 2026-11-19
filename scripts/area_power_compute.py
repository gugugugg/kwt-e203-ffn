"""Apply ER lifetime reuse and fixed single-row controls to frozen CROSS RTL."""
import re


def _replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Inspect frozen CROSS edit point: ' + before[:100])
    return text.replace(before, after, 1)


def transform_core(text):
    text = _replace(text, "    localparam [4:0] TP_BP_SEED=5'd16;",
                    "    localparam [4:0] AP_ER_SEED=5'd16;")
    text = _replace(
        text,
        '    integer row,tile,inner,lane,chunk,item,mac_group,emit_group,stash_pointer;',
        '''    reg [6:0] row;
    reg [3:0] tile,lane;
    reg [5:0] inner;
    reg [2:0] chunk;
    reg [14:0] item;
    localparam integer mac_group=0,emit_group=0;
    integer stash_pointer;''')
    text = _replace(text,
                    "    wire [2:0] block_rows=3'((99-row<ROW_GROUP)?99-row:ROW_GROUP);",
                    "    wire [2:0] block_rows=3'd1;")
    text = _replace(text,
                    "    wire input_complete=int'(input_count)>=(row+int'(block_rows))*64;",
                    "    wire input_complete={1'b0,input_count}>=((14'({1'b0,row})+14'd1)<<6);")

    start = text.index('    reg tp_bp_active,tp_bp_capture_phase,tp_bp_valid;')
    end = text.index('    wire prefetch=', start)
    text = text[:start] + '''    reg ap_er_next_seed_ready;
    wire ap_er_seed_wait=state==AP_ER_SEED;
    wire ap_er_has_next=(row<7'd98)||(tile<4'd15);
    wire ap_er_first_request=(state==B_MAC)&&(inner==6'd63)&&ap_er_has_next;
    wire ap_er_reseed=(state==EMIT)&&fifo_push&&ap_er_has_next;
    wire ap_er_next_request=ap_er_reseed&&(lane<4'd14);
    wire ap_er_request=ap_er_first_request||ap_er_next_request;
    wire [3:0] ap_er_target_tile=(tile==4'd15)?4'd0:(tile+4'd1);
    wire [2:0] ap_er_request_pair=ap_er_first_request?3'd0:(lane[3:1]+3'd1);
    wire [3:0] ap_bias_tile=ap_er_request?ap_er_target_tile:tile;
    wire [2:0] ap_bias_pair=ap_er_request?ap_er_request_pair:chunk;
    wire bias_request=(state==BIAS_REQ)||ap_er_request;
    wire bias_capture=state==BIAS_CAP;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)ap_er_next_seed_ready<=0;
        else if(layer_start_valid&&layer_start_ready)ap_er_next_seed_ready<=0;
        else begin
            if(ap_er_seed_wait)ap_er_next_seed_ready<=0;
            if(ap_er_reseed&&lane==4'd14)ap_er_next_seed_ready<=1;
        end
    end

''' + text[end:]
    start = text.index('    generate for(genvar tp_bp_bank=0;')
    end = text.index('    end endgenerate', start) + len('    end endgenerate\n')
    text = text[:start] + text[end:]
    text = text.replace('tp_bp_read_tile', 'ap_bias_tile')
    text = text.replace('tp_bp_read_chunk', 'ap_bias_pair')
    text = _replace(text, '.enable(bias_capture||tp_bp_seed||(state==B_MAC)||(state==ROW1_MAC)||fifo_push)',
                    '.enable(bias_capture||(state==B_MAC)||(state==ROW1_MAC)||fifo_push)')
    text = _replace(text, '''                    if(tp_bp_seed)begin
                        accumulator[group_id*LANES+lane_id]<=36'($signed(tp_bp_bias[lane_id*32+:32]));
                        shifts[group_id*LANES+lane_id]<=$signed(tp_bp_shift[lane_id*8+:8]);
                    end''', '''                    if(ap_er_reseed&&lane[3:1]==3'(lane_id/2))begin
                        accumulator[group_id*LANES+lane_id]<=36'($signed(bias_pair[(lane_id%2)*64+:64]));
                        shifts[group_id*LANES+lane_id]<=$signed(shift_rdata[(lane_id%2)*8+:8]);
                    end''')
    text = _replace(text, 'MAC_INIT:begin chunk<=0;state<=tp_bp_valid?TP_BP_SEED:BIAS_REQ;end',
                    'MAC_INIT:begin chunk<=0;state<=ap_er_next_seed_ready?AP_ER_SEED:BIAS_REQ;end')
    text = _replace(text, 'TP_BP_SEED:begin inner<=0;mac_group<=0;state<=A_REQ;end',
                    'AP_ER_SEED:begin inner<=0;state<=A_REQ;end')

    text = re.sub(r'(?:mac_group|emit_group)<=\s*(?:mac_group\+1|emit_group\+1|0|1);', '', text)
    text = _replace(text,
                    "    wire [5:0] request_inner=6'(inner+int'(prefetch));",
                    "    wire [5:0] request_inner=6'({1'b0,inner}+{6'd0,prefetch});")
    old_mac = "    wire signed [16:0] mac_a=USE_ROW_CACHE?$signed(row_cache[(SMALL_INPUT?((row/ROW_GROUP)%INPUT_SLOTS)*ROW_GROUP*64:0)+mac_group*64+inner]):$signed({sp_rdata[(inner%8)*16+15],sp_rdata[(inner%8)*16+:16]});"
    text = _replace(text, old_mac,
                    "    wire signed [16:0] mac_a=$signed(row_cache[{row[0],inner}]);")
    text = text.replace('accumulator[emit_group*LANES+lane+1]', "accumulator[{1'b0,lane}+5'd1]")
    text = text.replace('accumulator[emit_group*LANES+lane]', 'accumulator[lane]')
    text = text.replace('shifts[emit_group*LANES+lane+1]', "shifts[{1'b0,lane}+5'd1]")
    text = text.replace('shifts[emit_group*LANES+lane]', 'shifts[lane]')
    text = _replace(text, "(int'(input_count)<(row+ROW_GROUP*INPUT_SLOTS)*64)",
                    "({1'b0,input_count}<((14'({1'b0,row})+14'd2)<<6))")
    text = _replace(text, "if(item+int'(pop_count)==25344)",
                    "if({1'b0,item}+{14'd0,pop_count}==16'd25344)")
    text = _replace(text, "else item<=item+int'(pop_count);",
                    "else item<=15'({1'b0,item}+{14'd0,pop_count});")
    text = _replace(text,
                    "    assign trace_index=15'((row+((state==STASH_OUT)?emit_group:0))*256+((state==STASH_OUT)?stash_pointer:tile*LANES+lane));",
                    '    assign trace_index={row,tile,lane};')
    text = _replace(text, "ADVANCE:if(row+int'(block_rows)==99)",
                    "ADVANCE:if({1'b0,row}+8'd1==8'd99)")
    text = _replace(text, 'row<=row+ROW_GROUP;', "row<=row+7'd1;")
    return text
