module threebank_tb;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0;
    reg cpu_cmd_valid=0,cpu_cmd_read=1,cpu_rsp_ready=1;
    wire cpu_cmd_ready,cpu_rsp_valid,cpu_rsp_err;
    reg [31:0] cpu_cmd_addr=0,cpu_cmd_wdata=0;
    reg [3:0] cpu_cmd_wmask=15;
    wire [31:0] cpu_rsp_rdata;
    reg host_cmd_valid=0,host_cmd_read=0,host_rsp_ready=1;
    wire host_cmd_ready,host_rsp_valid;
    reg [16:0] host_cmd_addr=0;
    reg [31:0] host_cmd_wdata=0;
    reg [3:0] host_cmd_wmask=15;
    wire [31:0] host_rsp_rdata;
    reg ld_cmd_valid=0,ld_cmd_read=1,ld_rsp_ready=1;
    wire ld_cmd_ready,ld_rsp_valid,ld_rsp_err;
    reg [31:0] ld_cmd_addr=0,ld_cmd_wdata=0;
    reg [3:0] ld_cmd_wmask=0;
    wire [31:0] ld_rsp_rdata;
    reg wb_valid=0,wb_ack_ready=0;
    wire wb_ready,wb_ack_valid;
    reg [16:0] wb_addr=0;
    reg [31:0] wb_data=0;
    kwt_shared_icb_sm40 dut(.*);

    task host_store(input [16:0] addr,input [31:0] value);
        @(negedge clk);
        host_cmd_valid=1;host_cmd_read=0;host_cmd_addr=addr;host_cmd_wdata=value;
        @(posedge clk);
        while(!host_cmd_ready) @(posedge clk);
        @(negedge clk);host_cmd_valid=0;
    endtask

    task host_check(input [16:0] addr,input [31:0] value);
        @(negedge clk);
        host_cmd_valid=1;host_cmd_read=1;host_cmd_addr=addr;
        @(posedge clk);
        while(!host_cmd_ready) @(posedge clk);
        @(negedge clk);host_cmd_valid=0;
        @(posedge clk);
        while(!host_rsp_valid) @(posedge clk);
        if(host_rsp_rdata!==value) $fatal(1,"readback %h actual=%h expected=%h",addr,host_rsp_rdata,value);
    endtask

    initial begin
        repeat(2) @(negedge clk);rst_n=1;
        host_store(0,32'hdeadbeef);host_store(131021,1);
        @(negedge clk);
        ld_cmd_addr=32'ha0000000;ld_cmd_valid=1;ld_rsp_ready=0;
        host_cmd_addr=1;host_cmd_wdata=32'h1234cafe;host_cmd_valid=1;
        wb_valid=1;wb_addr=17'h4000;wb_data=32'h89abcdef;
        @(posedge clk);
        if(!ld_cmd_ready||!host_cmd_ready||!wb_ready||
           !dut.physical_accept||!dut.host_dual||!dut.result_commit||
           dut.memory.banks[0].halves[0].macro.CEN||
           dut.memory.banks[1].halves[0].macro.CEN||
           dut.memory.banks[4].halves[0].macro.CEN)
            $fatal(1,"three distinct bank commands did not physically fire");
        @(negedge clk);
        ld_cmd_valid=0;host_cmd_valid=0;wb_addr=17'h4001;wb_data=32'h23456789;
        repeat(2) begin
            @(posedge clk);
            if(wb_ready||!wb_ack_valid||!ld_rsp_valid||ld_rsp_rdata!==32'hdeadbeef)
                $fatal(1,"independent held response lost");
            @(negedge clk);
        end
        ld_rsp_ready=1;wb_ack_ready=1;
        @(posedge clk);
        if(!wb_ack_valid||!ld_rsp_valid||!wb_ready) $fatal(1,"response handoff failed");
        @(negedge clk);wb_valid=0;
        @(posedge clk);if(!wb_ack_valid) $fatal(1,"second result ACK missing");
        @(negedge clk);
        cpu_cmd_valid=1;cpu_cmd_addr=32'ha0010000;
        wb_valid=1;wb_addr=17'h4002;wb_data=32'h3456789a;
        @(posedge clk);
        if(!cpu_cmd_ready||wb_ready) $fatal(1,"CPU should win same-bank arbitration");
        @(negedge clk);cpu_cmd_valid=0;
        @(posedge clk);if(!wb_ready) $fatal(1,"held write should proceed");
        @(negedge clk);wb_valid=0;
        @(posedge clk);if(!wb_ack_valid) $fatal(1,"third result ACK missing");
        host_check(0,32'hdeadbeef);
        host_check(1,32'h1234cafe);
        host_check(17'h4000,32'h89abcdef);
        host_check(17'h4001,32'h23456789);
        host_check(17'h4002,32'h3456789a);
        $display("THREEBANK_PROTOCOL_PASS");
        $finish;
    end
endmodule

