module study_column (
    input wire clk, execute, side, tail, first, emit_side,
    input wire weight_access, weight_write,
    input wire [6:0] weight_addr,
    input wire [15:0] weight_data,
    input wire signed [31:0] bias,
    input wire [63:0] activation,
    output wire [143:0] emit_acc
);
    localparam GATED = STUDY_GATED;
    wire [15:0] weight;
    RAMSP128X16 memory(.CLK(clk), .CEN(!weight_access), .GWEN(!weight_write),
        .WEN({16{!weight_write}}), .A(weight_addr), .D(weight_data), .Q(weight),
        .EMA(3'b010), .EMAW(2'b00), .RET1N(1'b1));
    wire [3:0] context_clk;
    if (GATED) begin: gating
        CLKLANAQV1_12TR40 a(.CK(clk), .E(execute&&!side), .TE(1'b0), .Q(context_clk[0]));
        CLKLANAQV1_12TR40 b(.CK(clk), .E(execute&&side), .TE(1'b0), .Q(context_clk[1]));
        CLKLANAQV1_12TR40 at(.CK(clk), .E(execute&&!side&&!tail), .TE(1'b0), .Q(context_clk[2]));
        CLKLANAQV1_12TR40 bt(.CK(clk), .E(execute&&side&&!tail), .TE(1'b0), .Q(context_clk[3]));
    end
    for (genvar row=0; row<4; row=row+1) begin: lanes
        reg signed [35:0] acc_a, acc_b;
        wire signed [15:0] value=activation[row*16+:16];
        wire signed [31:0] product=value*$signed(weight);
        wire signed [35:0] previous=first ? {{4{bias[31]}},bias} : (side?acc_b:acc_a);
        wire signed [35:0] sum=previous+{{4{product[31]}},product};
        if (GATED) begin: clocked
            localparam integer BASE=(row==3)?2:0;
            always @(posedge context_clk[BASE]) acc_a<=sum;
            always @(posedge context_clk[BASE+1]) acc_b<=sum;
        end else begin: held
            wire lane_enable=execute&&(row!=3||!tail);
            always @(posedge clk) begin
                if (lane_enable&&!side) acc_a<=sum;
                if (lane_enable&&side) acc_b<=sum;
            end
        end
        assign emit_acc[36*row+:36]=emit_side?acc_b:acc_a;
    end
endmodule
