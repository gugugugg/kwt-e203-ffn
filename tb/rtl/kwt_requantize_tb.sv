`timescale 1ns/1ps
`include "counts.svh"
module kwt_requantize_tb;
    reg signed [63:0] value;
    reg signed [7:0] shift;
    wire signed [15:0] result;
    reg [63:0] values[0:`REQUANT_CASES-1];
    reg [7:0] shifts[0:`REQUANT_CASES-1];
    reg [15:0] expected[0:`REQUANT_CASES-1];
    integer i;
    kwt_requantize dut(.*);
    initial begin
        $readmemh("build/rtl/vectors/requant_value.hex",values);
        $readmemh("build/rtl/vectors/requant_shift.hex",shifts);
        $readmemh("build/rtl/vectors/requant_expected.hex",expected);
        for(i=0;i<`REQUANT_CASES;i=i+1) begin
            value=values[i]; shift=shifts[i]; #1;
            if(result!==expected[i]) $fatal(1,"Requant mismatch %0d actual=%h expected=%h",i,result,expected[i]);
        end
        $display("PASS requantize: %0d signed RNE/saturation/left-shift/extreme cases",`REQUANT_CASES);
        $finish;
    end
endmodule
