// Toolchain smoke fixture, not the competition accelerator implementation.
module smoke_mac (
    input wire clk,
    input wire rst_n,
    input wire enable,
    input wire signed [7:0] a,
    input wire signed [7:0] b,
    output reg signed [23:0] acc
);
    wire signed [15:0] product = a * b;
    wire signed [23:0] extended_product = {{8{product[15]}}, product};
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) acc <= 24'sd0;
        else if (enable) acc <= acc + extended_product;
    end
endmodule
