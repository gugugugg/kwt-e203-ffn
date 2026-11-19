module transport_endpoint(
    input wire clk,rst_n,clear,input wire [31:0] seed,input integer mode,
    input wire valid,output wire ready,input wire read,input wire [31:0] data,
    output wire rsp_valid,input wire rsp_ready,output wire [31:0] rsp_data,
    output integer reads,writes,responses
);
    reg pending;integer delay_count,cycle;
    reg [31:0] saved;
    wire retire=pending&&(delay_count==0)&&rsp_ready;
    assign ready=(!pending||retire)&&((mode!=2)||(cycle%7>1));
    wire fire=valid&&ready;
    assign rsp_valid=(pending&&(delay_count==0))||(!pending&&mode==0&&fire);
    assign rsp_data=pending?saved:(32'h51000000^seed^32'(reads));
    always @(posedge clk)begin
        if(!rst_n||clear)begin pending<=0;delay_count<=0;cycle<=0;reads<=0;writes<=0;responses<=0;saved<=0;end
        else begin
            cycle<=cycle+1;
            if(pending&&delay_count!=0)delay_count<=delay_count-1;
            if(retire)pending<=0;
            if(rsp_valid&&rsp_ready)responses<=responses+1;
            if(fire)begin
                if(read)reads<=reads+1;
                else begin
                    if(data!==(32'h51000000^seed^32'(writes)))
                        $fatal(1,"TRANSPORT_DATA_MISMATCH got=%h expected=%h index=%0d",data,32'h51000000^seed^32'(writes),writes);
                    writes<=writes+1;
                end
                saved<=32'h51000000^seed^32'(reads);
                pending<=pending||mode!=0||!rsp_ready;
                delay_count<=(mode==2)?(reads+writes)%3:0;
            end
        end
    end
endmodule

module transport_engine_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,start=0,direction=0,clear=0;
    reg [31:0] start_address=32'ha0020000,word_count=0,seed=0;
    integer mode=0,cycles=0,transfers=0,overlap=0,turnover=0;
    wire busy,done,error;
    wire input_ready=(mode!=2)||(cycles%11>2),output_ready=(mode!=2)||(cycles%13>3);
    wire mv,mr,mread,mrv,mrr,pv,pr,pread,prv,prr;
    wire [31:0] ma,md,mrd,pd,prd;wire [3:0] mm,pm;wire [7:0] pa;
    integer mem_reads,mem_writes,mem_responses,pio_reads,pio_writes,pio_responses;
    kwt_ld_engine dut(.clk(clk),.rst_n(rst_n),.start(start),.direction(direction),
        .start_address(start_address),.word_count(word_count),.busy(busy),.done(done),.error(error),
        .input_ready(input_ready),.output_ready(output_ready),
        .mem_cmd_valid(mv),.mem_cmd_ready(mr),.mem_cmd_addr(ma),.mem_cmd_read(mread),.mem_cmd_wdata(md),.mem_cmd_wmask(mm),
        .mem_rsp_valid(mrv),.mem_rsp_ready(mrr),.mem_rsp_rdata(mrd),.mem_rsp_err(1'b0),
        .pio_cmd_valid(pv),.pio_cmd_ready(pr),.pio_cmd_addr(pa),.pio_cmd_read(pread),.pio_cmd_wdata(pd),.pio_cmd_wmask(pm),
        .pio_rsp_valid(prv),.pio_rsp_ready(prr),.pio_rsp_rdata(prd),.pio_rsp_err(1'b0));
    transport_endpoint mem(clk,rst_n,clear,seed,mode,mv,mr,mread,md,mrv,mrr,mrd,mem_reads,mem_writes,mem_responses);
    transport_endpoint pio(clk,rst_n,clear,seed,mode,pv,pr,pread,pd,prv,prr,prd,pio_reads,pio_writes,pio_responses);
    always @(posedge clk)if(rst_n)begin
        cycles<=cycles+1;
        if(mv&&mr&&pv&&pr)overlap<=overlap+1;
        if(dut.pd_source_pending&&dut.source_complete&&dut.source_fire)turnover<=turnover+1;
        if(dut.pd_count>2)$fatal(1,"Slot count exceeded two");
        if(mv&&mr&&ma!==start_address+4*(mem_reads+mem_writes))$fatal(1,"Memory address order changed");
    end
    task transfer(input integer words,input bit output_dir,input integer profile);
        integer began;
        begin
            @(negedge clk);clear=1;direction=output_dir;mode=profile;word_count=words;seed=32'(transfers*4096);
            @(negedge clk);clear=0;start=1;
            @(negedge clk);start=0;began=cycles;
            while(!done)begin
                @(negedge clk);
                if(cycles-began>words*30+100)$fatal(1,"Normal transfer did not finish words=%0d mode=%0d",words,mode);
            end
            if(error||busy||mem_responses!=words||pio_responses!=words)$fatal(1,"Completion did not follow both endpoints");
            if(output_dir?(pio_reads!=words||mem_writes!=words):(mem_reads!=words||pio_writes!=words))$fatal(1,"Transfer count mismatch");
            transfers=transfers+1;
        end
    endtask
    initial begin
        repeat(4)@(negedge clk);rst_n=1;
        for(integer profile=0;profile<3;profile=profile+1)begin
            transfer(8704,0,profile);transfer(64,0,profile);
            for(integer task_id=0;task_id<2;task_id=task_id+1)
                for(integer row=0;row<99;row=row+1)begin transfer(32,0,profile);transfer(128,1,profile);end
        end
        if(overlap==0||turnover==0)$fatal(1,"Pipeline overlap or response turnover was not exercised");
        $display("POST_DMA_ENGINE_PASS transfers=%0d overlap=%0d turnover=%0d cycles=%0d",transfers,overlap,turnover,cycles);$finish;
    end
endmodule
