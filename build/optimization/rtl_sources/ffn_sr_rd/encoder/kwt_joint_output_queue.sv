module kwt_joint_output_queue(
    input wire clk,rst_n,clock_test_enable,restart,
    input wire push_valid,push_row1,
    input wire [15:0] push_low,push_high,
    output wire push_ready,
    input wire [14:0] item,
    input wire out_ready,out_pair_ready,
    output wire out_valid,out_pair_valid,
    output wire [15:0] out_data,out_high,
    output wire [1:0] pop_count,
    output reg [4:0] fifo_count
);
    reg [15:0] fifo[0:15];
    reg [3:0] fifo_write,fifo_read;
    reg [6:0] row0_write;
    reg [7:0] row0_count;
    reg [7:0] row1_write;
    reg [8:0] row1_count;
    reg [1:0] held_count,pending_count;
    reg pending_row1,pending_parity;
    reg [15:0] held_low,held_high;
    wire pair_pop=out_pair_ready&&(held_count==2);
    wire single_pop=out_ready&&(held_count!=0)&&!pair_pop;
    assign pop_count=pair_pop?2'd2:(single_pop?2'd1:2'd0);
    assign out_valid=held_count!=0;
    assign out_pair_valid=held_count==2;
    assign out_data=held_low;
    assign out_high=held_high;

    wire [1:0] capture0=pending_row1?2'd0:pending_count;
    wire [1:0] capture1=pending_row1?pending_count:2'd0;
    wire row1_room=({1'b0,row1_count}+10'd2<=10'd256+10'(capture1));
    wire row1_push=push_valid&&push_row1&&row1_room;
    wire [2:0] space=3'd2-3'(held_count)-3'(pending_count)+3'(pop_count);
    wire [15:0] next_item={1'b0,item}+16'(held_count)+16'(pending_count);
    wire next_row1=next_item[8];
    wire can_read=(space!=0)&&(next_item<16'd25344);
    wire read0=can_read&&!next_row1&&(row0_count>8'(capture0));
    wire read1=can_read&&next_row1&&!row1_push&&(row1_count>9'(capture1));
    wire read1_pair=read1&&(space>=2)&&(next_item[7:0]!=8'hff)&&
        (row1_count>=9'(capture1)+9'd2);
    wire [1:0] issue_count=read1_pair?2'd2:((read0||read1)?2'd1:2'd0);
    wire [7:0] read1_address=next_item[7:0];
    wire drain0=(fifo_count!=0)&&(row0_count<128)&&!read0;
    wire row0_room=({1'b0,fifo_count}+6'd2<=6'd16+6'(drain0));
    wire row0_push=push_valid&&!push_row1&&row0_room;
    assign push_ready=push_row1?row1_room:row0_room;

    wire [47:0] memory_data;
    generate for(genvar bank=0;bank<3;bank=bank+1)begin: row_stash
        wire en,we;
        wire [6:0] address;
        wire [15:0] data;
        wire memory_clk;
        if(bank==2)begin: first_row
            assign en=drain0||read0;
            assign we=drain0;
            assign address=drain0?row0_write:next_item[6:0];
            assign data=fifo[fifo_read];
        end else begin: second_row
            wire selected=read1&&(read1_pair||(read1_address[0]==1'(bank)));
            wire [7:0] selected_address=read1_address+
                8'((read1_address[0]!=1'(bank))&&read1_pair);
            assign en=row1_push||selected;
            assign we=row1_push;
            assign address=row1_push?row1_write[7:1]:selected_address[7:1];
            assign data=bank==0?push_low:push_high;
        end
        kwt_ffn_clock_gate gate(.clk(clk),.enable(en),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(en),.we(we),
            .addr(address),.wdata(data),.rdata(memory_data[bank*16+:16]));
    end endgenerate
    generate for(genvar bank=0;bank<8;bank=bank+1)begin: fifo_write_banks
        wire bank_write=row0_push&&(fifo_write[3:1]==3'(bank));
        wire bank_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(bank_write),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(bank_clk));
        for(genvar half=0;half<2;half=half+1)begin: words
            always @(posedge bank_clk)if(bank_write)fifo[bank*2+half]<=half==0?push_low:push_high;
        end
    end endgenerate

    wire [15:0] returned_low=pending_row1?
        (pending_parity?memory_data[31:16]:memory_data[15:0]):memory_data[47:32];
    wire [15:0] returned_high=pending_parity?memory_data[15:0]:memory_data[31:16];
    wire [1:0] remaining=held_count-pop_count;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            fifo_write<=0;fifo_read<=0;fifo_count<=0;
            row0_write<=0;row0_count<=0;
            row1_write<=0;row1_count<=0;
            held_count<=0;pending_count<=0;pending_row1<=0;pending_parity<=0;
            held_low<=0;held_high<=0;
        end else if(restart)begin
            fifo_write<=0;fifo_read<=0;fifo_count<=0;
            row0_write<=0;row0_count<=0;
            row1_write<=0;row1_count<=0;
            held_count<=0;pending_count<=0;
        end else begin
            if(row0_push)fifo_write<=fifo_write+4'd2;
            if(drain0)begin fifo_read<=fifo_read+1'b1;row0_write<=row0_write+1'b1;end
            fifo_count<=fifo_count+5'(row0_push?2:0)-5'(drain0);
            row0_count<=row0_count+8'(drain0)-8'(capture0);
                if(row1_push)row1_write<=row1_write+8'd2;
            row1_count<=row1_count+9'(row1_push?2:0)-9'(capture1);
                if(pop_count==1)held_low<=held_high;
            if(pending_count!=0)begin
                if(remaining==0)held_low<=returned_low;
                else held_high<=returned_low;
                if(pending_count==2)held_high<=returned_high;
            end
            held_count<=remaining+pending_count;
            pending_count<=issue_count;
            pending_row1<=read1;
            pending_parity<=read1_address[0];
        end
    end
endmodule
