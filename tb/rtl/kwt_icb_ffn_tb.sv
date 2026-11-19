`timescale 1ns/1ps
module kwt_icb_ffn_tb;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0,icb_cmd_valid=0,icb_cmd_read=0,icb_rsp_ready=0;
    reg [7:0] icb_cmd_addr=0;
    reg [31:0] icb_cmd_wdata=0;
    reg [3:0] icb_cmd_wmask=15;
    wire icb_cmd_ready,icb_rsp_valid,icb_rsp_err;
    wire [31:0] icb_rsp_rdata;
    reg [15:0] inputs[0:6335],kernel[0:16383],bias[0:1023],expected[0:25343];
    integer address,index,transactions=0;
    reg [31:0] result;
    kwt_icb_ffn dut(.*);
    task transaction(input reg read, input reg [7:0] addr, input reg [31:0] data,
                     input reg [3:0] mask, input reg expect_error, output reg [31:0] rdata);
        integer delay_cycles;
        reg [31:0] held_data;
        reg held_error;
        begin
            @(negedge clk);
            icb_cmd_valid=1; icb_cmd_read=read; icb_cmd_addr=addr;
            icb_cmd_wdata=data; icb_cmd_wmask=mask; icb_rsp_ready=0;
            @(posedge clk);
            while(!icb_cmd_ready) @(posedge clk);
            @(negedge clk); icb_cmd_valid=0;
            while(!icb_rsp_valid) @(negedge clk);
            held_data=icb_rsp_rdata; held_error=icb_rsp_err;
            // Response backpressure must not replay command side effects.
            for(delay_cycles=0;delay_cycles<(transactions%4);delay_cycles=delay_cycles+1) begin
                @(negedge clk);
                if(!icb_rsp_valid || icb_rsp_rdata!==held_data || icb_rsp_err!==held_error)
                    $fatal(1,"ICB response changed during stall");
            end
            if(icb_rsp_err!==expect_error) $fatal(1,"ICB error response addr=%h",addr);
            rdata=icb_rsp_rdata; icb_rsp_ready=1;
            @(negedge clk); icb_rsp_ready=0;
            transactions=transactions+1;
        end
    endtask
    task write_word(input [7:0] addr,input [31:0] data);
        begin transaction(0,addr,data,15,0,result); end
    endtask
    initial begin
        $readmemh("build/rtl/vectors/task_00_input.hex",inputs);
        $readmemh("build/rtl/vectors/task_00_kernel.hex",kernel);
        $readmemh("build/rtl/vectors/task_00_bias.hex",bias);
        $readmemh("build/rtl/vectors/task_00_expected.hex",expected);
        repeat(3) @(negedge clk); rst_n=1;
        transaction(1,8'h03,0,15,1,result); // Unaligned address.
        transaction(0,8'h04,12,1,1,result); // Partial configuration write.
        transaction(1,8'hfc,0,15,1,result); // Undefined register.
        transaction(0,8'h08,3,15,1,result); // Invalid load kind.
        write_word(8'h04,16);
        write_word(8'h08,0); write_word(8'h0c,0);
        for(address=0;address<6336;address=address+1) write_word(8'h10,{16'd0,inputs[address]});
        write_word(8'h08,1); write_word(8'h0c,0);
        for(address=0;address<16384;address=address+1) write_word(8'h10,{16'd0,kernel[address]});
        write_word(8'h08,2); write_word(8'h0c,0);
        for(address=0;address<1024;address=address+1) write_word(8'h10,{16'd0,bias[address]});
        write_word(8'h00,1);
        // Writes that would corrupt a running task are rejected.
        transaction(0,8'h04,3,15,1,result);
        transaction(0,8'h00,1,15,1,result);
        transaction(0,8'h10,0,15,1,result);
        for(index=0;index<25344;index=index+1) begin
            transaction(1,8'h14,0,15,0,result);
            // At the beginning of each tile, index points at the next output even while computing.
            // Poll for valid before sampling its stable index/data pair.
            transaction(1,8'h1c,0,15,0,result);
            while(!(result&2)) transaction(1,8'h1c,0,15,0,result);
            transaction(1,8'h14,0,15,0,result);
            if(result!==32'(index)) $fatal(1,"ICB output ordering index=%0d actual=%0d",index,result);
            transaction(1,8'h18,0,15,0,result);
            if(result[15:0]!==expected[index]) $fatal(1,"ICB numerical mismatch %0d",index);
        end
        transaction(1,8'h00,0,15,0,result);
        if(result[2:0]!==3'b010) $fatal(1,"ICB completion status %h",result);
        $display("PASS ICB: full FFN task 25344 words bit exact, %0d transactions, response stalls and rejected invalid commands",transactions);
        $finish;
    end
    initial begin #100000000; $fatal(1,"ICB timeout"); end
endmodule
