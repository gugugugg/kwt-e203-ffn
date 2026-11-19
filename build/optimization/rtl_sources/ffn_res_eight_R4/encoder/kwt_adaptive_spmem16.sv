// Single-port leaves with an integrated gate per physical SRAM instance.
module kwt_adaptive_spmem16 #(
    parameter integer ADDR_WIDTH=13,BANKS=1
)(
    input wire clk,en,we,test_enable,
    input wire [ADDR_WIDTH-1:0] addr,
    input wire [15:0] wdata,
    output wire [15:0] rdata
);
    localparam integer SW=(BANKS>1)?$clog2(BANKS):1;
    wire [SW-1:0] selected;
    reg [SW-1:0] read_bank;
    wire [15:0] data[0:BANKS-1];
    generate if(BANKS==1) assign selected=0;
    else assign selected=SW'(addr[ADDR_WIDTH-1:10]);
    for(genvar b=0;b<BANKS;b=b+1) begin: banks
        wire leaf_en=en&&(selected==SW'(b));
        wire leaf_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(leaf_en),.test_enable(test_enable),.gated_clk(leaf_clk));
        kwt_sram16x1024_model ram(.clk(leaf_clk),.en(leaf_en),.we(we),.addr(addr[9:0]),.wdata(wdata),.rdata(data[b]));
    end endgenerate
    always @(posedge clk) if(en&&!we) read_bank<=selected;
    assign rdata=data[read_bank];
endmodule
