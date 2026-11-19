module kwt_joint_output_queue(
    input wire clk,rst_n,clock_test_enable,restart,
    input wire reserve,compute_generation,group_done,commit,
    input wire [2:0] valid_rows,
    input wire [5:0] write_address,
    input wire [255:0] write_words,
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
    reg [1:0] pending_column;
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
    reg [6:0] iw_committed_quartets;
    wire iw_tail_fill=(next_item[14:10]==5'd24)&&(issue_row==0)&&(generation_state[0]==FILL);
    wire [8:0] iw_committed_columns={iw_committed_quartets,2'b00};
    wire iw_tail_available=iw_tail_fill&&({1'b0,next_item[7:0]}<iw_committed_columns);
    wire iw_tail_pair=({1'b0,next_item[7:0]}+9'd1)<iw_committed_columns;
    wire want_issue=space!=0&&(next_item<16'd25344)&&
        ((generation_state[issue_generation]==READY)||iw_tail_available);
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)iw_committed_quartets<=0;
        else if(restart||reserve)iw_committed_quartets<=0;
        else if(commit&&valid_rows==3)iw_committed_quartets<={1'b0,write_address}+7'd1;
    end
    wire blocked_read=want_issue&&commit&&(3'(issue_row)<valid_rows);
    wire issue=want_issue&&!blocked_read;
    wire issue_pair=issue&&(space>=2)&&(next_item[7:0]!=8'hff)&&(!iw_tail_fill||iw_tail_pair);
    wire [1:0] issue_count=issue_pair?2'd2:(issue?2'd1:2'd0);

    wire [255:0] memory_data;
    wire [1:0] next_column=next_item[1:0]+2'd1;
    generate for(genvar bank=0;bank<16;bank=bank+1)begin: row_stash
        localparam integer ROW=bank/4, COLUMN=bank%4;
        wire write_en=commit&&(3'(ROW)<valid_rows);
        wire read_en=issue&&(issue_row==2'(ROW))&&
                     ((next_item[1:0]==2'(COLUMN))||(issue_pair&&(next_column==2'(COLUMN))));
        wire wrap=issue_pair&&(next_item[1:0]==2'd3)&&(COLUMN==0);
        wire [5:0] read_quartet=next_item[7:2]+6'(wrap);
        wire [6:0] address=write_en?{compute_generation,write_address}:{issue_generation,read_quartet};
        wire memory_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(write_en||read_en),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(write_en||read_en),.we(write_en),
            .addr(address),.wdata(write_words[bank*16+:16]),.rdata(memory_data[bank*16+:16]));
    end endgenerate

    wire [63:0] returned_row=memory_data[pending_row*64+:64];
    wire [1:0] pending_high_column=pending_column+2'd1;
    wire [1:0] fill_count=pending_count;
    wire [15:0] fill_low=returned_row[pending_column*16+:16];
    wire [15:0] fill_high=returned_row[pending_high_column*16+:16];
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
            pending_row<=0;pending_column<=0;
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
            pending_row<=issue_row;
            pending_column<=next_item[1:0];
        end
    end
endmodule
