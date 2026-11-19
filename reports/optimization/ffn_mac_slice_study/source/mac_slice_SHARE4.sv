module mac_slice(
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
generate for(genvar r=0;r<2;r=r+1)begin: coefficient_rows
 wire signed [19:0] a={{4{input_return[r*16+15]}},input_return[r*16+:16]};
 wire signed [19:0] coeff[0:15];
 assign coeff[0]=20'sd0;assign coeff[1]=a;assign coeff[2]=a<<<1;assign coeff[4]=a<<<2;assign coeff[8]=a<<<3;
 assign coeff[3]=coeff[2]+coeff[1];
 assign coeff[5]=coeff[4]+coeff[1];
 assign coeff[6]=coeff[4]+coeff[2];
 assign coeff[7]=coeff[6]+coeff[1];
 assign coeff[9]=coeff[8]+coeff[1];
 assign coeff[10]=coeff[8]+coeff[2];
 assign coeff[11]=coeff[10]+coeff[1];
 assign coeff[12]=coeff[8]+coeff[4];
 assign coeff[13]=coeff[12]+coeff[1];
 assign coeff[14]=coeff[12]+coeff[2];
 assign coeff[15]=coeff[14]+coeff[1];
end endgenerate
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
 wire signed [19:0] digit0=coefficient_rows[R].coeff[weight_value[0+:4]];
 wire [35:0] part0={{16{digit0[19]}},digit0}<<0;
 wire signed [19:0] digit1=coefficient_rows[R].coeff[weight_value[4+:4]];
 wire [35:0] part1={{16{digit1[19]}},digit1}<<4;
 wire signed [19:0] digit2=coefficient_rows[R].coeff[weight_value[8+:4]];
 wire [35:0] part2={{16{digit2[19]}},digit2}<<8;
 wire [3:0] top=weight_value[15:12];
 wire [3:0] magnitude=top[3]?(~top+4'd1):top;
 wire signed [19:0] top_abs=coefficient_rows[R].coeff[magnitude];
 wire signed [19:0] top_value=top[3]?-top_abs:top_abs;
 wire [35:0] part3={{16{top_value[19]}},top_value}<<12;
 wire [35:0] stage1_s=part0^part1^part2;
 wire [35:0] stage1_c=((part0&part1)|(part0&part2)|(part1&part2))<<1;
 wire [35:0] stage2_s=stage1_s^stage1_c^part3;
 wire [35:0] stage2_c=((stage1_s&stage1_c)|(stage1_s&part3)|(stage1_c&part3))<<1;
 wire [35:0] stage3_s=stage2_s^stage2_c^accumulator[n];
 wire [35:0] stage3_c=((stage2_s&stage2_c)|(stage2_s&accumulator[n])|(stage2_c&accumulator[n]))<<1;
 wire [35:0] next_acc=stage3_s+stage3_c;
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
