module kwt_threebank_core (
    input wire clk, rst_n, start,
    output reg busy, done, error,
    output wire ld_cmd_valid, input wire ld_cmd_ready,
    output wire [31:0] ld_cmd_addr,
    input wire ld_rsp_valid, output wire ld_rsp_ready,
    input wire [31:0] ld_rsp_rdata, input wire ld_rsp_err,
    output wire ld2_cmd_valid, input wire ld2_cmd_ready,
    input wire ld2_rsp_valid, input wire [31:0] ld2_rsp_rdata,
    output wire wb_valid, input wire wb_ready,
    output wire [16:0] wb_addr, output wire [31:0] wb_data,
    input wire wb_ack_valid, output wire wb_ack_ready
);
    localparam [9:0] PACKET = 10'd532;
    reg [13:0] sent;
    reg [4:0] source_tile, load_tile, oldest;
    reg [9:0] source_offset, load_offset;
    reg [11:0] input_words;
    reg [2:0] load_group_pair, load_input_pair;
    reg [5:0] load_input_k, tail_k;
    reg [1:0] tail_row;
    reg [1:0] page_live, page_full;
    reg [3:0] page_units [0:1];
    reg [4:0] page_emits [0:1];
    reg signed [31:0] bias [0:1][0:15];
    reg signed [7:0] shift [0:1][0:15];

    reg [31:0] ingress [0:7];
    reg [2:0] ingress_head, ingress_tail;
    reg [3:0] ingress_count, in_flight;
    reg [2:0] load_count;
    wire [31:0] front [0:3];
    for (genvar lane=0;lane<4;lane=lane+1) begin: ingress_front
        assign front[lane]=ingress[3'(ingress_head+3'(lane))];
    end
    wire source_parameter=sent>=14'd3168;
    wire [13:0] parameter_word=sent-14'd3168;
    wire page_admit=source_offset!=0||
        (!page_live[source_tile[0]]&&source_tile<=oldest+5'd1);
    wire [4:0] credits={1'b0,ingress_count}+{1'b0,in_flight}-{2'b0,load_count};
    assign ld_cmd_addr=source_parameter?{16'ha002,parameter_word,2'b00}:
                                              {16'ha000,sent,2'b00};
    assign ld_cmd_valid=busy&&sent<14'd11680&&credits<5'd8&&
                        (!source_parameter||page_admit);
    assign ld2_cmd_valid=ld_cmd_valid&&credits<5'd7&&
                         (source_parameter?source_offset<PACKET-1:sent<14'd3167);
    assign ld_rsp_ready=busy;
    wire source_fire=ld_cmd_valid&&ld_cmd_ready;
    wire source_fire2=ld2_cmd_valid&&ld2_cmd_ready;
    wire return_fire=ld_rsp_valid&&ld_rsp_ready;
    wire return_fire2=ld2_rsp_valid&&ld_rsp_ready;
    wire [1:0] accepted={1'b0,source_fire}+{1'b0,source_fire2};
    wire [1:0] returned={1'b0,return_fire}+{1'b0,return_fire2};

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
    reg [5:0] read_index;
    wire [4:0] selected_tile=oldest+5'(page_units[oldest[0]]==9);
    wire [3:0] selected_pair=page_units[selected_tile[0]];
    wire [1:0] reserve_count=selected_pair==8?2'd1:2'd2;
    wire choose=busy&&!unit_active&&input_words==12'd3168&&
        selected_tile<16&&page_live[selected_tile[0]]&&page_full[selected_tile[0]]&&
        selected_pair<9&&(selected_pair==8||!phase)&&
        {1'b0,slot_count}+{3'b0,reserve_count}<=5'd8;
    wire [4:0] issue_tile=unit_active?unit_tile:selected_tile;
    wire [3:0] issue_pair=unit_active?unit_pair:selected_pair;
    wire [6:0] issue_index=unit_active?unit_index:7'd0;
    wire issue_tail=issue_pair==8;
    wire issue_side=!issue_tail&&issue_index[0];
    wire [5:0] issue_k=issue_tail?issue_index[5:0]:issue_index[6:1];
    wire [2:0] issue_slot=(unit_active?unit_slot:slot_alloc)+3'(issue_side);
    wire [9:0] issue_address={issue_pair[2:0],issue_side,issue_k};
    wire issue=busy&&(unit_active||choose);
    wire issue_last=issue_tail?issue_index==63:issue_index==127;

    typedef struct packed {
        logic valid, tail, side, page;
        logic [2:0] slot;
        logic [5:0] k;
    } token_t;
    token_t tags [0:32];
    reg [95:0] operands [1:31];
    wire [15:0] input_q [0:8];
    always @(posedge clk) begin
        tags[0]<={issue,issue_tail,issue_side,issue_tile[0],issue_slot,issue_k};
        for(integer index=1;index<=32;index=index+1) tags[index]<=tags[index-1];
    end
    for(genvar index=1;index<=31;index=index+1) begin: operand_stage
        wire operand_clk;
        kwt_ffn_clock_gate clock_gate(.clk(clk),.enable(tags[index-1].valid),
                                       .test_enable(1'b0),.gated_clk(operand_clk));
        if(index==1) begin: input_capture
            always @(posedge operand_clk) operands[index]<=tags[0].tail?
                {48'd0,input_q[8],input_q[7],input_q[6]}:
                {input_q[5],input_q[4],input_q[3],input_q[2],input_q[1],input_q[0]};
        end else begin: forwarding
            always @(posedge operand_clk) operands[index]<=operands[index-1];
        end
    end

    wire [9:0] offset0=load_offset-10'd20;
    wire [9:0] offset1=offset0+10'd2;
    wire [1:0] quartet0=offset0[2:1], quartet1=offset1[2:1];
    wire [6:0] weight_addr0={load_tile[0],offset0[8:3]};
    wire [6:0] weight_addr1={load_tile[0],offset1[8:3]};
    wire [15:0] weight_read;
    wire weight_ok0=(weight_read&(16'hf<<(4*quartet0)))==0;
    wire weight_ok1=(weight_read&(16'hf<<(4*quartet1)))==0;
    always @* begin
        load_count=0;
        if(busy&&ingress_count!=0) begin
            if(input_words<12'd3168)
                load_count=ingress_count>=2&&input_words<12'd3071 ?3'd2:3'd1;
            else if(load_offset<20)
                load_count=ingress_count>=2&&load_offset<19?3'd2:3'd1;
            else if(ingress_count>=2&&weight_ok0) begin
                load_count=3'd2;
                if(ingress_count>=4&&load_offset<=PACKET-4&&weight_ok1)
                    load_count=3'd4;
            end
        end
    end
    wire [63:0] weight_data0={front[1],front[0]};
    wire [63:0] weight_data1={front[3],front[2]};
    wire [15:0] column_emit;
    wire signed [35:0] emit_acc [0:15][0:5];
    wire signed [7:0] emit_shift [0:15];
    for(genvar col=0;col<16;col=col+1) begin: weight_columns
        localparam integer AGE=2*col;
        wire write0=input_words==12'd3168&&load_offset>=20&&load_count>=2&&quartet0==2'(col/4);
        wire write1=input_words==12'd3168&&load_offset>=20&&load_count==4&&quartet1==2'(col/4);
        wire wr=write0||write1;
        assign weight_read[col]=tags[AGE].valid&&(tags[AGE].tail||!tags[AGE].side);
        wire [6:0] address=write0?weight_addr0:write1?weight_addr1:{tags[AGE].page,tags[AGE].k};
        wire [15:0] weight_q;
        RAMSP128X16 memory(.CLK(clk),.CEN(!(weight_read[col]||wr)),.GWEN(!wr),
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
        for(genvar row=0;row<6;row=row+1) begin: lanes
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

    function automatic [3:0] input_pair_start(input [2:0] pair_index);
        begin
            case(pair_index)
                0,3: input_pair_start=0;
                1,4: input_pair_start=2;
                default: input_pair_start=4;
            endcase
        end
    endfunction
    wire [2:0] next_input_pair=load_input_pair==5?3'd0:load_input_pair+3'd1;
    wire [5:0] next_input_k=load_input_k+6'(load_input_pair==5);
    wire [2:0] next_group_pair=load_group_pair+3'(load_input_pair==5&&load_input_k==63);
    wire [9:0] input_address0={load_group_pair,load_input_pair>=3,load_input_k};
    wire [9:0] input_address1={next_group_pair,next_input_pair>=3,next_input_k};
    wire [3:0] input_bank0=input_pair_start(load_input_pair);
    wire [3:0] input_bank1=input_pair_start(next_input_pair);
    wire main_load=input_words<12'd3072;
    wire tail_load=input_words>=12'd3072&&input_words<12'd3168;
    wire [1:0] tail_high_row=tail_row==2?2'd0:tail_row+2'd1;
    for(genvar row=0;row<9;row=row+1) begin: input_memory
        if(row<6) begin: main
            wire write0=main_load&&load_count!=0&&(input_bank0==row||input_bank0+4'd1==row);
            wire write1=main_load&&load_count==2&&(input_bank1==row||input_bank1+4'd1==row);
            wire wr=write0||write1;
            wire [9:0] addr=write0?input_address0:write1?input_address1:issue_address;
            wire [31:0] data=write1?front[1]:front[0];
            RAMSP1024X16 memory(.CLK(clk),.CEN(!(wr||(issue&&!issue_tail))),.GWEN(!wr),
                .WEN({16{!wr}}),.A(addr),.D(data[(row%2)*16+:16]),.Q(input_q[row]),
                .EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
        end else begin: tail
            wire low=tail_load&&load_count!=0&&tail_row==row-6;
            wire high=tail_load&&load_count!=0&&tail_high_row==row-6;
            wire wr=low||high;
            wire [5:0] address=wr?(tail_k+6'(high&&tail_row==2)):issue_k;
            RAMSP128X16 memory(.CLK(clk),.CEN(!(wr||(issue&&issue_tail))),.GWEN(!wr),
                .WEN({16{!wr}}),.A({1'b0,address}),.D(high?front[0][31:16]:front[0][15:0]),.Q(input_q[row]),
                .EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
        end
    end

    reg emit_valid,emit_page,emit_tail;
    reg [2:0] emit_slot;
    reg [3:0] emit_col;
    reg signed [7:0] quant_shift;
    reg signed [35:0] quant_source [0:5];
    wire [15:0] rounded [0:5];
    always @* begin
        emit_valid=0;emit_page=0;emit_tail=0;emit_slot=0;emit_col=0;quant_shift=0;
        for(integer row=0;row<6;row=row+1) quant_source[row]=0;
        for(integer col=0;col<16;col=col+1) if(column_emit[col]) begin
            emit_valid=1;emit_page=tags[2+2*col].page;emit_tail=tags[2+2*col].tail;
            emit_slot=tags[2+2*col].slot;emit_col=4'(col);quant_shift=emit_shift[col];
            for(integer row=0;row<6;row=row+1) quant_source[row]=emit_acc[col][row];
        end
    end
    for(genvar row=0;row<6;row=row+1) begin: requantizers
        kwt_ffn_requantize quantizer(.value({{28{quant_source[row][35]}},quant_source[row]}),
                                    .shift(quant_shift),.result(rounded[row]));
    end
    reg quant_valid,quant_page,quant_tail;
    reg [2:0] quant_slot;
    reg [3:0] quant_col;
    reg [95:0] quant_data;
    always @(posedge clk or negedge rst_n)
        if(!rst_n) quant_valid<=0;
        else quant_valid<=emit_valid;
    always @(posedge clk) if(emit_valid) begin
        quant_page<=emit_page;quant_tail<=emit_tail;quant_slot<=emit_slot;quant_col<=emit_col;
        quant_data<={rounded[5],rounded[4],rounded[3],rounded[2],rounded[1],rounded[0]};
    end
    wire quant_done=quant_valid&&quant_col==15;
    wire page_release=busy&&oldest<16&&page_live[oldest[0]]&&
        (page_emits[oldest[0]]==17||
         (page_emits[oldest[0]]==16&&quant_done&&quant_page==oldest[0]));

    function automatic [2:0] column_mod6(input [3:0] col);
        if(col>=12) column_mod6=3'(col-12);
        else if(col>=6) column_mod6=3'(col-6);
        else column_mod6=col[2:0];
    endfunction
    function automatic [2:0] bank_for(input [2:0] row,input [3:0] col);
        reg [3:0] sum;
        begin
            sum={1'b0,row}+{1'b0,column_mod6(col)};
            bank_for=sum>=6?3'(sum-6):sum[2:0];
        end
    endfunction
    wire [3:0] read_col={read_index[2:0],1'b0};
    wire [2:0] read_row=read_index[5:3];
    wire [2:0] scratch_lo=bank_for(read_row,read_col);
    wire [2:0] scratch_hi=bank_for(read_row,read_col+4'd1);
    wire scratch_last=read_index==(slot_group[slot_read]==16?6'd23:6'd47);
    wire [6:0] result_row=({2'b0,slot_group[slot_read]}<<2)+
        ({2'b0,slot_group[slot_read]}<<1)+{4'b0,read_row};
    wire [16:0] scratch_dest=17'd16384+{3'b0,result_row,slot_tile[slot_read],read_index[2:0]};

    reg pending_result,pending_last;
    reg [2:0] pending_lo,pending_hi;
    reg [16:0] pending_addr;
    reg [31:0] out_word [0:1];
    reg [16:0] out_addr [0:1];
    reg [1:0] out_last,out_count;
    reg out_head,out_tail;
    reg [13:0] ack_count;
    wire [2:0] output_credit={1'b0,out_count}+{2'b0,pending_result};
    assign wb_valid=busy&&out_count!=0;
    assign wb_addr=out_addr[out_head];
    assign wb_data=out_word[out_head];
    assign wb_ack_ready=busy;
    wire result_fire=wb_valid&&wb_ready;
    wire slot_release=result_fire&&out_last[out_head];
    reg [5:0] quant_mask;
    reg [15:0] bank_data [0:5];
    always @* begin
        quant_mask=0;
        for(integer bank=0;bank<6;bank=bank+1) bank_data[bank]=0;
        for(integer row=0;row<6;row=row+1)
            if(quant_valid&&(!quant_tail||row<3)) begin
                quant_mask[bank_for(3'(row),quant_col)]=1;
                bank_data[bank_for(3'(row),quant_col)]=quant_data[16*row+:16];
            end
    end
    wire scratch_read=busy&&slot_complete[slot_read]&&(output_credit<2||result_fire)&&
        !quant_mask[scratch_lo]&&!quant_mask[scratch_hi];
    wire [15:0] result_q [0:5];
    for(genvar bank=0;bank<6;bank=bank+1) begin: result_memory
        wire wr=quant_mask[bank];
        wire rd=scratch_read&&(scratch_lo==bank||scratch_hi==bank);
        wire [6:0] address=wr?{quant_slot,quant_col}:{slot_read,read_col+4'(scratch_hi==bank)};
        RAMSP128X16 memory(.CLK(clk),.CEN(!(rd||wr)),.GWEN(!wr),
            .WEN({16{!wr}}),.A(address),.D(bank_data[bank]),.Q(result_q[bank]),
            .EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
    end

    wire starting=start&&!busy;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin busy<=0;done<=0;error<=0;phase<=0;end
        else begin
            phase<=!phase;
            if(starting) begin busy<=1;done<=0;error<=0;phase<=1;end
            if(return_fire&&ld_rsp_err) begin error<=1;busy<=0;end
            if(wb_ack_valid&&wb_ack_ready&&ack_count==14'd12671) begin busy<=0;done<=1;end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            sent<=0;source_tile<=0;source_offset<=0;load_tile<=0;load_offset<=0;
            input_words<=0;load_group_pair<=0;load_input_pair<=0;load_input_k<=0;
            tail_row<=0;tail_k<=0;ingress_count<=0;ingress_head<=0;ingress_tail<=0;in_flight<=0;
            page_live<=0;page_full<=0;oldest<=0;unit_active<=0;unit_index<=0;
            slot_alloc<=0;slot_read<=0;slot_count<=0;slot_complete<=0;read_index<=0;
            pending_result<=0;out_count<=0;out_head<=0;out_tail<=0;ack_count<=0;
            for(integer p=0;p<2;p=p+1) begin page_units[p]<=0;page_emits[p]<=0;end
        end else if(starting) begin
            sent<=0;source_tile<=0;source_offset<=0;load_tile<=0;load_offset<=0;
            input_words<=0;load_group_pair<=0;load_input_pair<=0;load_input_k<=0;
            tail_row<=0;tail_k<=0;ingress_count<=0;ingress_head<=0;ingress_tail<=0;in_flight<=0;
            page_live<=0;page_full<=0;oldest<=0;unit_active<=0;unit_index<=0;
            slot_alloc<=0;slot_read<=0;slot_count<=0;slot_complete<=0;read_index<=0;
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
                    if(source_offset+10'(accepted)==PACKET) begin
                        source_offset<=0;source_tile<=source_tile+5'd1;
                    end else source_offset<=source_offset+10'(accepted);
                end
            end
            if(return_fire) ingress[ingress_tail]<=ld_rsp_rdata;
            if(return_fire2) ingress[3'(ingress_tail+3'd1)]<=ld2_rsp_rdata;
            ingress_tail<=ingress_tail+3'(returned);
            ingress_head<=ingress_head+load_count;
            ingress_count<=ingress_count+4'(returned)-4'(load_count);
            in_flight<=in_flight+4'(accepted)-4'(returned);
            if(load_count!=0) begin
                if(input_words<12'd3168) begin
                    input_words<=input_words+12'(load_count);
                    if(main_load) begin
                        if(load_count==2) begin
                            load_input_pair<=next_input_pair==5?3'd0:next_input_pair+3'd1;
                            load_input_k<=next_input_k+6'(next_input_pair==5);
                            load_group_pair<=next_group_pair+3'(next_input_pair==5&&next_input_k==63);
                        end else begin
                            load_input_pair<=next_input_pair;load_input_k<=next_input_k;load_group_pair<=next_group_pair;
                        end
                    end else begin
                        tail_row<=tail_row==0?2'd2:tail_row-2'd1;
                        if(tail_row!=0) tail_k<=tail_k+6'd1;
                    end
                end else begin
                    if(load_offset+10'(load_count)==PACKET) begin
                        page_full[load_tile[0]]<=1;load_offset<=0;load_tile<=load_tile+5'd1;
                    end else load_offset<=load_offset+10'(load_count);
                    for(integer lane=0;lane<2;lane=lane+1)
                        if(load_count>lane&&load_offset+lane<20) begin
                            if(load_offset+lane<16) bias[load_tile[0]][4'(load_offset+lane)]<=front[lane];
                            else for(integer sub=0;sub<4;sub=sub+1)
                                shift[load_tile[0]][{2'(load_offset+lane),2'(sub)}]<=front[lane][8*sub+:8];
                        end
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
                pending_lo<=scratch_lo;pending_hi<=scratch_hi;pending_last<=scratch_last;
                pending_addr<=scratch_dest;read_index<=scratch_last?6'd0:read_index+6'd1;
                if(scratch_last) begin
                    slot_read<=slot_read+3'd1;slot_complete[slot_read]<=0;
                end
            end
            pending_result<=scratch_read;
            if(pending_result) begin
                out_word[out_tail]<={result_q[pending_hi],result_q[pending_lo]};
                out_addr[out_tail]<=pending_addr;out_last[out_tail]<=pending_last;out_tail<=!out_tail;
            end
            if(result_fire) out_head<=!out_head;
            out_count<=out_count+2'(pending_result)-2'(result_fire);
            if(wb_ack_valid&&wb_ack_ready) ack_count<=ack_count+14'd1;
        end
    end
endmodule



