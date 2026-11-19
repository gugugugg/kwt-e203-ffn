"""Extract the two fixed MAC slices from the published IR contract."""
from pathlib import Path
import json
import shutil

ROOT=Path('E:/xpian')
OUT=ROOT/'build/optimization/ffn_mac_slice_study'
REPORT=ROOT/'reports/optimization/ffn_mac_slice_study'
IR=ROOT/'build/optimization/rtl_sources/ffn_lp_IR'

HEADER='''module mac_slice(
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
'''

def share_tables():
    lines=['generate for(genvar r=0;r<2;r=r+1)begin: coefficient_rows',
           ' wire signed [19:0] a={{4{input_return[r*16+15]}},input_return[r*16+:16]};',
           ' wire signed [19:0] coeff[0:15];',
           " assign coeff[0]=20'sd0;assign coeff[1]=a;assign coeff[2]=a<<<1;assign coeff[4]=a<<<2;assign coeff[8]=a<<<3;"]
    for k,l,r in [(3,2,1),(5,4,1),(6,4,2),(7,6,1),(9,8,1),(10,8,2),(11,10,1),(12,8,4),(13,12,1),(14,12,2),(15,14,1)]:
        lines.append(' assign coeff[%d]=coeff[%d]+coeff[%d];'%(k,l,r))
    lines.append('end endgenerate')
    return '\n'.join(lines)+'\n'

def csa(out,a,b,c):
    return ' wire [35:0] %s_s=%s^%s^%s;\n wire [35:0] %s_c=((%s&%s)|(%s&%s)|(%s&%s))<<1;\n'%(out,a,b,c,out,a,b,a,c,b,c)

def rtl(shared):
    s=HEADER+(share_tables() if shared else '')
    s+='''generate for(genvar n=0;n<16;n=n+1)begin: lanes
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
'''
    if shared:
        for d in range(3):
            s+=' wire signed [19:0] digit%d=coefficient_rows[R].coeff[weight_value[%d+:4]];\n'%(d,4*d)
            s+=' wire [35:0] part%d={{16{digit%d[19]}},digit%d}<<%d;\n'%(d,d,d,4*d)
        s+=''' wire [3:0] top=weight_value[15:12];
 wire [3:0] magnitude=top[3]?(~top+4'd1):top;
 wire signed [19:0] top_abs=coefficient_rows[R].coeff[magnitude];
 wire signed [19:0] top_value=top[3]?-top_abs:top_abs;
 wire [35:0] part3={{16{top_value[19]}},top_value}<<12;
'''
        s+=csa('stage1','part0','part1','part2')
        s+=csa('stage2','stage1_s','stage1_c','part3')
        s+=csa('stage3','stage2_s','stage2_c','accumulator[n]')
        s+=' wire [35:0] next_acc=stage3_s+stage3_c;\n'
    else:s+=" wire [35:0] next_acc=accumulator[n]+36'(activation*weight_value);\n"
    s+=''' always @(posedge accumulator_clk or negedge rst_n)begin
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
'''
    return s

