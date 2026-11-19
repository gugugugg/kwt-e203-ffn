module kwt_joint_output_queue(
    input wire clk,rst_n,clock_test_enable,restart,
    input wire reserve,compute_generation,group_done,commit,
    input wire [2:0] valid_rows,
    input wire [6:0] write_address,
    input wire [127:0] write_words,
    output wire generation_empty,
    input wire [14:0] item,
    input wire out_ready,out_pair_ready,
    output wire out_valid,out_pair_valid,
    output wire [15:0] out_data,out_high,
    output wire [1:0] pop_count
);
    localparam [1:0] EMPTY=2'd0,FILL=2'd1,READY=2'd2;
    reg [1:0] generation_state[0:1];
    reg [2:0] held_count;
    reg [1:0] pending_count,pending_row;
    reg pending_generation,pending_parity;
    assign generation_empty=generation_state[compute_generation]==EMPTY;
    reg [15:0] held_data[0:3];
    reg [1:0] held_head,held_tail;
    wire [1:0] held_head_next=held_head+2'd1;
    wire [1:0] held_tail_next=held_tail+2'd1;
    wire pair_pop=out_pair_ready&&(held_count>=3'd2);
    wire single_pop=out_ready&&(held_count!=0)&&!pair_pop;
    assign pop_count=pair_pop?2'd2:(single_pop?2'd1:2'd0);
    assign out_valid=held_count!=0;
    assign out_pair_valid=held_count>=3'd2;
    assign out_data=held_data[held_head];
    assign out_high=held_data[held_head_next];

    wire [2:0] space=3'd4-held_count-3'(pending_count)+3'(pop_count);
    wire [15:0] next_item={1'b0,item}+16'(held_count)+16'(pending_count);
    wire [15:0] retired_end={1'b0,item}+16'(pop_count);
    wire retire_group=(pop_count!=0)&&((retired_end[10]!=item[10])||(retired_end==16'd25344));
    wire issue_generation=next_item[10];
    wire [1:0] issue_row=next_item[9:8];
    wire issue=space!=0&&(next_item<16'd25344)&&(generation_state[issue_generation]==READY);
    wire issue_pair=issue&&(space>=2)&&(next_item[7:0]!=8'hff);
    wire [1:0] issue_count=issue_pair?2'd2:(issue?2'd1:2'd0);

    wire [255:0] memory_data;
    generate for(genvar bank=0;bank<16;bank=bank+1)begin: row_stash
        localparam integer GEN=bank/8, ROW=(bank/2)%4, PARITY=bank%2;
        wire write_en=commit&&(compute_generation==1'(GEN))&&(3'(ROW)<valid_rows);
        wire read_en=issue&&(issue_generation==1'(GEN))&&(issue_row==2'(ROW))&&
                     (issue_pair||(next_item[0]==1'(PARITY)));
        wire [6:0] read_address=next_item[7:1]+7'(issue_pair&&next_item[0]&&(PARITY==0));
        wire [6:0] address=write_en?write_address:read_address;
        wire memory_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(write_en||read_en),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(write_en||read_en),.we(write_en),
            .addr(address),.wdata(write_words[(ROW*2+PARITY)*16+:16]),.rdata(memory_data[bank*16+:16]));
    end endgenerate

    wire [2:0] returned_bank={pending_generation,pending_row};
    wire [31:0] returned_pair=memory_data[returned_bank*32+:32];
    wire [1:0] fill_count=pending_count;
    wire [15:0] fill_low=pending_parity?returned_pair[31:16]:returned_pair[15:0];
    wire [15:0] fill_high=pending_parity?returned_pair[15:0]:returned_pair[31:16];
    generate for(genvar slot=0;slot<4;slot=slot+1)begin: return_words
        always @(posedge clk or negedge rst_n)begin
            if(!rst_n)held_data[slot]<=0;
            else if(!restart)begin
                if(fill_count!=0&&held_tail==2'(slot))held_data[slot]<=fill_low;
                else if(fill_count==2&&held_tail_next==2'(slot))held_data[slot]<=fill_high;
            end
        end
    end endgenerate
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            generation_state[0]<=EMPTY;generation_state[1]<=EMPTY;
            held_count<=0;pending_count<=0;held_head<=0;held_tail<=0;
            pending_generation<=0;pending_row<=0;pending_parity<=0;
        end else if(restart)begin
            generation_state[0]<=EMPTY;generation_state[1]<=EMPTY;
            held_count<=0;pending_count<=0;held_head<=0;held_tail<=0;
        end else begin
            if(retire_group)generation_state[item[10]]<=EMPTY;
            if(reserve)generation_state[compute_generation]<=FILL;
            if(group_done)generation_state[compute_generation]<=READY;
            held_head<=held_head+pop_count;
            held_tail<=held_tail+fill_count;
            held_count<=held_count-3'(pop_count)+3'(fill_count);
            pending_count<=issue_count;
            pending_generation<=issue_generation;
            pending_row<=issue_row;
            pending_parity<=next_item[0];
        end
    end
endmodule
