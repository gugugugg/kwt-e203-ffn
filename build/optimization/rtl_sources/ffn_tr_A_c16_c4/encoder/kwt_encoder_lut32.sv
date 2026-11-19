// Synchronous single-port, permitted 16-bit functional macro shapes.
module kwt_encoder_lut32(
    input wire clk,load,
    input wire [13:0] load_addr,
    input wire [15:0] load_data,
    input wire read_en,
    input wire [12:0] read_index,
    output wire [31:0] rdata
);
    wire [12:0] node=load?load_addr[13:1]:read_index;
    reg high_read;
    wire [15:0] low_data[0:1],high_data[0:1];
    always @(posedge clk) if(read_en) high_read<=read_index[12];
    generate for(genvar h=0;h<2;h=h+1) begin: halves
        wire wr=load&&(load_addr[0]==1'(h));
        kwt_spmem16 #(.ADDR_WIDTH(12),.BANKS(4)) low_ram(
            .clk(clk),.en(!node[12]&&(wr||read_en)),.we(wr),.addr(node[11:0]),
            .wdata(load_data),.rdata(low_data[h]));
        kwt_encoder_sram16x128 high_ram(
            .clk(clk),.en(node[12]&&(wr||read_en)),.we(wr),.addr(node[6:0]),
            .wdata(load_data),.rdata(high_data[h]));
        assign rdata[h*16+:16]=high_read?high_data[h]:low_data[h];
    end endgenerate
endmodule
