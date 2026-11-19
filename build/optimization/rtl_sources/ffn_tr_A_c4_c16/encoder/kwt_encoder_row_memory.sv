// Synchronous single-port, permitted 16-bit functional macro shapes.
module kwt_encoder_row_memory(
    input wire clk,en,
    input wire [5:0] we,
    input wire [6:0] addr,
    input wire [95:0] wdata,
    output wire [95:0] rdata
);
    generate for(genvar b=0;b<6;b=b+1) begin: words
        kwt_encoder_sram16x128 ram(.clk(clk),.en(en),.we(we[b]),.addr(addr),
            .wdata(wdata[b*16+:16]),.rdata(rdata[b*16+:16]));
    end endgenerate
endmodule
