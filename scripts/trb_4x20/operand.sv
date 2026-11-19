module study_operand (
    input wire clk,
    input wire [63:0] macro_return,
    input wire [STUDY_DEPTH-1:0] valid,
    output wire [(STUDY_DEPTH+1)*32-1:0] column_taps
);
    localparam DEPTH=STUDY_DEPTH;
    localparam GATED=STUDY_GATED;
    wire [63:0] stage [0:DEPTH];
    assign stage[0]=macro_return;
    for (genvar i=1; i<=DEPTH; i=i+1) begin: pipeline
        reg [63:0] q;
        if (GATED) begin: gated
            wire gclk;
            CLKLANAQV1_12TR40 gate(.CK(clk),.E(valid[i-1]),.TE(1'b0),.Q(gclk));
            always @(posedge gclk) q<=stage[i-1];
        end else begin: held
            always @(posedge clk) if (valid[i-1]) q<=stage[i-1];
        end
        assign stage[i]=q;
        if (i%2) assign column_taps[64*((i-1)/2)+:64]=q;
    end
endmodule
