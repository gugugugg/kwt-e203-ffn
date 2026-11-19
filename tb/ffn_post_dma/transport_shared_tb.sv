module transport_shared_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,run=0;
    integer cycle=0,ai=0,ar=0,bi=0,br=0,handovers=0,host_writes=0,host_reads=0;
    wire av,ardy,aread,arv,arr,aerr,bv,brdy,bread,brv,brr,berr;
    wire [31:0] aa,ad,ard,ba,bd,brd;
    reg hv=0,hr=0,hrr=1;reg [16:0] ha=0;reg [31:0] hd=0;
    wire hready,hrv;wire [31:0] hrd;
    assign arr=cycle%9>2;assign brr=cycle%11>1;
    assign av=run&&ai<96&&((ai==ar)||(arv&&arr));
    assign bv=run&&bi<96&&((bi==br)||(brv&&brr));
    assign aa=32'ha0000000+32'(ai/2)*4;assign ba=32'ha0001000+32'(bi/2)*4;
    assign aread=ai%2!=0;assign bread=bi%2!=0;
    assign ad=32'h12340000+32'(ai/2);assign bd=32'h56780000+32'(bi/2);
    kwt_shared_icb_sm40 dut(.clk(clk),.rst_n(rst_n),
        .cpu_cmd_valid(av),.cpu_cmd_ready(ardy),.cpu_cmd_addr(aa),.cpu_cmd_read(aread),.cpu_cmd_wdata(ad),.cpu_cmd_wmask(4'hf),
        .cpu_rsp_valid(arv),.cpu_rsp_ready(arr),.cpu_rsp_rdata(ard),.cpu_rsp_err(aerr),
        .ld_cmd_valid(bv),.ld_cmd_ready(brdy),.ld_cmd_addr(ba),.ld_cmd_read(bread),.ld_cmd_wdata(bd),.ld_cmd_wmask(4'hf),
        .ld_rsp_valid(brv),.ld_rsp_ready(brr),.ld_rsp_rdata(brd),.ld_rsp_err(berr),
        .host_cmd_valid(hv),.host_cmd_ready(hready),.host_cmd_addr(ha),.host_cmd_read(hr),.host_cmd_wdata(hd),.host_cmd_wmask(4'hf),
        .host_rsp_valid(hrv),.host_rsp_ready(hrr),.host_rsp_rdata(hrd));
    always @(posedge clk)if(rst_n)begin
        cycle<=cycle+1;
        if(av&&ardy)ai<=ai+1;
        if(bv&&brdy)bi<=bi+1;
        if(arv&&arr)begin
            if(aerr||(ar%2!=0&&ard!==(32'h12340000+32'(ar/2))))$fatal(1,"CPU response ownership/data");
            ar<=ar+1;
        end
        if(brv&&brr)begin
            if(berr||(br%2!=0&&brd!==(32'h56780000+32'(br/2))))$fatal(1,"DMA response ownership/data");
            br<=br+1;
        end
        if(dut.memory_arbiter.retire&&dut.memory_arbiter.fire)handovers<=handovers+1;
        if(hv&&hready&&!hr)host_writes<=host_writes+1;
        if(hrv&&hrr)host_reads<=host_reads+1;
        if(hv&&dut.joined_cmd_ready)$fatal(1,"Host priority changed");
        if(ai-ar>1||bi-br>1)$fatal(1,"Master has more than one outstanding");
        if(cycle>10000)$fatal(1,"Normal arbitration did not finish");
    end
    initial begin
        repeat(4)@(negedge clk);rst_n=1;run=1;
        for(integer index=0;index<40;index=index+1)begin
            repeat(3)@(negedge clk);hv=1;hr=0;ha=17'h1f000+17'(index);hd=32'h9abc0000+32'(index);
            @(posedge clk);while(!hready)@(posedge clk);
            @(negedge clk);hv=0;
            repeat(2)@(negedge clk);hv=1;hr=1;hrr=0;
            @(posedge clk);while(!hready)@(posedge clk);
            @(negedge clk);hv=0;
            repeat(3)@(negedge clk);hrr=1;
            @(posedge clk);while(!hrv)@(posedge clk);
            if(hrd!==(32'h9abc0000+32'(index)))$fatal(1,"Host readback data changed");
            @(negedge clk);
        end
        wait(ar==96&&br==96);@(negedge clk);
        if(handovers==0||host_writes!=40||host_reads!=40)$fatal(1,"Handoff and host paths were not exercised");
        $display("POST_DMA_SHARED_PASS cpu=%0d dma=%0d host_writes=%0d host_reads=%0d handovers=%0d cycles=%0d",ar,br,host_writes,host_reads,handovers,cycle);$finish;
    end
endmodule
