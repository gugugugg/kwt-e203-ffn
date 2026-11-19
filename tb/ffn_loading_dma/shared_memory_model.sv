module kwt_shared_sram_sm40(
    input wire clk,en,we,input wire [16:0] addr,input wire [31:0] wdata,
    input wire [3:0] wmask,output reg [31:0] rdata
);
    reg [31:0] memory[0:131071];
    always @(posedge clk)if(en)begin
        if(we)begin
            for(integer b=0;b<4;b=b+1)if(wmask[b])memory[addr][b*8+:8]<=wdata[b*8+:8];
        end else rdata<=memory[addr];
    end
endmodule
