module kwt_threebank_core (
    input wire clk, rst_n, start,
    output reg busy, done, error,
    input wire [11:0] input_committed,
    input wire [13:0] parameter_committed,
    output reg output_priority,
    output wire ld_cmd_valid, input wire ld_cmd_ready,
    output wire [31:0] ld_cmd_addr,
    input wire ld_rsp_valid, output wire ld_rsp_ready,
    input wire [31:0] ld_rsp_rdata, input wire ld_rsp_err,
    output wire wb_valid, input wire wb_ready,
    output wire [16:0] wb_addr, output wire [31:0] wb_data,
    input wire wb_ack_valid, output wire wb_ack_ready
);
    localparam [9:0] PACKET = 10'd532;
    localparam [13:0] OUTPUT_WORDS = 14'd12672;
    localparam [2:0] PARAM0=0, EARLY_INPUT=1, PARAM1=2, LATE_INPUT=3, OTHER_PARAM=4, LOADED=5;

    reg [2:0] source_phase;
    reg [4:0] source_tile, load_tile, oldest;
    reg [9:0] source_offset, load_offset;
    reg [13:0] parameter_address;
    reg [11:0] source_input, input_words;
    reg [1:0] tail_row;
    reg [5:0] tail_k;

    reg [1:0] page_live;
    reg [9:0] page_words [0:1];
    reg [3:0] page_units [0:1];
    reg [4:0] page_emits [0:1];
    reg signed [31:0] bias [0:1][0:15];
    reg signed [7:0] shift [0:1][0:15];
    wire source_parameter = source_phase==PARAM0 || source_phase==PARAM1 || source_phase==OTHER_PARAM;
    wire page_admit = source_offset!=0 || (!page_live[source_tile[0]] && source_tile<=oldest+5'd1);

    reg [1:0] read_count, owner_parameter;
    reg read_head, read_tail;
    reg [31:0] ingress_data [0:1];
    reg [1:0] ingress_kind;
    reg [1:0] ingress_count;
    reg ingress_head, ingress_tail;
    reg pack_valid;
    reg [31:0] pack_data;
    wire [31:0] load_word=ingress_data[ingress_head];
    wire load_parameter=ingress_kind[ingress_head];
    wire [9:0] weight_offset=load_offset-10'd20;
    wire [3:0] weight_first={weight_offset[2:1],2'b00};
    wire [6:0] weight_address={load_tile[0],weight_offset[8:3]};
    wire [1:0] read_credit=ingress_count+read_count;
    assign ld_rsp_ready=read_count!=0;
    wire src_response=ld_rsp_valid&&ld_rsp_ready;
    wire load_fire;
    assign ld_cmd_valid=busy && source_phase!=LOADED &&
        (read_credit<2 || load_fire) && (source_parameter ?
        page_admit && parameter_address<parameter_committed : source_input<input_committed);
    assign ld_cmd_addr=source_parameter ? {16'ha002,parameter_address,2'b00} :
                                         {18'h28000,source_input,2'b00};
    wire source_fire=ld_cmd_valid&&ld_cmd_ready;

    wire [15:0] weight_q [0:15];
    wire [15:0] input_q [0:7];
    wire [7:0] input_read_mask, input_write_mask;
    reg [9:0] input_address [0:7];
    reg [15:0] input_data [0:7];
    wire [15:0] weight_read;
    reg [2:0] load_bank0, load_bank1;
    reg [9:0] load_addr0, load_addr1;
    always @* begin
        if (input_words<12'd3072) begin
            load_bank0={input_words[0],input_words[1],1'b0};
            load_bank1={input_words[0],input_words[1],1'b1};
            load_addr0={input_words[11:8],input_words[7:2]};
            load_addr1=load_addr0;
        end else begin
            load_bank0={1'b0,tail_row};
            load_bank1=tail_row==2 ? 3'd0 : {1'b0,tail_row+2'd1};
            load_addr0={4'd12,tail_k};
            load_addr1={4'd12,tail_row==2 ? tail_k+6'd1 : tail_k};
        end
    end
    wire [7:0] load_banks=(8'b1<<load_bank0)|(8'b1<<load_bank1);
    wire input_load_ok=(input_read_mask&load_banks)==0;
    wire weight_load_ok=(weight_read & (16'h000f<<weight_first))==0;
    assign load_fire=busy && ingress_count!=0 &&
         (load_parameter ? (load_offset<20 || !pack_valid || weight_load_ok) : input_load_ok);
    wire weight_write=load_fire&&load_parameter&&load_offset>=20&&pack_valid;

    reg phase;
    reg unit_active;
    reg [4:0] unit_tile;
    reg [3:0] unit_pair;
    reg [6:0] unit_index;
    reg [3:0] unit_slot_a,unit_slot_b;
    reg [3:0] slot_alloc [0:1],slot_head [0:1],slot_read [0:1];
    reg [4:0] slot_count [0:1],unread_count [0:1];
    reg [4:0] slot_group [0:1][0:15];
    reg [3:0] slot_tile [0:1][0:15];
    reg [8:0] slot_sequence [0:1][0:15];
    reg [15:0] slot_complete [0:1];
    reg [8:0] next_sequence;
    reg [4:0] read_index [0:1];

    wire [1:0] side_full={slot_count[1]==16,slot_count[0]==16};
    reg choose;
    reg [4:0] selected_tile;
    reg [3:0] selected_pair;
    reg [1:0] blocked_sides;
    integer age;
    reg [4:0] choice_tile;
    reg [3:0] choice_pair;
    reg [11:0] choice_need;
    reg [1:0] choice_sides;
    always @* begin
        choose=0; selected_tile=0; selected_pair=0; blocked_sides=0;
        for(age=0;age<2;age=age+1) begin
            choice_tile=oldest+5'(age);
            choice_pair=page_units[choice_tile[0]];
            choice_need=choice_pair==12 ? 12'd3168 : {choice_pair+4'd1,8'b0};
            choice_sides=choice_pair==12 ? 2'b10 : 2'b11;
            if(busy&&!unit_active&&!choose&&choice_tile<16&&page_live[choice_tile[0]]&&choice_pair<13&&
               page_words[choice_tile[0]] == 10'd532&&
               input_words>=choice_need) begin
                if((side_full&choice_sides)!=0) blocked_sides=blocked_sides|(side_full&choice_sides);
                else if(choice_pair==12 || !phase) begin
                    choose=1; selected_tile=choice_tile; selected_pair=choice_pair;
                end
            end
        end
    end

    wire [4:0] issue_tile=unit_active?unit_tile:selected_tile;
    wire [3:0] issue_pair=unit_active?unit_pair:selected_pair;
    wire [6:0] issue_index=unit_active?unit_index:7'd0;
    wire issue_tail=issue_pair==12;
    wire issue_side=!issue_tail&&issue_index[0];
    wire [5:0] issue_k=issue_tail?issue_index[5:0]:issue_index[6:1];
    wire [3:0] issue_slot=issue_side?(unit_active?unit_slot_a:slot_alloc[0]):
                                     (unit_active?unit_slot_b:slot_alloc[1]);
    wire [7:0] issue_banks=issue_tail ? 8'h07 : issue_side ? 8'hf0 : 8'h0f;
    wire [9:0] issue_address={issue_pair,issue_k};
    wire [9:0] vector_end=10'd28+{1'b0,issue_k,3'b0};

    typedef struct packed {
        logic valid, tail, side;
        logic [3:0] tile, slot;
        logic [5:0] k;
    } token_t;
    token_t tags [0:32];
    reg [63:0] operands [1:31];

    reg quant_valid,quant_side,quant_tail,quant_tile;
    reg [3:0] quant_slot,quant_col;
    reg [63:0] quant_data;
    reg emit_valid,emit_side,emit_tail,emit_tile;
    reg [3:0] emit_slot,emit_col;
    wire issue = busy&&(unit_active||choose)&&page_words[issue_tile[0]]>=vector_end&&
        !(issue_tail&&issue_k==63&&phase)&&
        !(!issue_tail&&!issue_side&&phase);
    wire issue_last=issue_tail ? issue_index==63 : issue_index==127;
    wire [1:0] reserve_mask=choose ? (selected_pair==12 ? 2'b10 : 2'b11) : 2'b00;
    wire emit_group_done=quant_valid&&quant_col==15;
    wire page_release=busy&&oldest<16&&page_live[oldest[0]]&&
         (page_emits[oldest[0]]==25 ||
          (page_emits[oldest[0]]==24&&emit_group_done&&quant_tile==oldest[0]));

    integer pipe_index;
    always @(posedge clk) begin
        tags[0]<={issue,issue_tail,issue_side,issue_tile[3:0],issue_slot,issue_k};
        for(pipe_index=1;pipe_index<=32;pipe_index=pipe_index+1) tags[pipe_index]<=tags[pipe_index-1];
        if(tags[0].valid) operands[1]<=tags[0].side?
            {input_q[7],input_q[6],input_q[5],input_q[4]}:
            {input_q[3],input_q[2],input_q[1],input_q[0]};
        for(pipe_index=2;pipe_index<=31;pipe_index=pipe_index+1)
            if(tags[pipe_index-1].valid) operands[pipe_index]<=operands[pipe_index-1];
    end

    wire signed [35:0] emit_acc [0:15][0:3];
    wire signed [7:0] emit_shift [0:15];
    wire [15:0] column_emit;
    for(genvar col=0;col<16;col=col+1) begin: weight_columns
        localparam integer AGE=2*col;
        wire column_write=weight_write && (4'(col) & 4'hc)==weight_first;
        wire [63:0] weight_pack={load_word,pack_data};
        assign weight_read[col]=tags[AGE].valid&&(tags[AGE].tail||!tags[AGE].side);
        wire [6:0] address=column_write?weight_address:{tags[AGE].tile[0],tags[AGE].k};
        RAMSP128X16 memory(.CLK(clk),.CEN(!(weight_read[col]||column_write)),.GWEN(!column_write),
            .WEN({16{!column_write}}),.A(address),.D(weight_pack[(col%4)*16+:16]),
            .Q(weight_q[col]),.EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));

        wire [63:0] x=operands[AGE+1];
        wire execute=tags[AGE+1].valid;
        wire context_select=tags[AGE+1].side;
        wire [5:0] k=tags[AGE+1].k;
        wire seed_page=tags[AGE+1].tile[0];
        wire emit_context=tags[AGE+2].side;
        assign column_emit[col]=tags[AGE+2].valid&&tags[AGE+2].k==63;
        assign emit_shift[col]=shift[tags[AGE+2].tile[0]][col];
        wire execute_tail=tags[AGE+1].tail;
        wire [1:0] acc_write={execute&&context_select,execute&&!context_select};
        wire [1:0] acc_clock, fourth_clock;
        for(genvar ctx=0;ctx<2;ctx=ctx+1) begin: accum_clocks
            kwt_ffn_clock_gate group_gate(.clk(clk),.enable(acc_write[ctx]),
                .test_enable(1'b0),.gated_clk(acc_clock[ctx]));
            kwt_ffn_clock_gate fourth_gate(.clk(clk),.enable(acc_write[ctx]&&!execute_tail),
                .test_enable(1'b0),.gated_clk(fourth_clock[ctx]));
        end
        for(genvar row=0;row<4;row=row+1) begin: lanes
            reg signed [35:0] acc_a,acc_b;
            wire signed [15:0] value=x[row*16+:16];
            wire signed [31:0] product=value*$signed(weight_q[col]);
            wire signed [31:0] seed=bias[seed_page][col];
            wire signed [35:0] previous=k==0 ? {{4{seed[31]}},seed} :
                                                (context_select?acc_b:acc_a);
            wire signed [35:0] sum=previous+{{4{product[31]}},product};
            wire clk_a=(row==3)?fourth_clock[0]:acc_clock[0];
            wire clk_b=(row==3)?fourth_clock[1]:acc_clock[1];
            always @(posedge clk_a) acc_a<=sum;
            always @(posedge clk_b) acc_b<=sum;
            assign emit_acc[col][row]=emit_context?acc_b:acc_a;
        end
    end

    reg signed [35:0] quant_source [0:3];
    reg signed [7:0] quant_shift;
    wire [15:0] rounded [0:3];
    integer column, lane;
    always @* begin
        emit_valid=0;emit_side=0;emit_tail=0;emit_tile=0;emit_slot=0;emit_col=0;quant_shift=0;
        for(lane=0;lane<4;lane=lane+1) quant_source[lane]=0;
        for(column=0;column<16;column=column+1) if(column_emit[column]) begin
            emit_valid=1; emit_col=4'(column);
            emit_side=tags[2+2*column].side; emit_tail=tags[2+2*column].tail;
            emit_tile=tags[2+2*column].tile[0]; emit_slot=tags[2+2*column].slot;
            quant_shift=emit_shift[column];
            for(lane=0;lane<4;lane=lane+1) quant_source[lane]=emit_acc[column][lane];
        end
    end
    for(genvar r=0;r<4;r=r+1) begin: requantizers
        kwt_ffn_requantize quantizer(.value({{28{quant_source[r][35]}},quant_source[r]}),
                                   .shift(quant_shift),.result(rounded[r]));
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) quant_valid<=0;
        else quant_valid<=emit_valid;
    end
    always @(posedge clk) if(emit_valid) begin
        quant_side<=!emit_side;quant_tail<=emit_tail;quant_tile<=emit_tile;
        quant_slot<=emit_slot;quant_col<=emit_col;
        quant_data<={rounded[3],rounded[2],rounded[1],rounded[0]};
    end

    reg pending_result,pending_side,pending_last;
    reg [3:0] pending_bank_lo,pending_bank_hi;
    reg [16:0] pending_address;
    reg [1:0] out_count;
    reg out_head,out_tail;
    reg [31:0] out_word [0:1];
    reg [16:0] out_addr [0:1];
    reg [1:0] out_side,out_last;
    assign wb_valid=busy&&out_count!=0;
    assign wb_addr=out_addr[out_head];
    assign wb_data=out_word[out_head];
    wire result_fire=wb_valid&&wb_ready;
    assign wb_ack_ready=busy;
    reg [13:0] ack_count;
    reg [3:0] ack_last, ack_side;
    reg [1:0] ack_head, ack_tail;
    wire write_ack=wb_ack_valid&&wb_ack_ready;
    wire [1:0] release_mask=write_ack&&ack_last[ack_head] ?
        (ack_side[ack_head]?2'b10:2'b01) : 2'b0;

    reg scratch_read,scratch_side,scratch_last;
    reg [3:0] scratch_lo,scratch_hi;
    reg [6:0] scratch_addr;
    reg [16:0] scratch_dest;
    wire [1:0] output_credit=out_count+{1'b0,pending_result};
    reg [1:0] unread_side;
    reg [3:0] head_slot;
    reg [4:0] head_group;
    reg [6:0] result_row;
    wire [15:0] result_q [0:15];
    wire [5:0] occupancy={1'b0,slot_count[0]}+{1'b0,slot_count[1]};
    always @* begin
        unread_side={unread_count[1]!=0,unread_count[0]!=0};
        scratch_side=unread_side[1]&&(!unread_side[0]||
            slot_sequence[1][slot_read[1]]<slot_sequence[0][slot_read[0]]);
        head_slot=slot_read[scratch_side];
        head_group=slot_group[scratch_side][head_slot];
        scratch_lo={read_index[scratch_side][4:3],read_index[scratch_side][0],1'b0};
        scratch_hi=scratch_lo^4'd1;
        scratch_addr={scratch_side,head_slot,read_index[scratch_side][2:1]};
        scratch_read=busy&&(|unread_side)&&slot_complete[scratch_side][head_slot]&&
            (output_credit<2||result_fire)&&!(quant_valid&&quant_col[1]==scratch_lo[1]);
        scratch_last=read_index[scratch_side]==(head_group==24?5'd23:5'd31);
        result_row={head_group,read_index[scratch_side][4:3]};
        scratch_dest=17'd16384+{3'b0,result_row,slot_tile[scratch_side][head_slot],read_index[scratch_side][2:0]};
    end
    wire [1:0] scratch_finish=scratch_read&&scratch_last ?
        (scratch_side?2'b10:2'b01):2'b00;

    assign input_read_mask=issue?issue_banks:0;
    assign input_write_mask=load_fire&&!load_parameter?load_banks:0;
    integer bank;
    always @* begin
        for(bank=0;bank<8;bank=bank+1) begin
            input_address[bank]=issue_address;
            input_data[bank]=0;
            if(input_write_mask[bank]) begin
                input_address[bank]=3'(bank)==load_bank0?load_addr0:load_addr1;
                input_data[bank]=3'(bank)==load_bank0?load_word[15:0]:load_word[31:16];
            end
        end
    end
    for(genvar bank_id=0;bank_id<8;bank_id=bank_id+1) begin: input_banks
        wire en=input_read_mask[bank_id]||input_write_mask[bank_id];
        wire we=input_write_mask[bank_id];
        RAMSP1024X16 memory(.CLK(clk),.CEN(!en),.GWEN(!we),.WEN({16{!we}}),
            .A(input_address[bank_id]),.D(input_data[bank_id]),.Q(input_q[bank_id]),
            .EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
    end
    for(genvar bank_id=0;bank_id<16;bank_id=bank_id+1) begin: result_banks
        wire we=quant_valid&&quant_col[1:0]==2'(bank_id)&&(!quant_tail||bank_id<12);
        wire re=scratch_read&&(scratch_lo==4'(bank_id)||scratch_hi==4'(bank_id));
        wire [6:0] address=we?{quant_side,quant_slot,quant_col[3:2]}:scratch_addr;
        RAMSP128X16 memory(.CLK(clk),.CEN(!(re||we)),.GWEN(!we),.WEN({16{!we}}),
            .A(address),.D(quant_data[16*(bank_id/4)+:16]),.Q(result_q[bank_id]),
            .EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1));
    end

    function automatic [3:0] advance_slot(input [3:0] slot);
        advance_slot=slot+4'd1;
    endfunction

    integer s;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin busy<=0;done<=0;error<=0;phase<=0;end
        else begin
            phase<=!phase;
            if(start&&!busy) begin busy<=1;done<=0;error<=0;phase<=1;end
            if((src_response||write_ack)&&ld_rsp_err) begin error<=1;busy<=0;end
            if(wb_ack_valid&&wb_ack_ready&&ack_count==OUTPUT_WORDS-1) begin busy<=0;done<=1;end
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            source_phase<=PARAM0;source_tile<=0;source_offset<=0;parameter_address<=0;source_input<=0;
            load_tile<=0;load_offset<=0;input_words<=0;tail_row<=0;tail_k<=0;
            read_count<=0;read_head<=0;read_tail<=0;ingress_count<=0;ingress_head<=0;ingress_tail<=0;pack_valid<=0;
            page_live<=0;oldest<=0;unit_active<=0;unit_index<=0;
            next_sequence<=0;pending_result<=0;out_count<=0;out_head<=0;out_tail<=0;
            ack_count<=0;ack_head<=0;ack_tail<=0;output_priority<=0;
            for(s=0;s<2;s=s+1) begin
                page_words[s]<=0;page_units[s]<=0;page_emits[s]<=0;
                slot_alloc[s]<=0;slot_head[s]<=0;slot_read[s]<=0;slot_count[s]<=0;
                unread_count[s]<=0;slot_complete[s]<=0;read_index[s]<=0;
            end
        end else if(start&&!busy) begin
            source_phase<=PARAM0;source_tile<=0;source_offset<=0;parameter_address<=0;source_input<=0;
            load_tile<=0;load_offset<=0;input_words<=0;tail_row<=0;tail_k<=0;
            read_count<=0;read_head<=0;read_tail<=0;ingress_count<=0;ingress_head<=0;ingress_tail<=0;pack_valid<=0;
            page_live<=0;oldest<=0;unit_active<=0;unit_index<=0;
            next_sequence<=0;pending_result<=0;out_count<=0;out_head<=0;out_tail<=0;
            ack_count<=0;ack_head<=0;ack_tail<=0;output_priority<=0;
            for(s=0;s<2;s=s+1) begin
                page_words[s]<=0;page_units[s]<=0;page_emits[s]<=0;
                slot_alloc[s]<=0;slot_head[s]<=0;slot_read[s]<=0;slot_count[s]<=0;
                unread_count[s]<=0;slot_complete[s]<=0;read_index[s]<=0;
            end
        end else if(busy) begin
            if(page_release) begin page_live[oldest[0]]<=0;oldest<=oldest+5'd1;end
            if(occupancy>=24) output_priority<=1;
            else if(occupancy<=16) output_priority<=0;
            case({source_fire,src_response})
                2'b10:read_count<=read_count+2'd1;
                2'b01:read_count<=read_count-2'd1;
                default: ;
            endcase
            if(source_fire) begin
                owner_parameter[read_tail]<=source_parameter;read_tail<=!read_tail;
                if(source_parameter) begin
                    if(source_offset==0) begin
                        page_live[source_tile[0]]<=1;page_words[source_tile[0]]<=0;
                        page_units[source_tile[0]]<=0;page_emits[source_tile[0]]<=0;
                    end
                    parameter_address<=parameter_address+14'd1;
                    if(source_offset==PACKET-1) begin
                        source_offset<=0; source_tile<=source_tile+5'd1;
                        if(source_phase==PARAM0) source_phase<=EARLY_INPUT;
                        if(source_phase==PARAM1) source_phase<=LATE_INPUT;
                        if(source_tile==15) source_phase<=LOADED;
                    end else source_offset<=source_offset+10'd1;
                end else begin
                    source_input<=source_input+12'd1;
                    if(source_input==1023) source_phase<=PARAM1;
                    if(source_input==3167) source_phase<=OTHER_PARAM;
                end
            end
            if(src_response) begin
                ingress_data[ingress_tail]<=ld_rsp_rdata;ingress_kind[ingress_tail]<=owner_parameter[read_head];read_head<=!read_head;
                ingress_tail<=!ingress_tail;
            end
            if(load_fire) begin
                ingress_head<=!ingress_head;
                if(!load_parameter) begin
                    input_words<=input_words+12'd1;
                    if(input_words>=3072) begin
                        tail_row<=tail_row==0?2'd2:tail_row-2'd1;
                        if(tail_row!=0) tail_k<=tail_k+6'd1;
                    end
                end else if(load_offset<20) begin
                    page_words[load_tile[0]]<=load_offset+10'd1;load_offset<=load_offset+10'd1;
                    if(load_offset<16) bias[load_tile[0]][load_offset[3:0]]<=load_word;
                    else for(integer i=0;i<4;i=i+1)
                        shift[load_tile[0]][{load_offset[1:0],2'(i)}]<=load_word[8*i+:8];
                end else if(!pack_valid) begin
                    pack_valid<=1;pack_data<=load_word;
                end else begin
                    pack_valid<=0;page_words[load_tile[0]]<=load_offset+10'd2;
                    if(load_offset==PACKET-2) begin load_offset<=0;load_tile<=load_tile+5'd1;end
                    else load_offset<=load_offset+10'd2;
                end
            end
            case({src_response,load_fire})
                2'b10:ingress_count<=ingress_count+2'd1;
                2'b01:ingress_count<=ingress_count-2'd1;
                default: ;
            endcase

            if(choose) begin
                page_units[selected_tile[0]]<=selected_pair+4'd1;
                unit_active<=1;unit_tile<=selected_tile;unit_pair<=selected_pair;
                unit_slot_a<=slot_alloc[0];unit_slot_b<=slot_alloc[1];unit_index<=0;
                next_sequence<=next_sequence+(selected_pair==12?9'd1:9'd2);
                for(s=0;s<2;s=s+1) if(reserve_mask[s]) begin
                    slot_group[s][slot_alloc[s]]<={selected_pair,(s==0)};
                    slot_tile[s][slot_alloc[s]]<=selected_tile[3:0];
                    slot_sequence[s][slot_alloc[s]]<=next_sequence+9'(s==0);
                    slot_complete[s][slot_alloc[s]]<=0;
                    slot_alloc[s]<=advance_slot(slot_alloc[s]);
                end
            end
            if(issue) begin
                unit_index<=issue_index+7'd1;
                if(issue_last) unit_active<=0;
            end
            if(emit_group_done) begin
                slot_complete[quant_side][quant_slot]<=1;
                page_emits[quant_tile]<=page_emits[quant_tile]+5'd1;
            end
            if(scratch_read) begin
                pending_side<=scratch_side;pending_last<=scratch_last;
                pending_bank_lo<=scratch_lo;pending_bank_hi<=scratch_hi;pending_address<=scratch_dest;
                read_index[scratch_side]<=scratch_last?5'd0:read_index[scratch_side]+5'd1;
                if(scratch_last) slot_read[scratch_side]<=advance_slot(slot_read[scratch_side]);
            end
            pending_result<=scratch_read;
            if(pending_result) begin
                out_word[out_tail]<={result_q[pending_bank_hi],result_q[pending_bank_lo]};
                out_addr[out_tail]<=pending_address;out_side[out_tail]<=pending_side;
                out_last[out_tail]<=pending_last;out_tail<=!out_tail;
            end
            if(result_fire) begin
                out_head<=!out_head;ack_last[ack_tail]<=out_last[out_head];
                ack_side[ack_tail]<=out_side[out_head];ack_tail<=ack_tail+2'd1;
            end
            if(write_ack) begin ack_head<=ack_head+2'd1;ack_count<=ack_count+14'd1;end
            case({pending_result,result_fire})
                2'b10:out_count<=out_count+2'd1;
                2'b01:out_count<=out_count-2'd1;
                default: ;
            endcase
            for(s=0;s<2;s=s+1) begin
                if(release_mask[s]) slot_head[s]<=advance_slot(slot_head[s]);
                case({reserve_mask[s],release_mask[s]})
                    2'b10:slot_count[s]<=slot_count[s]+5'd1;
                    2'b01:slot_count[s]<=slot_count[s]-5'd1;
                    default: ;
                endcase
                case({reserve_mask[s],scratch_finish[s]})
                    2'b10:unread_count[s]<=unread_count[s]+5'd1;
                    2'b01:unread_count[s]<=unread_count[s]-5'd1;
                    default: ;
                endcase
            end
        end
    end
endmodule

