`timescale 1ns/1ps
module smoke_mac_tb;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst_n = 0;
    reg enable = 0;
    reg signed [7:0] a = 0;
    reg signed [7:0] b = 0;
    wire signed [23:0] acc;
    smoke_mac dut(.clk(clk), .rst_n(rst_n), .enable(enable), .a(a), .b(b), .acc(acc));

    task step(input signed [7:0] lhs, input signed [7:0] rhs,
              input run, input signed [23:0] expected);
        begin
            @(negedge clk);
            a = lhs; b = rhs; enable = run;
            @(posedge clk); #1;
            if (acc !== expected) $fatal(1, "acc=%0d expected=%0d", acc, expected);
        end
    endtask

    initial begin
        $dumpfile("build/environment/mac-smoke.vcd");
        $dumpvars(0, smoke_mac_tb);
        #1; rst_n = 1; #1; rst_n = 0; #1;
        if (acc !== 24'sd0) $fatal(1, "reset failed");
        @(negedge clk); rst_n = 1;
        step(8'sd3, 8'sd4, 1, 24'sd12);
        step(-8'sd2, 8'sd5, 1, 24'sd2);
        step(8'sd100, 8'sd100, 0, 24'sd2);
        @(negedge clk); rst_n = 0;
        #1; if (acc !== 24'sd0) $fatal(1, "second reset failed");
        @(negedge clk); rst_n = 1;
        step(-8'sd128, -8'sd128, 1, 24'sd16384);
        step(8'sd127, 8'sd127, 1, 24'sd32513);
        $display("PASS: reset, signed MAC, enable hold, consecutive inputs and boundary inputs");
        $finish;
    end
endmodule
