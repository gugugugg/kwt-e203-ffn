module mac_slice_top(
 input wire clk,rst_n,clock_test_enable,
 input wire [31:0] input_rdata,input wire [1:0] input_read,
 input wire [255:0] weight_rdata,input wire tile_half,
 input wire [127:0] bias_pair,input wire [15:0] shift_return,seed_mask,mac_mask,
 input wire [3:0] quant_lane,
 output wire signed [15:0] result_low,result_high
);
 mac_slice u_slice(.*,.accumulators());
endmodule
