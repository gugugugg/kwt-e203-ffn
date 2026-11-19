`timescale 1ns/1ps
`include "counts.svh"
module kwt_dot64_tb;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0, start_valid=0, in_valid=0, out_ready=0;
    wire start_ready, in_ready, out_valid, out_error;
    reg signed [63:0] bias=0;
    reg signed [7:0] shift=0;
    reg signed [15:0] a=0,b=0;
    wire signed [15:0] out_data;
    reg [15:0] aa[0:`DOT_CASES*64-1], bb[0:`DOT_CASES*64-1], expected[0:`DOT_CASES-1];
    reg [63:0] biases[0:`DOT_CASES-1];
    reg [7:0] shifts[0:`DOT_CASES-1];
    integer test_index,k,wait_count;
    kwt_dot64 dut(.*);
    initial begin
        $readmemh("build/rtl/vectors/dot_a.hex",aa);
        $readmemh("build/rtl/vectors/dot_b.hex",bb);
        $readmemh("build/rtl/vectors/dot_bias.hex",biases);
        $readmemh("build/rtl/vectors/dot_shift.hex",shifts);
        $readmemh("build/rtl/vectors/dot_expected.hex",expected);
        repeat(3) @(negedge clk); rst_n=1;
        // Abort an in-flight task; stale products/output must be flushed.
        @(negedge clk); start_valid=1;
        @(negedge clk); start_valid=0; in_valid=1; a=32767; b=-32768;
        repeat(10) @(negedge clk);
        rst_n=0; in_valid=0;
        repeat(2) @(negedge clk); rst_n=1;
        repeat(4) @(negedge clk);
        if(!start_ready || out_valid) $fatal(1,"Reset did not abort task");
        for(test_index=0;test_index<`DOT_CASES;test_index=test_index+1) begin
            @(negedge clk);
            if(!start_ready) $fatal(1,"Not ready between continuous tasks");
            bias=biases[test_index]; shift=shifts[test_index]; start_valid=1;
            @(negedge clk); start_valid=0;
            for(k=0;k<64;k=k+1) begin
                if(k%7==3) begin in_valid=0; @(negedge clk); end
                if(!in_ready) $fatal(1,"Unexpected input backpressure");
                in_valid=1; a=aa[test_index*64+k]; b=bb[test_index*64+k];
                @(negedge clk);
            end
            in_valid=0; wait_count=0;
            while(!out_valid && wait_count<20) begin @(negedge clk); wait_count=wait_count+1; end
            if(!out_valid || out_error || out_data!==expected[test_index])
                $fatal(1,"Dot mismatch case %0d actual=%h expected=%h error=%b",test_index,out_data,expected[test_index],out_error);
            repeat(3) begin
                @(negedge clk);
                if(!out_valid || start_ready || out_data!==expected[test_index]) $fatal(1,"Output not stable under stall");
            end
            out_ready=1; @(negedge clk); out_ready=0;
        end
        $display("PASS dot64: %0d cases, input gaps, output stalls, reset abort, continuous tasks",`DOT_CASES);
        $finish;
    end
    initial begin #10000000; $fatal(1,"dot64 timeout"); end
endmodule
