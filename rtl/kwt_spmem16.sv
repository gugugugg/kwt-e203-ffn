// Functional synchronous single-port RAM. Leaf shape is exactly 16x1024.
// Replace leaf with the committee macro wrapper; this is not a foundry macro.
module kwt_spmem16 #(
    parameter integer ADDR_WIDTH = 13,
    parameter integer BANKS = 8
) (
    input wire clk, en, we,
    input wire [ADDR_WIDTH-1:0] addr,
    input wire [15:0] wdata,
    output wire [15:0] rdata
);
    localparam integer SELECT_WIDTH = (BANKS > 1) ? $clog2(BANKS) : 1;
    wire [SELECT_WIDTH-1:0] select_bank;
    reg [SELECT_WIDTH-1:0] read_bank;
    wire [15:0] bank_data [0:BANKS-1];
    generate
        if (BANKS == 1) begin: single_bank
            assign select_bank = 0;
        end else begin: multiple_banks
            assign select_bank = addr[ADDR_WIDTH-1:10];
        end
        for (genvar bank=0; bank<BANKS; bank=bank+1) begin: banks
            kwt_sram16x1024_model ram(
                .clk(clk), .en(en && (select_bank == SELECT_WIDTH'(bank))), .we(we),
                .addr(addr[9:0]), .wdata(wdata), .rdata(bank_data[bank]));
        end
    endgenerate
    always @(posedge clk) if (en && !we) read_bank <= select_bank;
    assign rdata = bank_data[read_bank];
endmodule
