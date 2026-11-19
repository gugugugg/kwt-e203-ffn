// Native mapping uses the committee library's latch-based integrated gate.
module kwt_ffn_clock_gate(input wire clk,enable,test_enable,output wire gated_clk);
`ifdef VERILATOR
    reg enabled;
    always_latch if(!clk) enabled=enable|test_enable;
    assign gated_clk=clk&enabled;
`else
    CLKLANAQV1_12TR40 cell_gate(.CK(clk),.E(enable),.TE(test_enable),.Q(gated_clk));
`endif
endmodule
