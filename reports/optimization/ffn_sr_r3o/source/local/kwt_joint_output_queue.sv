module kwt_joint_output_queue(
    input wire clk,rst_n,clock_test_enable,restart,
    input wire push_valid,
    input wire [1:0] push_row,
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
    reg [6:0] row0_write,row0_read;
    reg [7:0] row0_count;
    reg [7:0] row_write[1:2],row_read[1:2];
    reg [8:0] row_count[1:2];
    reg [1:0] held_count,pending_count,pending_row,retiring_row;
    reg pending_parity;
    reg [15:0] held_low,held_high;
    wire pair_pop=out_pair_ready&&(held_count==2);
    wire single_pop=out_ready&&(held_count!=0)&&!pair_pop;
    assign pop_count=pair_pop?2'd2:(single_pop?2'd1:2'd0);
    assign out_valid=held_count!=0;
    assign out_pair_valid=held_count==2;
    assign out_data=held_low;
    assign out_high=held_high;

    function automatic [1:0] following_row(input [1:0] current);
        following_row=(current==2)?2'd0:current+2'd1;
    endfunction
    wire [8:0] retiring_column={1'b0,item[7:0]}+9'(pop_count);
    wire [1:0] capture0=(pending_row==0)?pending_count:2'd0;
    wire [2:0] space=3'd2-3'(held_count)-3'(pending_count)+3'(pop_count);
    wire [15:0] next_item={1'b0,item}+16'(held_count)+16'(pending_count);
    // At most four reserved words can move the address into the next row.
    wire [1:0] next_row=(next_item[8]!=item[8])?following_row(retiring_row):retiring_row;
    wire can_read=(space!=0)&&(next_item<16'd25344);
    wire read0=can_read&&(next_row==0)&&(row0_count>8'(capture0));
    wire drain0=(fifo_count!=0)&&(row0_count<128)&&!read0;
    wire row0_room=({1'b0,fifo_count}+6'd2<=6'd16+6'(drain0));
    wire row0_push=push_valid&&(push_row==0)&&row0_room;

    wire [1:0] capture[1:2];
    wire [7:0] read_address[1:2];
    wire room[1:2],row_push[1:2],row_read_en[1:2],read_pair[1:2];
    wire [79:0] memory_data;
    generate for(genvar row=1;row<=2;row=row+1) begin: younger_rows
        assign capture[row]=(pending_row==2'(row))?pending_count:2'd0;
        assign room[row]=({1'b0,row_count[row]}+10'd2<=10'd256+10'(capture[row]));
        assign row_push[row]=push_valid&&(push_row==2'(row))&&room[row];
        assign read_address[row]=row_read[row]+8'(capture[row]);
        assign row_read_en[row]=can_read&&(next_row==2'(row))&&!row_push[row]&&
                                (row_count[row]>9'(capture[row]));
        assign read_pair[row]=row_read_en[row]&&(space>=2)&&(next_item[7:0]!=8'hff)&&
                              (row_count[row]>=9'(capture[row])+9'd2);
    end endgenerate
    assign push_ready=(push_row==0)?row0_room:((push_row==1)?room[1]:room[2]);
    wire [1:0] issue_count=(read_pair[1]||read_pair[2])?2'd2:
                            ((read0||row_read_en[1]||row_read_en[2])?2'd1:2'd0);

    generate for(genvar bank=0;bank<5;bank=bank+1)begin: row_stash
        wire en,we;
        wire [6:0] address;
        wire [15:0] data;
        wire memory_clk;
        if(bank==2)begin: first_row
            assign en=drain0||read0;
            assign we=drain0;
            assign address=drain0?row0_write:(row0_read+7'(capture0));
            assign data=fifo[fifo_read];
        end else begin: paired_row
            localparam integer ROW=(bank<2)?1:2;
            localparam integer PARITY=(bank<2)?bank:(bank-3);
            wire selected=row_read_en[ROW]&&(read_pair[ROW]||(read_address[ROW][0]==1'(PARITY)));
            wire [7:0] selected_address=read_address[ROW]+
                8'((read_address[ROW][0]!=1'(PARITY))&&read_pair[ROW]);
            assign en=row_push[ROW]||selected;
            assign we=row_push[ROW];
            assign address=row_push[ROW]?row_write[ROW][7:1]:selected_address[7:1];
            assign data=(PARITY==0)?push_low:push_high;
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

    wire [31:0] returned_pair=(pending_row==1)?memory_data[31:0]:memory_data[79:48];
    wire [15:0] returned_low=(pending_row==0)?memory_data[47:32]:
        (pending_parity?returned_pair[31:16]:returned_pair[15:0]);
    wire [15:0] returned_high=pending_parity?returned_pair[15:0]:returned_pair[31:16];
    wire [1:0] remaining=held_count-pop_count;
    integer row_index;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin
            fifo_write<=0;fifo_read<=0;fifo_count<=0;
            row0_write<=0;row0_read<=0;row0_count<=0;
            for(row_index=1;row_index<=2;row_index=row_index+1)begin
                row_write[row_index]<=0;row_read[row_index]<=0;row_count[row_index]<=0;
            end
            held_count<=0;pending_count<=0;pending_row<=0;pending_parity<=0;retiring_row<=0;
            held_low<=0;held_high<=0;
        end else if(restart)begin
            fifo_write<=0;fifo_read<=0;fifo_count<=0;
            row0_write<=0;row0_read<=0;row0_count<=0;
            for(row_index=1;row_index<=2;row_index=row_index+1)begin
                row_write[row_index]<=0;row_read[row_index]<=0;row_count[row_index]<=0;
            end
            held_count<=0;pending_count<=0;retiring_row<=0;
        end else begin
            if(retiring_column[8])retiring_row<=following_row(retiring_row);
            if(row0_push)fifo_write<=fifo_write+4'd2;
            if(drain0)begin fifo_read<=fifo_read+1'b1;row0_write<=row0_write+1'b1;end
            fifo_count<=fifo_count+5'(row0_push?2:0)-5'(drain0);
            row0_count<=row0_count+8'(drain0)-8'(capture0);
            row0_read<=row0_read+7'(capture0);
            for(row_index=1;row_index<=2;row_index=row_index+1)begin
                if(row_push[row_index])row_write[row_index]<=row_write[row_index]+8'd2;
                row_count[row_index]<=row_count[row_index]+9'(row_push[row_index]?2:0)-9'(capture[row_index]);
                row_read[row_index]<=row_read[row_index]+8'(capture[row_index]);
            end
            if(pop_count==1)held_low<=held_high;
            if(pending_count!=0)begin
                if(remaining==0)held_low<=returned_low;
                else held_high<=returned_low;
                if(pending_count==2)held_high<=returned_high;
            end
            held_count<=remaining+pending_count;
            pending_count<=issue_count;
            pending_row<=next_row;
            pending_parity<=(next_row==1)?read_address[1][0]:read_address[2][0];
        end
    end
endmodule
