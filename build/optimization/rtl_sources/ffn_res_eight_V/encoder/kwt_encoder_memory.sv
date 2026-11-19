// Synchronous single-port, permitted 16-bit functional macro shapes.
module kwt_encoder_memory #(
    parameter integer BANK_LEAVES=8
)(
    input wire clk,test_enable,
    input wire [7:0] en,we,
    input wire [103:0] addr,
    input wire [127:0] wdata,
    output wire [127:0] rdata
);
    generate for(genvar b=0;b<8;b=b+1) begin: banks
        kwt_adaptive_spmem16 #(.ADDR_WIDTH(13),.BANKS(BANK_LEAVES)) ram(
            .clk(clk),.test_enable(test_enable),.en(en[b]),.we(we[b]),.addr(addr[b*13+:13]),
            .wdata(wdata[b*16+:16]),.rdata(rdata[b*16+:16]));
    end endgenerate
endmodule
