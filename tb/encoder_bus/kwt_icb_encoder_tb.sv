`timescale 1ns/1ps
module kwt_icb_encoder_tb;
    reg clk=0,rst_n=0;
    always #5 clk=~clk;
    reg cmd_valid=0,cmd_read=1,rsp_ready=0;
    reg [7:0] cmd_addr=0;
    reg [31:0] cmd_data=0;
    reg [3:0] cmd_mask=15;
    wire cmd_ready,rsp_valid,rsp_err;
    wire [31:0] rsp_data;
    wire unused_trace_valid;
    wire [3:0] unused_trace_layer,unused_trace_stage;
    wire [14:0] unused_trace_index;
    wire signed [63:0] unused_trace_data;
    kwt_icb_encoder dut(.clk(clk),.rst_n(rst_n),.icb_cmd_valid(cmd_valid),.icb_cmd_ready(cmd_ready),
        .icb_cmd_addr(cmd_addr),.icb_cmd_read(cmd_read),.icb_cmd_wdata(cmd_data),.icb_cmd_wmask(cmd_mask),
        .icb_rsp_valid(rsp_valid),.icb_rsp_ready(rsp_ready),.icb_rsp_rdata(rsp_data),.icb_rsp_err(rsp_err),
        .trace_valid(unused_trace_valid),.trace_layer(unused_trace_layer),.trace_stage(unused_trace_stage),
        .trace_index(unused_trace_index),.trace_data(unused_trace_data));
    integer cases=0;
    reg [31:0] value;
    task automatic access(input bit reading,input [7:0] addr,input [31:0] data,input [3:0] mask,input bit expect_error,output reg [31:0] result);
        reg [31:0] held;
        reg held_error;
        begin
            @(negedge clk); cmd_valid=1; cmd_read=reading; cmd_addr=addr; cmd_data=data; cmd_mask=mask;
            #1;
            while(!cmd_ready) begin @(negedge clk); #1; end
            @(negedge clk); cmd_valid=0;
            while(!rsp_valid) @(negedge clk);
            held=rsp_data; held_error=rsp_err;
            repeat(4) begin
                @(negedge clk);
                if(!rsp_valid||rsp_data!==held||rsp_err!==held_error||cmd_ready) $fatal(1,"ICB response/backpressure failure");
            end
            if(held_error!==expect_error) $fatal(1,"ICB wrong error addr=%h got=%b expected=%b",addr,held_error,expect_error);
            result=held; rsp_ready=1; @(negedge clk); rsp_ready=0; cases=cases+1;
        end
    endtask
    initial begin
        repeat(3) @(negedge clk); rst_n=1;
        access(1,8'h28,0,15,0,value); if(value!==32'h4b574531) $fatal(1,"ID mismatch");
        access(0,8'h10,1,15,1,value); // Must fail promptly while clearing, not block CPU.
        access(1,8'hfc,0,15,1,value);
        access(1,8'h29,0,15,1,value);
        access(0,8'h08,0,1,1,value);
        wait(dut.core_start_ready);
        access(0,0,1,15,0,value); // Incomplete input/LUT start is rejected by the core.
        access(1,4,0,15,0,value); if(!value[7]||!value[6]) $fatal(1,"Missing incomplete-start error/done");
        access(1,8'h24,0,15,0,value); if(!value[7]) $fatal(1,"EVENT failed to return core error");
        access(0,0,2,15,0,value); wait(dut.core_start_ready);
        access(1,4,0,15,0,value); if(value[7]) $fatal(1,"Reset retained core error");
        access(0,8'h08,5,15,1,value);
        access(0,8'h0c,65536,15,1,value);
        access(0,8'h18,1,15,1,value);
        access(1,8'h1c,0,15,1,value);
        access(0,8'h08,0,15,0,value);
        access(0,8'h0c,1,15,0,value);
        access(0,8'h10,32'h1357,15,0,value);
        access(1,8'h0c,0,15,0,value); if(value!=2) $fatal(1,"Held response repeated a DATA side effect");
        access(1,4,0,15,0,value); if(!value[7]) $fatal(1,"Skipped address was not rejected");
        access(1,8'h20,0,15,1,value); // Output wait must unblock on a core error.
        access(0,0,2,15,0,value); wait(dut.core_start_ready);
        access(0,8'h08,0,15,0,value); access(0,8'h0c,0,15,0,value); access(0,8'h10,32'hffff,15,0,value);
        access(1,4,0,15,0,value); if(value[7]) $fatal(1,"Clean sequential load failed");
        $display("ICB_ENCODER_PROTOCOL_PASS cases=%0d response_hold=4",cases); $finish;
    end
    initial begin #10000000; $fatal(1,"ICB test timeout"); end
endmodule
