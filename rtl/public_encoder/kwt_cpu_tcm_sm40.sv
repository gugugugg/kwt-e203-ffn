module kwt_cpu_tcm_sram #(
    parameter integer DW=64,
    parameter integer AW=15,
    parameter integer LEAF_AW=12
)(
    input wire clk,rst_n,cs,we,
    input wire [AW-1:0] addr,
    input wire [DW-1:0] wdata,
    input wire [DW/8-1:0] wmask,
    output wire [DW-1:0] rdata
);
    localparam integer BANKS=1<<(AW-LEAF_AW);
    wire [BANKS*DW-1:0] data;
    wire [DW-1:0] bit_wen;
    reg [AW-LEAF_AW-1:0] read_bank;
    for(genvar byte_index=0;byte_index<DW/8;byte_index=byte_index+1) begin: write_masks
        assign bit_wen[byte_index*8+:8]={8{!(we&&wmask[byte_index])}};
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) read_bank<=0;
        else if(cs) read_bank<=addr[AW-1:LEAF_AW];
    end
    assign rdata=data[read_bank*DW+:DW];
    for(genvar bank=0;bank<BANKS;bank=bank+1) begin: banks
        if(DW==64) begin: wide
            RAMSP4KX64 macro(
                .CLK(clk),.CEN(!(cs&&addr[AW-1:LEAF_AW]==bank)),
                .GWEN(~we),.WEN(bit_wen),.A(addr[LEAF_AW-1:0]),
                .D(wdata),.Q(data[bank*DW+:DW]),
                .EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1)
            );
        end else begin: narrow
            RAMSP8KX32 macro(
                .CLK(clk),.CEN(!(cs&&addr[AW-1:LEAF_AW]==bank)),
                .GWEN(~we),.WEN(bit_wen),.A(addr[LEAF_AW-1:0]),
                .D(wdata),.Q(data[bank*DW+:DW]),
                .EMA(3'b010),.EMAW(2'b00),.RET1N(1'b1)
            );
        end
    end
endmodule
