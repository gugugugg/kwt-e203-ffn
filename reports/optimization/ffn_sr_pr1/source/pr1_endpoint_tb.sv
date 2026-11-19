module pr1_endpoint_tb;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0;
    reg cv=0, cr=1, drv=0, dr=1, dw=0, hv=0, hr=0, hrr=1;
    reg [31:0] ca=0, da=0, hd=0;
    reg [16:0] ha=0;
    wire cready, crv, cerr, dready, drsp, derr, hready, hrv;
    wire [31:0] cd, dd, hdata;
    integer cycle=0;
    always @(posedge clk) cycle<=cycle+1;
    kwt_shared_icb_sm40 dut(.clk(clk),.rst_n(rst_n),
        .cpu_cmd_valid(cv),.cpu_cmd_ready(cready),.cpu_cmd_addr(ca),.cpu_cmd_read(1'b1),
        .cpu_cmd_wdata(32'b0),.cpu_cmd_wmask(4'hf),.cpu_rsp_valid(crv),.cpu_rsp_ready(cr),
        .cpu_rsp_rdata(cd),.cpu_rsp_err(cerr),.ld_cmd_valid(drv),.ld_cmd_ready(dready),
        .ld_cmd_addr(da),.ld_cmd_read(!dw),.ld_cmd_wdata(32'hd00d5678),.ld_cmd_wmask(4'hf),
        .ld_rsp_valid(drsp),.ld_rsp_ready(dr),.ld_rsp_rdata(dd),.ld_rsp_err(derr),
        .host_cmd_valid(hv),.host_cmd_ready(hready),.host_cmd_read(hr),.host_cmd_addr(ha),
        .host_cmd_wdata(hd),.host_cmd_wmask(4'hf),.host_rsp_valid(hrv),.host_rsp_ready(hrr),
        .host_rsp_rdata(hdata));

    task host_write(input [31:0] addr,input [31:0] data);
        @(negedge clk); hv=1;ha=addr[18:2];hd=data;
        @(posedge clk); if(!hready) $fatal(1,"Host setup write was not accepted");
        @(negedge clk);hv=0;
    endtask

    task issue(input [31:0] addr,input bit write,output integer accepted);
        @(negedge clk);drv=1;da=addr;dw=write;
        @(posedge clk);if(!dready) $fatal(1,"DMA request not accepted");
        accepted=cycle;
        @(negedge clk);drv=0;
    endtask

    task response(input integer edge_number,input [31:0] data,input bit err);
        @(posedge clk);while(!drsp) @(posedge clk);
        if(cycle!=edge_number||dd!==data||derr!==err||crv)
            $fatal(1,"DMA response cycle/data/owner got %0d %h %b expected %0d %h %b",
                cycle,dd,derr,edge_number,data,err);
    endtask

    integer issued;
    initial begin
        repeat(2) @(negedge clk);
        rst_n=1;
        host_write(32'ha0023ffc,32'h10100101);
        host_write(32'ha0024000,32'h20200202);
        host_write(32'ha00287fc,32'h30300303);
        host_write(32'ha0028800,32'h40400404);

        issue(32'ha0023ffc,0,issued);
        drv=1;da=32'ha0024000;
        response(issued+1,32'h10100101,0);
        if(!dready||!dut.physical_accept) $fatal(1,"Same-edge fast handoff missing");
        @(negedge clk);drv=0;
        response(issued+2,32'h20200202,0);

        issue(32'ha0023ffc,0,issued);
        cv=1;ca=32'ha0024000;
        drv=1;da=32'ha00287fc;
        response(issued+1,32'h10100101,0);
        if(dready||cready) $fatal(1,"Early handoff bypassed the CPU grant");
        @(posedge clk);if(!cready||dready||drsp) $fatal(1,"CPU lost its original round-robin turn");
        @(negedge clk);cv=0;
        @(posedge clk);if(crv||dready) $fatal(1,"CPU response latency changed");
        @(posedge clk);if(!crv||cd!==32'h20200202||dready) $fatal(1,"CPU contention response");
        @(posedge clk);if(!dready) $fatal(1,"DMA did not resume after CPU retirement");
        issued=cycle;
        @(negedge clk);drv=0;
        response(issued+1,32'h30300303,0);

        issue(32'ha00287fc,0,issued);
        drv=1;da=32'ha0028800;
        response(issued+1,32'h30300303,0);
        if(dready) $fatal(1,"Early handoff accepted an out-of-window address");
        @(posedge clk);if(!dready||drsp) $fatal(1,"Legacy command did not follow early retirement");
        @(negedge clk);drv=0;
        response(issued+4,32'h40400404,0);

        issue(32'ha0024000,0,issued);
        dr=0;drv=1;da=32'ha00287fc;
        repeat(3) begin
            @(posedge clk);
            if(!drsp||dd!==32'h20200202||dready) $fatal(1,"Early response not held across backpressure");
        end
        @(negedge clk);dr=1;hv=1;hr=1;ha=17'h9000;hrr=0;
        @(posedge clk);if(!drsp||dd!==32'h20200202||dready||hready) $fatal(1,"Old DMA/host exclusion");
        @(posedge clk);if(!hready||dready||drsp) $fatal(1,"Host priority or duplicate DMA response");
        @(negedge clk);hv=0;
        repeat(2) begin
            @(posedge clk);
            if(dready) $fatal(1,"Accepted DMA with an unretired host response");
        end
        @(negedge clk);hrr=1;
        @(posedge clk);if(!hrv||hdata!==32'h20200202||dready) $fatal(1,"Host read data or priority");
        @(posedge clk);if(!dready) $fatal(1,"DMA did not resume after host retirement");
        issued=cycle;
        @(negedge clk);drv=0;
        response(issued+1,32'h30300303,0);

        @(negedge clk);cv=1;ca=32'ha0024000;
        @(posedge clk);if(!cready) $fatal(1,"CPU read not accepted");
        issued=cycle;
        @(negedge clk);cv=0;
        @(posedge clk);if(crv||drsp) $fatal(1,"CPU got the DMA-only early response");
        @(posedge clk);if(!crv||cerr||cd!==32'h20200202||cycle!=issued+2) $fatal(1,"CPU legacy response");

        issue(32'ha0024001,0,issued);
        response(issued+2,32'h20200202,0);
        issue(32'ha1024000,0,issued);
        response(issued+2,32'b0,1);
        issue(32'ha0024000,1,issued);
        response(issued+2,32'b0,0);
        issue(32'ha0024000,0,issued);
        response(issued+1,32'hd00d5678,0);

        issue(32'ha0023ffc,0,issued);
        rst_n=0;
        @(negedge clk);rst_n=1;
        @(posedge clk);if(drsp||crv||hrv) $fatal(1,"Reset left a pending response");
        issue(32'ha0023ffc,0,issued);
        response(issued+1,32'h10100101,0);
        $display("PR1_ENDPOINT_PASS bank_crossing=true host_priority=true fallback=true cpu_legacy=true reset=true");
        $finish;
    end
    initial #3000 $fatal(1,"Endpoint scenario timed out");
endmodule
