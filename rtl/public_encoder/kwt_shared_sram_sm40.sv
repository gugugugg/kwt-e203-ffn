module kwt_shared_sram_sm40(
    input wire clk,en,we,
    input wire [16:0] addr,
    input wire [31:0] wdata,
    input wire [3:0] wmask,
    output wire [31:0] rdata
);
    wire [1023:0] bank_data;
    reg [4:0] read_bank;
    always @(posedge clk) if(en) read_bank<=addr[16:12];
    assign rdata=bank_data[read_bank*32+:32];
    for(genvar bank=0;bank<32;bank=bank+1) begin: banks
        for(genvar half=0;half<2;half=half+1) begin: halves
            RAMSP4096X16 macro(
                .CLK(clk),.CEN(!(en&&addr[16:12]==bank)),
                .GWEN(~we),.WEN(~{{8{we&&wmask[half*2+1]}},{8{we&&wmask[half*2]}}}),
                .A(addr[11:0]),.D(wdata[half*16+:16]),.Q(bank_data[bank*32+half*16+:16]),
                .EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1)
            );
        end
    end
endmodule
