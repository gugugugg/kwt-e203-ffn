module shared_engine_tb;
    parameter integer EXPECT_RH=0;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,start=0,direction=0,clear=0;
    reg [31:0] start_address=32'ha0020000,word_count=0,seed=0;
    integer first_accept=-1,last_rsp=-1,first_pio=-1,last_pio=-1;
    integer mode=0,cycle=0,transfers=0,turnover=0,reads=0,writes=0,responses=0;
    wire busy,done,error;
    wire input_ready=mode==0||cycle%11>2;
    wire output_ready=mode==0||cycle%13>3;
    wire mv,mr,mread,mrv,mrr,merr,pv,pr,pread,prv,prr;
    wire [31:0] ma,md,mrd,pd,prd;
    wire [3:0] mm,pm;
    wire [7:0] pa;
    integer pio_reads,pio_writes,pio_responses;
    reg hv=0,hr=0;
    reg [16:0] ha=0;
    reg [31:0] hd=0;
    wire hready,hrv;
    wire [31:0] hrd;
    kwt_ld_engine engine(.clk(clk),.rst_n(rst_n),.start(start),.direction(direction),
        .start_address(start_address),.word_count(word_count),.busy(busy),.done(done),.error(error),
        .input_ready(input_ready),.output_ready(output_ready),
        .mem_cmd_valid(mv),.mem_cmd_ready(mr),.mem_cmd_addr(ma),.mem_cmd_read(mread),.mem_cmd_wdata(md),.mem_cmd_wmask(mm),
        .mem_rsp_valid(mrv),.mem_rsp_ready(mrr),.mem_rsp_rdata(mrd),.mem_rsp_err(merr),
        .pio_cmd_valid(pv),.pio_cmd_ready(pr),.pio_cmd_addr(pa),.pio_cmd_read(pread),.pio_cmd_wdata(pd),.pio_cmd_wmask(pm),
        .pio_rsp_valid(prv),.pio_rsp_ready(prr),.pio_rsp_rdata(prd),.pio_rsp_err(1'b0));
    kwt_shared_icb_sm40 shared(.clk(clk),.rst_n(rst_n),
        .cpu_cmd_valid(1'b0),.cpu_cmd_ready(),.cpu_cmd_addr(32'b0),.cpu_cmd_read(1'b0),.cpu_cmd_wdata(32'b0),.cpu_cmd_wmask(4'b0),
        .cpu_rsp_valid(),.cpu_rsp_ready(1'b1),.cpu_rsp_rdata(),.cpu_rsp_err(),
        .ld_cmd_valid(mv),.ld_cmd_ready(mr),.ld_cmd_addr(ma),.ld_cmd_read(mread),.ld_cmd_wdata(md),.ld_cmd_wmask(mm),
        .ld_rsp_valid(mrv),.ld_rsp_ready(mrr),.ld_rsp_rdata(mrd),.ld_rsp_err(merr),
        .host_cmd_valid(hv),.host_cmd_ready(hready),.host_cmd_addr(ha),.host_cmd_read(hr),.host_cmd_wdata(hd),.host_cmd_wmask(4'hf),
        .host_rsp_valid(hrv),.host_rsp_ready(1'b1),.host_rsp_rdata(hrd));
    transport_endpoint pio(clk,rst_n,clear,seed,mode,pv,pr,pread,pd,prv,prr,prd,pio_reads,pio_writes,pio_responses);
    always @(posedge clk) if(rst_n) begin
        cycle<=cycle+1;
        if(clear) begin reads<=0;writes<=0;responses<=0;end
        else begin
            if(transfers==0) begin
                if(mv&&mr&&first_accept<0) first_accept<=cycle;
                if(mrv&&mrr) last_rsp<=cycle;
                if(pv&&pr) begin
                    if(first_pio<0) first_pio<=cycle;
                    last_pio<=cycle;
                end
            end
            if(mv&&mr) begin
                if(ma!==start_address+4*32'(reads+writes)) $fatal(1,"Connected DPIPE address order");
                if(mread) reads<=reads+1;
                else writes<=writes+1;
            end
            if(mrv&&mrr) responses<=responses+1;
            if(engine.pd_source_pending&&engine.source_complete&&engine.source_fire) turnover<=turnover+1;
        end
    end
    task host_word(input bit read,input integer index);
        begin
            @(negedge clk);hv=1;hr=read;ha=start_address[18:2]+17'(index);
            hd=32'h51000000^seed^32'(index);
            @(posedge clk);while(!hready) @(posedge clk);
            @(negedge clk);hv=0;
            if(read) begin
                @(posedge clk);while(!hrv) @(posedge clk);
                if(hrd!==(32'h51000000^seed^32'(index))) $fatal(1,"DMA output physical SRAM readback");
                @(negedge clk);
            end
        end
    endtask
    task transfer(input integer words,input bit output_dir,input integer profile);
        begin
            @(negedge clk);clear=1;direction=output_dir;mode=profile;word_count=words;seed=32'(transfers*4096);
            if(!output_dir) for(integer index=0;index<words;index=index+1) host_word(0,index);
            @(negedge clk);clear=0;start=1;
            @(negedge clk);start=0;
            while(!done) @(negedge clk);
            if(error||busy||responses!=words||pio_responses!=words||
               (output_dir?(writes!=words||pio_reads!=words):(reads!=words||pio_writes!=words)))
                $fatal(1,"Connected DPIPE completion counts");
            if(output_dir) for(integer index=0;index<words;index=index+1) host_word(1,index);
            if(transfers==0) begin
                if(last_pio-first_accept!=13056||first_pio-first_accept!=2||last_rsp!=last_pio-1)
                    $fatal(1,"PR1 descriptor cadence differs");
                $display("PR1_REAL_ENGINE main_words=%0d first_accept=%0d last_rsp=%0d first_pio=%0d last_pio=%0d",
                    words,first_accept,last_rsp,first_pio,last_pio);
            end
            transfers=transfers+1;
        end
    endtask
    initial begin
        repeat(4) @(negedge clk);rst_n=1;
        transfer(8704,0,0);transfer(64,0,0);transfer(32,0,0);transfer(128,1,0);
        transfer(8704,0,2);transfer(64,0,2);transfer(32,0,2);transfer(128,1,2);
        if(EXPECT_RH&&turnover==0) $fatal(1,"Connected DMA read turnover was not exercised");
        $display("TILE_SHARED_ENGINE_PASS read_handoff=%0d transfers=%0d turnover=%0d cycles=%0d",EXPECT_RH,transfers,turnover,cycle);
        $finish;
    end
endmodule
