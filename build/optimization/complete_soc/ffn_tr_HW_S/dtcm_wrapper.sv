module sram_wrap_64KX32 #(parameter ADDRWIDTH=16, DATAWIDTH=32)(input CLK,RSTN,CS,WE,input [ADDRWIDTH-1:0] ADDRESS,input [3:0] WEM,input [DATAWIDTH-1:0] WDATA,output [DATAWIDTH-1:0] RDATA);
kwt_cpu_tcm_sram #(.DW(DATAWIDTH),.AW(ADDRWIDTH),.LEAF_AW(13)) memory(.clk(CLK),.rst_n(RSTN),.cs(CS),.we(WE),.addr(ADDRESS),.wdata(WDATA),.wmask(WEM),.rdata(RDATA));
endmodule
