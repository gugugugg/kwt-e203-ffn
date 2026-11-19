module mac_slice_REF(
 input wire clk,rst_n,clock_test_enable,
 input wire [31:0] input_rdata,
 input wire [1:0] input_read,
 input wire [255:0] weight_rdata,
 input wire tile_half,
 input wire [127:0] bias_pair,
 input wire [15:0] shift_return,seed_mask,mac_mask,
 input wire [3:0] quant_lane,
 output wire signed [15:0] result_low,result_high,
 output wire [575:0] accumulators
);
 reg [31:0] input_return;
 reg signed [35:0] accumulator[0:15];
 reg signed [7:0] shifts[0:15];
 generate for(genvar r=0;r<2;r=r+1)begin: input_rows
  wire return_clock;
  kwt_ffn_clock_gate gate(.clk(clk),.enable(input_read[r]),.test_enable(clock_test_enable||!rst_n),.gated_clk(return_clock));
  always_latch if(return_clock)input_return[r*16+:16]<=input_rdata[r*16+:16];
 end endgenerate
 wire [35:0] quant_bits=accumulator[quant_lane];
 wire [35:0] high_bits=accumulator[{1'b0,quant_lane}+5'd1];
 kwt_ffn_requantize quantizer(.value({{28{quant_bits[35]}},quant_bits}),.shift(shifts[quant_lane]),.result(result_low));
 kwt_ffn_requantize high_quantizer(.value({{28{high_bits[35]}},high_bits}),.shift(shifts[{1'b0,quant_lane}+5'd1]),.result(result_high));
generate for(genvar n=0;n<16;n=n+1)begin: lanes
 localparam integer R=n/8,C=n%8;
 wire signed [16:0] activation=$signed(input_return[R*16+:16]);
 wire signed [15:0] weight_value=$signed(weight_rdata[(int'(tile_half)*8+C)*16+:16]);
 wire accumulator_clk,shift_clk;
 if(C%2==0)begin: pair_gate
  kwt_ffn_clock_gate acc_gate(.clk(clk),.enable(mac_mask[n]||seed_mask[n]),.test_enable(clock_test_enable||!rst_n),.gated_clk(accumulator_clk));
  kwt_ffn_clock_gate shift_gate(.clk(clk),.enable(seed_mask[n]),.test_enable(clock_test_enable||!rst_n),.gated_clk(shift_clk));
 end else begin
  assign accumulator_clk=lanes[n-1].accumulator_clk;
  assign shift_clk=lanes[n-1].shift_clk;
 end
 wire [35:0] next_acc=accumulator[n]+36'(activation*weight_value);
 always @(posedge accumulator_clk or negedge rst_n)begin
  if(!rst_n)accumulator[n]<=0;
  else if(seed_mask[n])accumulator[n]<=36'($signed(bias_pair[(C%2)*64+:64]));
  else if(mac_mask[n])accumulator[n]<=next_acc;
 end
 always @(posedge shift_clk or negedge rst_n)begin
  if(!rst_n)shifts[n]<=0;
  else if(seed_mask[n])shifts[n]<=$signed(shift_return[(C%2)*8+:8]);
 end
 assign accumulators[n*36+:36]=accumulator[n];
end endgenerate
endmodule