def prepare():
    OUT.mkdir(parents=True,exist_ok=True);REPORT.mkdir(parents=True,exist_ok=True)
    (REPORT/'source').mkdir(exist_ok=True)
    for variant in ['REF','SHARE4']:
        target=OUT/variant;target.mkdir(exist_ok=True)
        (target/'mac_slice.sv').write_text(rtl(variant=='SHARE4'))
        shutil.copy2(target/'mac_slice.sv',REPORT/'source'/('mac_slice_%s.sv'%variant))
    for name in ['kwt_ffn_clock_gate.sv','kwt_ffn_requantize.sv']:
        shutil.copy2(IR/'encoder'/name,OUT/name)
    selected=(ROOT/'constraints/ffn_selected.json').read_bytes()
    (REPORT/'frozen-selected.json').write_bytes(selected)
    (REPORT/'protocol.json').write_text(json.dumps(dict(variants=['REF','SHARE4'],agents=False,new_CPU=False,
        scope='Two independent slices; no SoC or published hardware changes',clock_ns=6.666666666667,
        original_IR='ffn_lp_IR',library='SS0.99V125C OCV EMA2 original interconnect/load',
        declared_boundaries=dict(input_hold=True,weight_tile_selection=True,accumulator_bits=576,shift_bits=128,
            pair_ICGs=16,input_hold_ICGs=2,quantizers=2,probe_accumulator_outputs='verification only; disabled as output load for synthesis'),
        original_expression="accumulator+36'(activation*weight_value)",share='2x11 20bit adders,4x16-way selects/lane,5->4->3->2 CSA',
        no_extra_state=True,no_extra_cycles=True,release_unchanged=True),indent=2))
    bench=(ROOT/'build/optimization/rtl/ffn_lp_IR/loading_dma_tb.sv').read_text()
    bench=bench.replace('reg clk=0;always #5 clk=~clk;','reg clk=0;always #3.333333 clk=~clk;')
    # Each original frozen core supplies both candidates at its actual interface.
    observer='''
 wire [575:0] ref_acc,share_acc;
 wire signed [15:0] ref_low,ref_high,share_low,share_high;
 wire [1:0] slice_read={dut.core.ap_input_rows[1].read_enable,dut.core.ap_input_rows[0].read_enable};
 mac_slice_REF ref_slice(.clk(clk),.rst_n(dut.core.rst_n),.clock_test_enable(dut.core.clock_test_enable),
 .input_rdata(dut.core.ap_input_rdata),.input_read(slice_read),.weight_rdata(dut.core.pm_rdata),.tile_half(dut.core.tile[0]),
 .bias_pair(dut.core.bias_pair),.shift_return(dut.core.jp_shift_return),.seed_mask(dut.core.jp_seed_mask),
 .mac_mask(dut.core.jp_mac_mask),.quant_lane(dut.core.jp_quant_lane),.result_low(ref_low),.result_high(ref_high),.accumulators(ref_acc));
 mac_slice_SHARE4 share_slice(.clk(clk),.rst_n(dut.core.rst_n),.clock_test_enable(dut.core.clock_test_enable),
 .input_rdata(dut.core.ap_input_rdata),.input_read(slice_read),.weight_rdata(dut.core.pm_rdata),.tile_half(dut.core.tile[0]),
 .bias_pair(dut.core.bias_pair),.shift_return(dut.core.jp_shift_return),.seed_mask(dut.core.jp_seed_mask),
 .mac_mask(dut.core.jp_mac_mask),.quant_lane(dut.core.jp_quant_lane),.result_low(share_low),.result_high(share_high),.accumulators(share_acc));
 generate for(genvar sl=0;sl<16;sl=sl+1)begin: slice_check
 always @(negedge clk)if(dut.core.rst_n)begin
  if(ref_acc[sl*36+:36]!==dut.core.accumulator[sl]||share_acc[sl*36+:36]!==dut.core.accumulator[sl])
   $fatal(1,"SLICE_ACC_MISMATCH layer=%0d lane=%0d",layer,sl);
 end end endgenerate
 always @(posedge clk)if(active&&dut.core.jp_quant_commit)begin
  if(ref_low!==dut.core.result_word||ref_high!==dut.core.tp_result_high||share_low!==ref_low||share_high!==ref_high)
   $fatal(1,"SLICE_QUANT_MISMATCH layer=%0d",layer);
 end
'''
    bench=bench[:bench.rfind('endmodule')]+observer+'\nendmodule\n'
    (OUT/'local_tb.sv').write_text(bench)
    for v in ['REF','SHARE4']:
        (OUT/('local_%s.sv'%v)).write_text(rtl(v=='SHARE4').replace('module mac_slice(','module mac_slice_%s('%v))
    print('SLICE_PREPARED',OUT)

if __name__=='__main__':prepare()
