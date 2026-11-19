module shared_pipeline_tb;
    parameter integer EXPECT_RH=0;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,run=0;
    integer cycle=0,ai=0,ar=0,bi=0,br=0,handovers=0,host_writes=0,host_reads=0;
    integer physical_reads=0,physical_writes=0,cpu_stalls=0,dma_stalls=0;
    wire av,ardy,aread,arv,arr,aerr,bv,brdy,bread,brv,brr,berr;
    wire [31:0] aa,ad,ard,ba,bd,brd;
    wire [3:0] am,bm;
    reg hv=0,hr=0,hrr=1;
    reg [16:0] ha=0;
    reg [31:0] hd=0;
    reg [3:0] hm=4'hf;
    wire hready,hrv;
    wire [31:0] hrd;
    assign arr=cycle%9>2;
    assign brr=cycle%11>1;
    assign av=run&&ai<32&&((ai==ar)||(arv&&arr));
    assign bv=run&&bi<80&&((bi==br)||(brv&&brr));
    assign aa=32'ha0000000+32'(ai/4)*4;
    assign ba=32'ha0001000+32'(bi<32?bi/4:(bi-32)%8)*4;
    assign aread=ai%4>=2;
    assign bread=bi>=32||bi%4>=2;
    assign ad=ai%4==1?32'ha5005a00:32'h12340000+32'(ai/4);
    assign bd=bi%4==1?32'h00cd00e0+32'(bi/4):32'h56780000+32'(bi/4);
    assign am=ai%4==1?4'ha:4'hf;
    assign bm=bi%4==1?4'h5:4'hf;
    kwt_shared_icb_sm40 dut(.clk(clk),.rst_n(rst_n),
        .cpu_cmd_valid(av),.cpu_cmd_ready(ardy),.cpu_cmd_addr(aa),.cpu_cmd_read(aread),.cpu_cmd_wdata(ad),.cpu_cmd_wmask(am),
        .cpu_rsp_valid(arv),.cpu_rsp_ready(arr),.cpu_rsp_rdata(ard),.cpu_rsp_err(aerr),
        .ld_cmd_valid(bv),.ld_cmd_ready(brdy),.ld_cmd_addr(ba),.ld_cmd_read(bread),.ld_cmd_wdata(bd),.ld_cmd_wmask(bm),
        .ld_rsp_valid(brv),.ld_rsp_ready(brr),.ld_rsp_rdata(brd),.ld_rsp_err(berr),
        .host_cmd_valid(hv),.host_cmd_ready(hready),.host_cmd_addr(ha),.host_cmd_read(hr),.host_cmd_wdata(hd),.host_cmd_wmask(hm),
        .host_rsp_valid(hrv),.host_rsp_ready(hrr),.host_rsp_rdata(hrd));

    reg last_a_stall=0,last_b_stall=0,last_h_stall=0;
    reg [31:0] stalled_a,stalled_b,stalled_h;
    reg [16:0] last_addr=0;
    reg last_we=0;
    reg [31:0] last_wdata=0;
    reg [3:0] last_wmask=0;
    always @(posedge clk) if(rst_n) begin
        cycle<=cycle+1;
        if(av&&ardy) ai<=ai+1;
        if(bv&&brdy) bi<=bi+1;
        if(arv&&arr) begin
            if(aerr||(ar%4>=2&&ard!==(32'ha5345a00+32'(ar/4))))
                $fatal(1,"CPU masked-write readback or response owner");
            ar<=ar+1;
        end
        if(brv&&brr) begin
            if(berr||((br>=32||br%4>=2)&&brd!==(32'h56cd00e0+32'(br<32?br/4:(br-32)%8))))
                $fatal(1,"DMA masked-write readback or response owner");
            br<=br+1;
        end
        if(last_a_stall&&(!arv||ard!==stalled_a)) $fatal(1,"CPU response changed during backpressure");
        if(last_b_stall&&(!brv||brd!==stalled_b)) $fatal(1,"DMA response changed during backpressure");
        if(last_h_stall&&(!hrv||hrd!==stalled_h)) $fatal(1,"Host response changed during backpressure");
        last_a_stall=arv&&!arr;last_b_stall=brv&&!brr;last_h_stall=hrv&&!hrr;
        if(last_a_stall) begin stalled_a=ard;cpu_stalls<=cpu_stalls+1;end
        if(last_b_stall) begin stalled_b=brd;dma_stalls<=dma_stalls+1;end
        if(last_h_stall) stalled_h=hrd;
        if(dut.joined_rsp_valid&&dut.joined_rsp_ready&&dut.joined_fire) begin
            if(!EXPECT_RH||!dut.memory_arbiter.owner||!dut.read_pending||!dut.joined_cmd_read||
               !(bv&&brdy)||hv||hrv||dut.pending)
                $fatal(1,"Handoff was not a retiring DMA read followed by a qualified DMA read");
            handovers<=handovers+1;
        end
        if(hv&&hready&&!hr) host_writes<=host_writes+1;
        if(hrv&&hrr) host_reads<=host_reads+1;
        if(hv&&dut.joined_cmd_ready) $fatal(1,"Host priority changed");
        if(dut.memory.en) begin
            if(dut.memory.addr!==(dut.host_fire?ha:dut.joined_cmd_addr[18:2])||
               dut.memory.we!==(dut.host_fire?!hr:!dut.joined_cmd_read))
                $fatal(1,"Accepted memory command was delayed or changed");
            last_addr=dut.memory.addr;last_we=dut.memory.we;
            if(dut.memory.we) begin
                if(dut.memory.wdata!==(dut.host_fire?hd:dut.joined_cmd_wdata)||
                   dut.memory.wmask!==(dut.host_fire?hm:dut.joined_cmd_wmask))
                    $fatal(1,"Accepted write data or byte mask changed");
                last_wdata=dut.memory.wdata;last_wmask=dut.memory.wmask;
                physical_writes<=physical_writes+1;
            end else physical_reads<=physical_reads+1;
        end
    end
    always @(negedge clk) if(rst_n) begin
        #1;
        if(!dut.memory.en&&(dut.memory.addr!==last_addr||dut.memory.we!==last_we))
            $fatal(1,"Inactive SRAM address or direction did not hold");
        if(!(dut.memory.en&&dut.memory.we)&&
           (dut.memory.wdata!==last_wdata||dut.memory.wmask!==last_wmask))
            $fatal(1,"SRAM write data or mask changed outside a physical write");
    end

    task host_write(input [16:0] address,input [31:0] data,input [3:0] mask);
        begin
            @(negedge clk);hv=1;hr=0;ha=address;hd=data;hm=mask;
            @(posedge clk);while(!hready) @(posedge clk);
            @(negedge clk);hv=0;
        end
    endtask
    task host_read(input [16:0] address,input [31:0] expected);
        begin
            @(negedge clk);hv=1;hr=1;ha=address;hrr=0;
            @(posedge clk);while(!hready) @(posedge clk);
            @(negedge clk);hv=0;
            repeat(4) @(negedge clk);
            hrr=1;
            @(posedge clk);while(!hrv) @(posedge clk);
            if(hrd!==expected) $fatal(1,"Host masked-write readback");
            @(negedge clk);
        end
    endtask
    initial begin
        repeat(4) @(negedge clk);
        rst_n=1;run=1;
        for(integer index=0;index<16;index=index+1) begin
            host_write(17'h1f000+17'(index),32'h9abc0000+32'(index),4'hf);
            host_write(17'h1f000+17'(index),32'h550000a0+32'(index),4'h9);
            host_read(17'h1f000+17'(index),32'h55bc00a0+32'(index));
        end
        wait(ar==32&&br==80);
        @(negedge clk);
        if((EXPECT_RH&&handovers==0)||(!EXPECT_RH&&handovers!=0)||host_writes!=32||host_reads!=16||
           physical_reads!=96||physical_writes!=64||cpu_stalls==0||dma_stalls==0)
            $fatal(1,"Normal transfer scenario did not complete its expected work");
        $display("TILE_SHARED_PASS read_handoff=%0d cpu=%0d dma=%0d host_writes=%0d host_reads=%0d physical_reads=%0d physical_writes=%0d handovers=%0d cpu_stalls=%0d dma_stalls=%0d cycles=%0d",
            EXPECT_RH,ar,br,host_writes,host_reads,physical_reads,physical_writes,handovers,cpu_stalls,dma_stalls,cycle);
        $finish;
    end
endmodule
