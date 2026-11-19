module kwt_sram16x128_model(
    input wire clk,en,we,
    input wire [6:0] addr,
    input wire [15:0] wdata,
    output reg [15:0] rdata
);
    reg [15:0] mem[0:127];
    always @(posedge clk) if(en) begin
        if(we) mem[addr] <= wdata;
        else rdata <= mem[addr];
    end
endmodule
