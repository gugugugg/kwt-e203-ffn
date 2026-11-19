"""Derive the 4x16 core from the verified two-page datapath."""


def derive(core):
    def replace(old, new):
        nonlocal core
        assert core.count(old) == 1, old
        core = core.replace(old, new)

    def section(first, last, replacement):
        nonlocal core
        begin = core.index(first)
        core = core[:begin] + replacement + core[core.index(last, begin):]

    replace('    output reg busy, done, error,', '''    output reg busy, done, error,
    input wire [11:0] input_committed,
    input wire [13:0] parameter_committed,
    output reg output_priority,''')
    replace('    reg read_owner, owner_parameter;', '''    reg [1:0] read_count, owner_parameter;
    reg read_head, read_tail;''')
    replace("    wire [1:0] read_credit=ingress_count+{1'b0,read_owner};\n    assign ld_rsp_ready=read_owner;", "    wire [1:0] read_credit=ingress_count+read_count;\n    assign ld_rsp_ready=read_count!=0;")
    replace('(read_credit<2 || load_fire) && (!source_parameter || page_admit);',
            '(read_credit<2 || load_fire) && (source_parameter ?\n        page_admit && parameter_address<parameter_committed : source_input<input_committed);')
    replace('wire input_load_ok=((input_read_mask|quant_write_mask)&load_banks)==0;', 'wire input_load_ok=(input_read_mask&load_banks)==0;')
    replace("wire [1:0] side_full={slot_count[1]==16,slot_count[0]==12};", "wire [1:0] side_full={slot_count[1]==16,slot_count[0]==16};")
    replace("               !(age==1&&page_live[oldest[0]]&&page_units[oldest[0]]<13&&\n                 input_words<older_need&&older_need-input_words<(choice_pair==12 ? 12'd64 : 12'd128))&&\n               page_words[choice_tile[0]] >= (choice_pair==12 ? 10'd532 : 10'd404)&&", "               page_words[choice_tile[0]] == 10'd532&&")
    replace('    reg [11:0] older_need,choice_need;', '    reg [11:0] choice_need;')
    replace("        older_need=page_units[oldest[0]]==12 ? 12'd3168 :\n                   {page_units[oldest[0]]+4'd1,8'b0};\n", '')
    replace('        ((issue_banks&quant_write_mask)==0)&&\n        !(issue_tail&&issue_k==63&&phase)&&\n        !(!issue_tail&&!issue_side&&(phase||(emit_valid&&!emit_side)));', '        !(issue_tail&&issue_k==63&&phase)&&\n        !(!issue_tail&&!issue_side&&phase);')
    section('    function automatic [9:0] slot_address', '    reg pending_result', '')
    replace('reg [2:0] pending_bank_lo,pending_bank_hi;', 'reg [3:0] pending_bank_lo,pending_bank_hi;')
    section('    reg [13:0] result_count,ack_count;', '    reg scratch_read', '''    reg [13:0] ack_count;
    reg [3:0] ack_last, ack_side;
    reg [1:0] ack_head, ack_tail;
    wire write_ack=wb_ack_valid&&wb_ack_ready;
    wire [1:0] release_mask=write_ack&&ack_last[ack_head] ?
        (ack_side[ack_head]?2'b10:2'b01) : 2'b0;

''')
    section('    reg scratch_read', '    function automatic [3:0] advance_slot', '''    reg scratch_read,scratch_side,scratch_last;
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

''')
    replace('    function automatic [3:0] advance_slot(input side,input [3:0] slot);\n        advance_slot=(!side&&slot==11)?4\'d0:slot+4\'d1;', "    function automatic [3:0] advance_slot(input [3:0] slot);\n        advance_slot=slot+4'd1;")
    core = core.replace("advance_slot(1'(s),", 'advance_slot(').replace('advance_slot(scratch_side,', 'advance_slot(')
    core = core.replace('input_read_mask, input_write_mask, result_read_mask, quant_write_mask', 'input_read_mask, input_write_mask')
    core = core.replace('read_owner<=0;', 'read_count<=0;read_head<=0;read_tail<=0;')
    core = core.replace('result_count<=0;ack_count<=0;', 'ack_count<=0;ack_head<=0;ack_tail<=0;output_priority<=0;')
    replace('            case({source_fire,src_response})\n                2\'b10:read_owner<=1;\n                2\'b01:read_count<=0;read_head<=0;read_tail<=0;\n                default: ;\n            endcase', '''            if(occupancy>=24) output_priority<=1;
            else if(occupancy<=16) output_priority<=0;
            case({source_fire,src_response})
                2'b10:read_count<=read_count+2'd1;
                2'b01:read_count<=read_count-2'd1;
                default: ;
            endcase''')
    replace('                owner_parameter<=source_parameter;', '                owner_parameter[read_tail]<=source_parameter;read_tail<=!read_tail;')
    replace('ingress_kind[ingress_tail]<=owner_parameter;', 'ingress_kind[ingress_tail]<=owner_parameter[read_head];read_head<=!read_head;')
    replace('{input_q[pending_bank_hi],input_q[pending_bank_lo]}', '{result_q[pending_bank_hi],result_q[pending_bank_lo]}')
    replace('            if(result_fire) begin out_head<=!out_head;result_count<=result_count+14\'d1;end\n            if(wb_ack_valid&&wb_ack_ready) ack_count<=ack_count+14\'d1;', '''            if(result_fire) begin
                out_head<=!out_head;ack_last[ack_tail]<=out_last[out_head];
                ack_side[ack_tail]<=out_side[out_head];ack_tail<=ack_tail+2'd1;
            end
            if(write_ack) begin ack_head<=ack_head+2'd1;ack_count<=ack_count+14'd1;end''')
    replace('if(src_response&&ld_rsp_err)', 'if((src_response||write_ack)&&ld_rsp_err)')
    return core
