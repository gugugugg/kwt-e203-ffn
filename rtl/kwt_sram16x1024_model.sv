// Functional synchronous 16x1024 single-port RAM; replace with committee macro.
module kwt_sram16x1024_model (
    input wire clk, en, we,
    input wire [9:0] addr,
    input wire [15:0] wdata,
    output reg [15:0] rdata
);
    reg [15:0] mem [0:1023];
    always @(posedge clk) if (en) begin
        if (we) mem[addr] <= wdata;
        else rdata <= mem[addr];
    end
endmodule
