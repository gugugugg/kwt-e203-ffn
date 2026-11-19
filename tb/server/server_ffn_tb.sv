`timescale 1ns/1ps
module server_ffn_tb;
    reg clk = 0;
    reg rst_n = 0;
    wire [31:0] inspect_pc;
    wire sim_done, sim_pass;
    longint unsigned cycles = 0;
    kwt_cpu_soc dut(.*);
    always #3.333 clk = ~clk;
    initial begin
        repeat (32) @(negedge clk);
        rst_n = 1;
    end
    always @(negedge clk) begin
        if (rst_n) cycles = cycles + 1;
        if (sim_done) begin
            if (!sim_pass) $fatal(1, "Real E203 FFN firmware failed pc=%h", inspect_pc);
            $display("SERVER_FFN_PASS cycles=%0d", cycles);
            $finish;
        end
    end
endmodule
