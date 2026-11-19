`timescale 1ns/1ps
module slice_replay_tb;
reg clk=0,rst_n=0,clock_test_enable=0;
reg [31:0] input_rdata;
reg [1:0] input_read;
reg [255:0] weight_rdata;
reg tile_half;
reg [127:0] bias_pair;
reg [15:0] shift_return,seed_mask,mac_mask;
reg [3:0] quant_lane;
wire [15:0] result_low,result_high;
mac_slice_top dut(.*);
integer fd,rc,cycle,phase,check,layer,outputs;
reg [31:0] expected;
string path,saif_base;
task read_record;
begin
 rc=$fscanf(fd,"%d %d %h %h %h %h %h %h %h %h %h %h %h %h\n",
   cycle,phase,rst_n,tile_half,seed_mask,mac_mask,quant_lane,input_read,input_rdata,weight_rdata,bias_pair,shift_return,check,expected);
 if(rc!=14&&!$feof(fd))$fatal(1,"SLICE_STIMULUS_FORMAT rc=%0d",rc);
end endtask
initial begin
 if(!$value$plusargs("STIMULUS=%s",path))$fatal(1,"STIMULUS_PATH_REQUIRED");
 if(!$value$plusargs("LAYER=%d",layer))layer=0;
 fd=$fopen(path,"r");outputs=0;
 if(!fd)$fatal(1,"STIMULUS_OPEN_FAILED");
 repeat(4)begin #3.333333;clk=1;#3.333333;clk=0;end
`ifdef NATIVE_SAIF
 if($value$plusargs("SAIF=%s",saif_base))begin
  $set_gate_level_monitoring("rtl_on");$set_toggle_region(dut);$toggle_start();
 end
`endif
 while(!$feof(fd))begin
  read_record();
  if(rc==14)begin
   if(phase!=0)$fatal(1,"SLICE_LOW_PHASE_REQUIRED");
   #3.333333;
   if(check)begin
    if({result_high,result_low}!==expected)$fatal(1,"SLICE_REPLAY_VALUE layer=%0d cycle=%0d actual=%h expected=%h",layer,cycle,{result_high,result_low},expected);
    outputs=outputs+2;
   end
   clk=1;#0.001;
   read_record();if(rc!=14||phase!=1)$fatal(1,"SLICE_HIGH_PHASE_REQUIRED");
   #3.332333;clk=0;
  end
 end
`ifdef NATIVE_SAIF
 if(saif_base!="")begin $toggle_stop();$toggle_report(saif_base,1.0e-9,"slice_replay_tb.dut");end
`endif
 $fclose(fd);
 if(outputs!=25344||cycle!=148270)$fatal(1,"SLICE_REPLAY_COUNT outputs=%0d cycle=%0d",outputs,cycle);
 $display("SLICE_REPLAY_PASS layer=%0d outputs=%0d cycles=148271",layer,outputs);$fflush();$finish;
end
endmodule
