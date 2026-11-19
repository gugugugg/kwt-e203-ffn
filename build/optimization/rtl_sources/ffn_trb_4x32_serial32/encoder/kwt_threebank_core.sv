module kwt_threebank_core (
    input wire clk, rst_n, start,
    output reg busy, done, error,
    output wire ld_cmd_valid, input wire ld_cmd_ready,
    output wire [31:0] ld_cmd_addr,
    output wire ld_cmd_read,
    output wire [31:0] ld_cmd_wdata,
    output wire [3:0] ld_cmd_wmask,
    input wire ld_rsp_valid, output wire ld_rsp_ready,
    input wire [31:0] ld_rsp_rdata, input wire ld_rsp_err,
    input wire [11:0] ld_input_committed,
    input wire [13:0] ld_parameter_committed
);
    localparam [10:0] PACKET = 11'd1064;
    reg [13:0] sent;
    reg [4:0] source_tile, load_tile, oldest;
    reg [10:0] source_offset, load_offset;
    reg [11:0] input_words;
    reg [5:0] tail_k;
    reg [1:0] tail_row;
    reg [1:0] page_live, page_full;
    reg [3:0] page_units [0:1];
    reg [4:0] page_emits [0:1];
    reg signed [31:0] bias [0:1][0:31];
    reg signed [7:0] shift [0:1][0:31];

    reg [31:0] ingress [0:7];
    reg [2:0] ingress_head, ingress_tail;
    reg [3:0] ingress_count, in_flight;
    reg [2:0] load_count;
    wire [31:0] front [0:3];
    for (genvar lane=0;lane<4;lane=lane+1) begin: ingress_front
        assign front[lane]=ingress[3'(ingress_head+3'(lane))];
    end
    // Wire order: first pair of input groups, P0, remaining input, P1 onward.
    wire first_parameter=sent>=14'd256&&sent<14'd1320;
    wire source_parameter=first_parameter||sent>=14'd4232;
    wire [13:0] parameter_word=first_parameter?sent-14'd256:sent-14'd3168;
    wire [13:0] input_word=sent<14'd256 ?sent:sent-14'd1064;
    wire page_admit=source_offset!=0||
        (!page_live[source_tile[0]]&&source_tile<=oldest+5'd1);
    wire [4:0] credits={1'b0,ingress_count}+{1'b0,in_flight}-{2'b0,load_count};
    wire [31:0] source_addr=source_parameter?{16'ha002,parameter_word,2'b00}:
                                              {16'ha000,input_word,2'b00};
    wire source_ready=sent<14'd11680&&credits<5'd8&&
        (source_parameter?(page_admit&&parameter_word<ld_parameter_committed):
                          input_word<{2'b0,ld_input_committed});
    assign ld_rsp_ready=busy;
    wire dma_fire=ld_cmd_valid&&ld_cmd_ready;
    wire source_fire=dma_fire&&ld_cmd_read;
    reg dma_response_write;
    wire dma_retire=ld_rsp_valid&&ld_rsp_ready;
    wire return_fire=dma_retire&&!dma_response_write;
    wire accepted=source_fire;
    wire returned=return_fire;

    reg phase, unit_active;
    reg [4:0] unit_tile;
    reg [3:0] unit_pair;
    reg [6:0] unit_index;
    reg [2:0] unit_slot;
    reg [2:0] slot_alloc, slot_read;
    reg [3:0] slot_count;
    reg [7:0] slot_complete;
    reg [4:0] slot_group [0:7];
    reg [3:0] slot_tile [0:7];
    wire [4:0] selected_tile=oldest+5'(page_units[oldest[0]]==13);
    wire [3:0] selected_pair=page_units[selected_tile[0]];
    wire [1:0] reserve_count=selected_pair==12?2'd1:2'd2;
    wire [11:0] input_need=selected_pair==12?12'd3168:({selected_pair,8'b0}+12'd256);
    wire choose=busy&&!unit_active&&input_words>=input_need&&
        selected_tile<8&&page_live[selected_tile[0]]&&page_full[selected_tile[0]]&&
        selected_pair<13&&(selected_pair==12||!phase)&&
        {1'b0,slot_count}+{3'b0,reserve_count}<=5'd8;
    wire [4:0] issue_tile=unit_active?unit_tile:selected_tile;
    wire [3:0] issue_pair=unit_active?unit_pair:selected_pair;
    wire [6:0] issue_index=unit_active?unit_index:7'd0;
    wire issue_tail=issue_pair==12;
    wire issue_side=!issue_tail&&issue_index[0];
    wire [5:0] issue_k=issue_tail?issue_index[5:0]:issue_index[6:1];
    wire [2:0] issue_slot=(unit_active?unit_slot:slot_alloc)+3'(issue_side);
    wire [9:0] issue_address={issue_pair,issue_k};
    wire issue=busy&&(unit_active||choose);
    wire issue_last=issue_tail?issue_index==63:issue_index==127;

    typedef struct packed {
        logic valid, tail, side, page;
        logic [2:0] slot;
        logic [5:0] k;
    } token_t;
    token_t tags [0:32];
    reg [63:0] operands [1:31];
    wire [15:0] input_q [0:7];
    always @(posedge clk) begin
        tags[0]<={issue,issue_tail,issue_side,issue_tile[0],issue_slot,issue_k};
        for(integer index=1;index<=32;index=index+1) tags[index]<=tags[index-1];
    end
    for(genvar index=1;index<=31;index=index+1) begin: operand_stage
        wire operand_clk;
        kwt_ffn_clock_gate clock_gate(.clk(clk),.enable(tags[index-1].valid),
                                       .test_enable(1'b0),.gated_clk(operand_clk));
        if(index==1) begin: input_capture
            always @(posedge operand_clk)
                operands[index]<=tags[0].side?{input_q[7],input_q[6],input_q[5],input_q[4]}:
                    {tags[0].tail?16'b0:input_q[3],input_q[2],input_q[1],input_q[0]};
        end else begin: forwarding
            always @(posedge operand_clk) operands[index]<=operands[index-1];
        end
    end

    wire load_input=input_words<12'd256||(load_tile!=0&&input_words<12'd3168);
    wire [11:0] input_next=input_words+12'd1;
    wire tail_load=input_words>=12'd3072;
    wire [1:0] tail_high_row=tail_row==2?2'd0:tail_row+2'd1;
    wire [2:0] low_bank=tail_load?{1'b0,tail_row}:{input_words[1:0],1'b0};
    wire [2:0] high_bank=tail_load?{1'b0,tail_high_row}:low_bank+3'd1;
    wire [2:0] next_low_bank={input_next[1:0],1'b0};
    wire [2:0] next_high_bank=next_low_bank+3'd1;
    wire [7:0] input_read=issue?(issue_tail?8'h07:(issue_side?8'hf0:8'h0f)):8'h00;
    wire input_ok0=!input_read[low_bank]&&!input_read[high_bank];
    wire input_ok1=!input_read[next_low_bank]&&!input_read[next_high_bank];
    wire [10:0] offset0=load_offset-11'd40;
    wire [10:0] offset1=offset0+11'd2;
    wire [2:0] quartet0=offset0[3:1], quartet1=offset1[3:1];
    wire [6:0] weight_addr0={load_tile[0],offset0[9:4]};
    wire [6:0] weight_addr1={load_tile[0],offset1[9:4]};
    wire [31:0] weight_read;
    wire weight_ok0=(weight_read&(32'hf<<(4*quartet0)))==0;
    wire weight_ok1=(weight_read&(32'hf<<(4*quartet1)))==0;
    always @* begin
        load_count=0;
        if(busy&&ingress_count!=0) begin
            if(load_input) begin
                if(input_ok0) begin
                    load_count=3'd1;
                    if(ingress_count>=2&&input_words!=12'd255&&input_words<12'd3071&&input_ok1)
                        load_count=3'd2;
                end
            end else if(load_offset<40)
                load_count=ingress_count>=2&&load_offset<39?3'd2:3'd1;
            else if(ingress_count>=2&&weight_ok0) begin
                load_count=3'd2;
                if(ingress_count>=4&&load_offset<=PACKET-4&&weight_ok1)
                    load_count=3'd4;
            end
        end
    end
    for(genvar page=0;page<2;page=page+1) begin: parameter_pages
        for(genvar word=0;word<40;word=word+1) begin: words
            wire eligible=rst_n&&busy&&!load_input&&load_tile[0]==page[0];
            wire lane0=eligible&&load_count!=0&&load_offset==11'(word);
            wire lane1=eligible&&load_count>1&&({1'b0,load_offset}+12'd1)==12'(word);
            wire [31:0] write_data=lane1?front[1]:front[0];
            wire word_clk;
            kwt_ffn_clock_gate word_gate(.clk(clk),.enable(lane0||lane1),
                .test_enable(1'b0),.gated_clk(word_clk));
            if(word<32) begin: bias_word
                always @(posedge word_clk) bias[page][word]<=write_data;
            end else begin: shift_word
                always @(posedge word_clk)
                    for(integer sub=0;sub<4;sub=sub+1)
                        shift[page][4*(word-32)+sub]<=write_data[8*sub+:8];
            end
        end
    end

    wire [63:0] weight_data0={front[1],front[0]};
    wire [63:0] weight_data1={front[3],front[2]};
    wire [31:0] column_emit;
    wire signed [35:0] emit_acc [0:31][0:3];
    wire signed [7:0] emit_shift [0:31];
    for(genvar col=0;col<32;col=col+1) begin: weight_columns
        localparam integer AGE=2*(col%16);
        wire write0=!load_input&&load_offset>=40&&load_count>=2&&quartet0==3'(col/4);
        wire write1=!load_input&&load_offset>=40&&load_count==4&&quartet1==3'(col/4);
        wire wr=write0||write1;
        assign weight_read[col]=tags[AGE].valid&&(tags[AGE].tail||!tags[AGE].side);
        wire [6:0] address=write0?weight_addr0:write1?weight_addr1:{tags[AGE].page,tags[AGE].k};
        wire [15:0] weight_q;
        wire sram_clk;
        kwt_ffn_clock_gate sram_gate(.clk(clk),.enable(weight_read[col]||wr),.test_enable(1'b0),.gated_clk(sram_clk));
        RAMSP128X16 memory(.CLK(sram_clk),.CEN(!(weight_read[col]||wr)),.GWEN(!wr),
            .WEN({16{!wr}}),.A(address),.D(write1?weight_data1[(col%4)*16+:16]:
                                                        weight_data0[(col%4)*16+:16]),
            .Q(weight_q),.EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
        wire execute=tags[AGE+1].valid;
        wire side=tags[AGE+1].side;
        wire tail=tags[AGE+1].tail;
        wire first=tags[AGE+1].k==0;
        wire signed [31:0] seed=bias[tags[AGE+1].page][col];
        wire [3:0] context_clk;
        kwt_ffn_clock_gate gate_a(.clk(clk),.enable(execute&&!side),.test_enable(1'b0),.gated_clk(context_clk[0]));
        kwt_ffn_clock_gate gate_b(.clk(clk),.enable(execute&&side),.test_enable(1'b0),.gated_clk(context_clk[1]));
        kwt_ffn_clock_gate gate_full_a(.clk(clk),.enable(execute&&!side&&!tail),.test_enable(1'b0),.gated_clk(context_clk[2]));
        kwt_ffn_clock_gate gate_full_b(.clk(clk),.enable(execute&&side&&!tail),.test_enable(1'b0),.gated_clk(context_clk[3]));
        assign column_emit[col]=tags[AGE+2].valid&&tags[AGE+2].k==63;
        assign emit_shift[col]=shift[tags[AGE+2].page][col];
        for(genvar row=0;row<4;row=row+1) begin: lanes
            localparam integer GATE=(row>=3)?2:0;
            reg signed [35:0] acc_a,acc_b;
            wire signed [15:0] operand=operands[AGE+1][row*16+:16];
            wire signed [31:0] product=operand*$signed(weight_q);
            wire signed [35:0] previous=first?{{4{seed[31]}},seed}:(side?acc_b:acc_a);
            wire signed [35:0] sum=previous+{{4{product[31]}},product};
            always @(posedge context_clk[GATE]) acc_a<=sum;
            always @(posedge context_clk[GATE+1]) acc_b<=sum;
            assign emit_acc[col][row]=tags[AGE+2].side?acc_b:acc_a;
        end
    end


    wire [9:0] input_address0=tail_load?{4'd12,tail_k}:{input_words[11:8],input_words[7:2]};
    wire [9:0] input_address1={input_next[11:8],input_next[7:2]};
    for(genvar bank=0;bank<8;bank=bank+1) begin: input_memory
        wire lo=load_input&&load_count!=0&&low_bank==3'(bank);
        wire hi=load_input&&load_count!=0&&high_bank==3'(bank);
        wire wr1=load_input&&load_count==2&&(next_low_bank==3'(bank)||next_high_bank==3'(bank));
        wire wr=lo||hi||wr1;
        wire [9:0] addr=wr1?input_address1:wr?input_address0+10'(tail_load&&hi&&tail_row==2):issue_address;
        wire [15:0] data=wr1?(bank%2==0?front[1][15:0]:front[1][31:16]):
                                      (hi?front[0][31:16]:front[0][15:0]);
        wire sram_clk;
        kwt_ffn_clock_gate sram_gate(.clk(clk),.enable(wr||input_read[bank]),.test_enable(1'b0),.gated_clk(sram_clk));
        RAMSP1024X16 memory(.CLK(sram_clk),.CEN(!(wr||input_read[bank])),.GWEN(!wr),
            .WEN({16{!wr}}),.A(addr),.D(data),.Q(input_q[bank]),.EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
    end

    reg emit_valid,emit_page,emit_tail;
    reg [2:0] emit_slot;
    reg [3:0] emit_col;
    reg signed [7:0] quant_shift [0:1];
    reg signed [35:0] quant_source [0:7];
    wire [15:0] rounded [0:7];
    always @* begin
        emit_valid=0;emit_page=0;emit_tail=0;emit_slot=0;emit_col=0;
        quant_shift[0]=0;quant_shift[1]=0;
        for(integer lane=0;lane<8;lane=lane+1) quant_source[lane]=0;
        for(integer col=0;col<16;col=col+1) if(column_emit[col]) begin
            emit_valid=1;emit_page=tags[2+2*col].page;emit_tail=tags[2+2*col].tail;
            emit_slot=tags[2+2*col].slot;emit_col=4'(col);
            quant_shift[0]=emit_shift[col];quant_shift[1]=emit_shift[col+16];
            for(integer row=0;row<4;row=row+1) begin
                quant_source[row]=emit_acc[col][row];
                quant_source[row+4]=emit_acc[col+16][row];
            end
        end
    end
    for(genvar lane=0;lane<8;lane=lane+1) begin: requantizers
        kwt_ffn_requantize quantizer(.value({{28{quant_source[lane][35]}},quant_source[lane]}),
                                    .shift(quant_shift[lane/4]),.result(rounded[lane]));
    end
    reg quant_valid,quant_page,quant_tail;
    reg [2:0] quant_slot;
    reg [3:0] quant_col;
    reg [127:0] quant_data;
    always @(posedge clk or negedge rst_n)
        if(!rst_n) quant_valid<=0;
        else quant_valid<=emit_valid;
    always @(posedge clk) if(emit_valid) begin
        quant_page<=emit_page;quant_tail<=emit_tail;quant_slot<=emit_slot;quant_col<=emit_col;
        for(integer lane=0;lane<8;lane=lane+1) quant_data[16*lane+:16]<=rounded[lane];
    end
    wire quant_done=quant_valid&&quant_col==15;
    wire page_release=busy&&oldest<8&&page_live[oldest[0]]&&
        (page_emits[oldest[0]]==25||
         (page_emits[oldest[0]]==24&&quant_done&&quant_page==oldest[0]));

    // An aligned read consumes four consecutive banks. The output stores only
    // payload; the physical retirement cursor carries row and tile identity.
    reg [4:0] read_index;
    reg [5:0] retire_index;
    reg [2:0] retire_slot;
    wire [3:0] read_col={read_index[1:0],2'b00};
    wire [2:0] scratch_base={1'b0,read_index[4:3]}+3'(read_col)+{read_index[2],2'b0};
    wire scratch_last=read_index==(slot_group[slot_read]==24?5'd23:5'd31);
    wire [6:0] result_row={slot_group[retire_slot],2'b00}+{5'b0,retire_index[5:4]};
    wire retire_last=retire_index==(slot_group[retire_slot]==24?6'd47:6'd63);
    reg pending_result;
    reg [2:0] pending_base;
    reg [63:0] out_word [0:16];
    reg [4:0] out_head,out_tail;
    reg [5:0] out_count;
    reg [13:0] ack_count;
    wire [15:0] result_q [0:7];
    for (genvar entry=0; entry<17; entry++) begin: fifo_entries
        wire write_entry=rst_n&&busy&&pending_result&&out_tail==5'(entry);
        wire entry_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(write_entry),
            .test_enable(1'b0),.gated_clk(entry_clk));
        wire [63:0] entry_data=write_entry?{result_q[3'(pending_base+3'd3)],result_q[3'(pending_base+3'd2)],
                                    result_q[3'(pending_base+3'd1)],result_q[pending_base]}:64'hffffffffffffffff;
        always @(posedge entry_clk) out_word[entry]<=entry_data;
    end
    wire [6:0] output_credit={1'b0,out_count}+{5'b0,pending_result,1'b0};
    wire [16:0] result_word=17'd16384+{3'b0,result_row,slot_tile[retire_slot][2:0],retire_index[3:0]};
    wire result_ready=out_count!=0;
    wire slot_pressure=selected_tile<8&&{1'b0,slot_count}+{3'b0,reserve_count}>5'd8;
    reg drain, held_command, held_read;
    wire choose_write=result_ready&&(drain||output_credit>=32||slot_pressure||!source_ready);
    assign ld_cmd_read=held_command?held_read:!choose_write;
    assign ld_cmd_valid=busy&&(held_command||choose_write||source_ready);
    assign ld_cmd_addr=ld_cmd_read?source_addr:{13'h1400,result_word,2'b00};
    assign ld_cmd_wdata=ld_cmd_read?32'b0:
        (retire_index[0]?out_word[out_head][63:32]:out_word[out_head][31:0]);
    assign ld_cmd_wmask=ld_cmd_read?4'b0:4'hf;
    wire result_fire=dma_fire&&!ld_cmd_read;
    wire result_ack=dma_retire&&dma_response_write&&!ld_rsp_err;
    wire slot_release=result_fire&&retire_last;
    wire [7:0] quant_mask,scratch_mask;
    wire scratch_read=busy&&slot_complete[slot_read]&&(output_credit<=32||(output_credit==33&&result_fire))&&
        ((scratch_mask&quant_mask)==0);
    for(genvar bank=0;bank<8;bank=bank+1) begin: result_memory
        wire [2:0] quant_lane=3'(bank)-quant_col[2:0];
        wire [2:0] read_lane=3'(bank)-scratch_base;
        assign quant_mask[bank]=quant_valid&&(!quant_tail||quant_lane[1:0]!=3);
        assign scratch_mask[bank]=!read_lane[2];
        wire wr=quant_mask[bank];
        wire rd=scratch_read&&scratch_mask[bank];
        wire [6:0] address=wr?{quant_slot,quant_col}:{slot_read,read_col+4'(read_lane)};
        wire sram_clk;
        kwt_ffn_clock_gate sram_gate(.clk(clk),.enable(rd||wr),.test_enable(1'b0),.gated_clk(sram_clk));
        RAMSP128X16 memory(.CLK(sram_clk),.CEN(!(rd||wr)),.GWEN(!wr),
            .WEN({16{!wr}}),.A(address),.D(quant_data[16*quant_lane+:16]),.Q(result_q[bank]),
            .EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
    end

    wire starting=start&&!busy;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            drain<=0;held_command<=0;held_read<=0;dma_response_write<=0;
        end else if(starting) begin
            drain<=0;held_command<=0;dma_response_write<=0;
        end else begin
            drain<=choose_write;
            if(dma_fire) begin
                held_command<=0;
                dma_response_write<=!ld_cmd_read;
            end else if(ld_cmd_valid&&!held_command) begin
                held_command<=1;
                held_read<=ld_cmd_read;
            end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin busy<=0;done<=0;error<=0;phase<=0;end
        else begin
            phase<=!phase;
            if(starting) begin busy<=1;done<=0;error<=0;phase<=1;end
            if(dma_retire&&ld_rsp_err) begin error<=1;busy<=0;end
            if(result_ack&&ack_count==14'd12671) begin busy<=0;done<=1;end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            sent<=0;source_tile<=0;source_offset<=0;load_tile<=0;load_offset<=0;
            input_words<=0;
            tail_row<=0;tail_k<=0;ingress_count<=0;ingress_head<=0;ingress_tail<=0;in_flight<=0;
            page_live<=0;page_full<=0;oldest<=0;unit_active<=0;unit_index<=0;
            slot_alloc<=0;slot_read<=0;slot_count<=0;slot_complete<=0;read_index<=0;retire_index<=0;retire_slot<=0;
            pending_result<=0;out_count<=0;out_head<=0;out_tail<=0;ack_count<=0;
            for(integer p=0;p<2;p=p+1) begin page_units[p]<=0;page_emits[p]<=0;end
        end else if(starting) begin
            sent<=0;source_tile<=0;source_offset<=0;load_tile<=0;load_offset<=0;
            input_words<=0;
            tail_row<=0;tail_k<=0;ingress_count<=0;ingress_head<=0;ingress_tail<=0;in_flight<=0;
            page_live<=0;page_full<=0;oldest<=0;unit_active<=0;unit_index<=0;
            slot_alloc<=0;slot_read<=0;slot_count<=0;slot_complete<=0;read_index<=0;retire_index<=0;retire_slot<=0;
            pending_result<=0;out_count<=0;out_head<=0;out_tail<=0;ack_count<=0;
            for(integer p=0;p<2;p=p+1) begin page_units[p]<=0;page_emits[p]<=0;end
        end else if(busy) begin
            if(page_release) begin page_live[oldest[0]]<=0;oldest<=oldest+5'd1;end
            if(accepted!=0) begin
                sent<=sent+14'(accepted);
                if(source_parameter) begin
                    if(source_offset==0) begin
                        page_live[source_tile[0]]<=1;page_full[source_tile[0]]<=0;
                        page_units[source_tile[0]]<=0;page_emits[source_tile[0]]<=0;
                    end
                    if(source_offset+11'(accepted)==PACKET) begin
                        source_offset<=0;source_tile<=source_tile+5'd1;
                    end else source_offset<=source_offset+11'(accepted);
                end
            end
            if(return_fire) ingress[ingress_tail]<=ld_rsp_rdata;
            ingress_tail<=ingress_tail+3'(returned);
            ingress_head<=ingress_head+load_count;
            ingress_count<=ingress_count+4'(returned)-4'(load_count);
            in_flight<=in_flight+4'(accepted)-4'(returned);
            if(load_count!=0) begin
                if(load_input) begin
                    input_words<=input_words+12'(load_count);
                    if(tail_load) begin
                        tail_row<=tail_row==0?2'd2:tail_row-2'd1;
                        if(tail_row!=0) tail_k<=tail_k+6'd1;
                    end
                end else begin
                    if(load_offset+11'(load_count)==PACKET) begin
                        page_full[load_tile[0]]<=1;load_offset<=0;load_tile<=load_tile+5'd1;
                    end else load_offset<=load_offset+11'(load_count);

                end
            end

            if(choose) begin
                page_units[selected_tile[0]]<=selected_pair+4'd1;
                unit_active<=1;unit_tile<=selected_tile;unit_pair<=selected_pair;
                unit_slot<=slot_alloc;
                slot_group[slot_alloc]<={selected_pair,1'b0};slot_tile[slot_alloc]<=selected_tile[3:0];
                slot_complete[slot_alloc]<=0;
                if(reserve_count==2) begin
                    slot_group[3'(slot_alloc+3'd1)]<={selected_pair,1'b1};
                    slot_tile[3'(slot_alloc+3'd1)]<=selected_tile[3:0];slot_complete[3'(slot_alloc+3'd1)]<=0;
                end
                slot_alloc<=slot_alloc+3'(reserve_count);
            end
            if(issue) begin
                unit_index<=issue_index+7'd1;
                if(issue_last) unit_active<=0;
            end
            slot_count<=slot_count+(choose?4'(reserve_count):4'd0)-4'(slot_release);
            if(quant_done) begin
                slot_complete[quant_slot]<=1;
                page_emits[quant_page]<=page_emits[quant_page]+5'd1;
            end
            if(scratch_read) begin
                pending_base<=scratch_base;
                read_index<=scratch_last?5'd0:read_index+5'd1;
                if(scratch_last) begin
                    slot_read<=slot_read+3'd1;
                    slot_complete[slot_read]<=0;
                end
            end
            pending_result<=scratch_read;
            if(pending_result) begin
                out_tail<=out_tail==16?5'd0:out_tail+5'd1;
            end
            if(result_fire) begin
                if(retire_index[0]) out_head<=out_head==16?5'd0:out_head+5'd1;
                retire_index<=retire_last?6'd0:retire_index+6'd1;
                if(retire_last) retire_slot<=retire_slot+3'd1;
            end
            out_count<=out_count+{4'b0,pending_result,1'b0}-6'(result_fire);
            if(result_ack) ack_count<=ack_count+14'd1;
        end
    end
endmodule

