// Independent four-state event simulation preserves upstream #1 delays.
`timescale 1ns/1ps
module kwt_cpu_event_tb;
    reg clk=0,rst_n=0;
    always #5 clk=~clk;
    wire sim_done,sim_pass;
    wire [31:0] inspect_pc;
    integer cycles=0;
    kwt_cpu_soc dut(.*);
    initial begin repeat(32) @(negedge clk); rst_n=1; end
    always @(posedge clk) begin
        cycles<=cycles+1;
        if(cycles!=0 && cycles%250000==0) begin
            $display("EVENT_CPU progress cycle=%0d pc=%h",cycles,inspect_pc); $fflush();
        end
        if(sim_done) begin
            if(!sim_pass) $fatal(1,"Event CPU run failed");
            $display("PASS four-state real E203 CPU integration cycles=%0d",cycles); $finish;
        end
        if(cycles>10000000) $fatal(1,"Event CPU run timeout pc=%h",inspect_pc);
    end
endmodule
