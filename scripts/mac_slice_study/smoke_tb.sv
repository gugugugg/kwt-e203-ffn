`timescale 1ns/1ps
module smoke_tb;
reg clk=0;always #3.333 clk=~clk;
reg rst_n=0;
wire [575:0] a;
wire [15:0] lo,hi;
mac_slice_SHARE4 dut(.clk(clk),.rst_n(rst_n),.clock_test_enable(1'b0),.input_rdata(32'd0),.input_read(2'd0),
 .weight_rdata(256'd0),.tile_half(1'b0),.bias_pair(128'd0),.shift_return(16'd0),.seed_mask(16'd0),
 .mac_mask(16'd0),.quant_lane(4'd0),.result_low(lo),.result_high(hi),.accumulators(a));
initial begin $display("SMOKE_START");#20;rst_n=1;#20;$display("SMOKE_PASS");$finish;end
endmodule
