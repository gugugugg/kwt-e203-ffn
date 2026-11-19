module kwt_sram16x1024_model (
    input wire clk, en, we,
    input wire [9:0] addr,
    input wire [15:0] wdata,
    output wire [15:0] rdata
);
    RAMSP1024X16 macro (
        .CLK(clk), .CEN(~en), .GWEN(~we), .WEN({16{~we}}),
        .A(addr), .D(wdata), .Q(rdata),
        .EMA(3'b010), .EMAW(2'b00), .RET1N(1'b1)
    );
endmodule

module kwt_sram16x128_model (
    input wire clk, en, we,
    input wire [6:0] addr,
    input wire [15:0] wdata,
    output wire [15:0] rdata
);
    RAMSP128X16 macro (
        .CLK(clk), .CEN(~en), .GWEN(~we), .WEN({16{~we}}),
        .A(addr), .D(wdata), .Q(rdata),
        .EMA(3'b010), .EMAW(2'b00), .RET1N(1'b1)
    );
endmodule
