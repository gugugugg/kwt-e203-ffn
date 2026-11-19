module kwt_encoder_sram16x128(
    input wire clk,en,we,
    input wire [6:0] addr,
    input wire [15:0] wdata,
    output wire [15:0] rdata
);
    kwt_sram16x128_model macro_wrapper(.*);
endmodule
