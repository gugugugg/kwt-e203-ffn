module sram_wrap_32KX64 #(parameter ADDRWIDTH=15, DATAWIDTH=64)(input CLK,RSTN,CS,WE,input [ADDRWIDTH-1:0] ADDRESS,input [7:0] WEM,input [DATAWIDTH-1:0] WDATA,output [DATAWIDTH-1:0] RDATA);
kwt_cpu_tcm_sram #(.DW(DATAWIDTH),.AW(ADDRWIDTH),.LEAF_AW(12)) memory(.clk(CLK),.rst_n(RSTN),.cs(CS),.we(WE),.addr(ADDRESS),.wdata(WDATA),.wmask(WEM),.rdata(RDATA));
endmodule
