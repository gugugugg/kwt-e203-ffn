module RAMSP4096X16(input CLK,CEN,GWEN,input [15:0] WEN,input [11:0] A,
    input [15:0] D,output reg [15:0] Q,input [2:0] EMA,input [1:0] EMAW,input RET1N);
    reg [15:0] mem[0:4095];
    always @(posedge CLK) if(!CEN) begin
        if(GWEN) Q<=mem[A];
        else for(integer bit_no=0;bit_no<16;bit_no=bit_no+1)
            if(!WEN[bit_no])mem[A][bit_no]<=D[bit_no];
    end
endmodule

module bank_port_tb;
    parameter integer INTERLEAVED=0;
    localparam integer FIRST=INTERLEAVED?1:4096;
    reg clk=0,rst_n=0;
    always #5 clk=~clk;

    reg cpu_cmd_valid=0,cpu_cmd_read=1;
    reg [31:0] cpu_cmd_addr=0,cpu_cmd_wdata=0;
    reg [3:0] cpu_cmd_wmask=15;
    wire cpu_cmd_ready,cpu_rsp_valid,cpu_rsp_err;
    wire [31:0] cpu_rsp_rdata;
    reg host_cmd_valid=0,host_cmd_read=0;
    reg [16:0] host_cmd_addr=0;
    reg [31:0] host_cmd_wdata=0;
    wire host_cmd_ready,host_rsp_valid;
    wire [31:0] host_rsp_rdata;
    reg ld_cmd_valid=0,ld_rsp_ready=1;
    reg [31:0] ld_cmd_addr=0;
    wire ld_cmd_ready,ld_rsp_valid,ld_rsp_err;
    wire [31:0] ld_rsp_rdata;
    kwt_shared_icb_sm40 dut(
        .clk(clk),.rst_n(rst_n),.cpu_cmd_valid(cpu_cmd_valid),.cpu_cmd_ready(cpu_cmd_ready),
        .cpu_cmd_addr(cpu_cmd_addr),.cpu_cmd_read(cpu_cmd_read),.cpu_cmd_wdata(cpu_cmd_wdata),
        .cpu_cmd_wmask(cpu_cmd_wmask),.cpu_rsp_valid(cpu_rsp_valid),.cpu_rsp_ready(1'b1),
        .cpu_rsp_rdata(cpu_rsp_rdata),.cpu_rsp_err(cpu_rsp_err),
        .host_cmd_valid(host_cmd_valid),.host_cmd_ready(host_cmd_ready),.host_cmd_read(host_cmd_read),
        .host_cmd_addr(host_cmd_addr),.host_cmd_wdata(host_cmd_wdata),.host_cmd_wmask(4'hf),
        .host_rsp_valid(host_rsp_valid),.host_rsp_ready(1'b1),.host_rsp_rdata(host_rsp_rdata),
        .ld_cmd_valid(ld_cmd_valid),.ld_cmd_ready(ld_cmd_ready),.ld_cmd_addr(ld_cmd_addr),
        .ld_cmd_read(1'b1),.ld_cmd_wdata(32'b0),.ld_cmd_wmask(4'b0),
        .ld_rsp_valid(ld_rsp_valid),.ld_rsp_ready(ld_rsp_ready),.ld_rsp_rdata(ld_rsp_rdata),.ld_rsp_err(ld_rsp_err));

    function automatic [31:0] address(input integer index);
        address=(index<8448)?32'ha0020000+4*index:32'ha003a000+4*(index-8448);
    endfunction
    function automatic [31:0] payload(input integer index,input integer epoch);
        payload=32'h83be29b1^(index*32'h31c63+epoch*32'h53c4a1);
    endfunction

    task host_word(input integer addr,input reg [31:0] value,input reg reading);
        @(negedge clk);host_cmd_valid=1;host_cmd_addr=17'(addr);host_cmd_wdata=value;host_cmd_read=reading;
        @(posedge clk);while(!host_cmd_ready) @(posedge clk);
    endtask
    task cpu_access(input reg [31:0] addr,input reg [31:0] value,input reg reading,input reg [3:0] mask);
        @(negedge clk);cpu_cmd_valid=1;cpu_cmd_addr=addr;cpu_cmd_wdata=value;cpu_cmd_read=reading;cpu_cmd_wmask=mask;
        @(posedge clk);while(!cpu_cmd_ready) @(posedge clk);
        @(negedge clk);cpu_cmd_valid=0;
        @(posedge clk);while(!cpu_rsp_valid) @(posedge clk);
        if(cpu_rsp_err||(reading&&cpu_rsp_rdata!==value))$fatal(1,"CPU_LOGICAL_READBACK addr=%h got=%h",addr,cpu_rsp_rdata);
    endtask

    integer epoch=0,committed=0,accepted=0,returned=0,dual=0,conflict=0,blocked=0;
    reg checking=0;
    always @(posedge clk) if(checking) begin
        if(dut.host_dual)begin
            if(!dut.host_fire||!dut.joined_fire||!dut.joined_load_read||
               dut.host_bank_word[16:12]==dut.joined_bank_word[16:12])$fatal(1,"PHYSICAL_BANK_COLLISION");
            dual=dual+1;
        end
        if(dut.host_bank_conflict) begin
            if(host_cmd_ready)$fatal(1,"CONFLICT_ACCEPTED_HOST");
            conflict=conflict+1;
        end
        if(ld_cmd_valid&&!dut.dma_load_eligible)blocked=blocked+1;
        if(ld_cmd_valid&&ld_cmd_ready)begin
            if(ld_cmd_addr!==address(accepted)||accepted>=committed||
               (accepted>=8448&&committed!=8512))$fatal(1,"DMA_READ_UNCOMMITTED");
            if(!INTERLEAVED && accepted<8448 &&
               committed < (accepted<4096?4096:accepted<8192?8192:8448))$fatal(1,"UNSEALED_BANK");
            accepted=accepted+1;
        end
        if(ld_rsp_valid&&ld_rsp_ready)begin
            if(ld_rsp_err||returned>=accepted||ld_rsp_rdata!==payload(returned,epoch))
                $fatal(1,"DMA_RETURN_SEQUENCE index=%0d got=%h",returned,ld_rsp_rdata);
            returned=returned+1;
        end
        if(host_cmd_valid&&host_cmd_ready&&!host_cmd_read&&
            ((host_cmd_addr>=32768&&host_cmd_addr<41216)||(host_cmd_addr>=59392&&host_cmd_addr<59456)))begin
            if(host_cmd_addr!==17'((address(committed)-32'ha0000000)>>2))$fatal(1,"HOST_STREAM_SEQUENCE");
            committed=committed+1;
        end
    end

    initial begin
        repeat(4)@(negedge clk);rst_n=1;
        for(epoch=0;epoch<2;epoch=epoch+1) begin
            @(negedge clk);
            committed=0;accepted=0;returned=0;dual=0;conflict=0;blocked=0;checking=1;
            host_word(0,0,0);
            host_word(131021,0,0);
            @(negedge clk);host_cmd_valid=0;
            cpu_access(32'ha007ff30,0,0,15);
            for(integer i=0;i<FIRST;i=i+1)host_word(32768+i,payload(i,epoch),0);
            host_word(131021,1,0);
            fork
                begin
                    for(integer i=FIRST;i<8512;i=i+1)
                        host_word((address(i)-32'ha0000000)>>2,payload(i,epoch),0);
                    @(negedge clk);host_cmd_valid=0;
                end
                begin
                    cpu_access(32'ha007ff34,1,1,15);
                    for(integer i=0;i<8512;i=i+1)begin
                        @(negedge clk);ld_cmd_valid=1;ld_cmd_addr=address(i);
                        @(posedge clk);while(!ld_cmd_ready) @(posedge clk);
                    end
                    @(negedge clk);ld_cmd_valid=0;
                end
                begin
                    repeat(95) begin
                        repeat(53) @(negedge clk);
                        ld_rsp_ready=0;
                        repeat(4) @(negedge clk);
                        ld_rsp_ready=1;
                    end
                end
            join
            wait(returned==8512);
            @(negedge clk);
            checking=0;
            if(committed!=8512||accepted!=8512||dual==0||(INTERLEAVED&&conflict==0))$fatal(1,"BANK_COVERAGE");
            cpu_access(address(4097),payload(4097,epoch),1,15);
            cpu_access(address(4097),32'h0000aa00,0,4'b0010);
            host_word(32768+4097,0,1);
            @(negedge clk);host_cmd_valid=0;
            @(posedge clk);while(!host_rsp_valid)@(posedge clk);
            if(host_rsp_rdata!==((payload(4097,epoch)&32'hffff00ff)|32'h0000aa00))
                $fatal(1,"SHARED_CPU_TO_HOST_BYTE_MASK");
            $display("BANK_PORT_PASS interleaved=%0d epoch=%0d dual=%0d conflict=%0d blocked=%0d",
                      INTERLEAVED,epoch,dual,conflict,blocked);
        end
        $finish;
    end
    initial begin
        repeat(50000) @(posedge clk);
        $fatal(1,"Bank streaming made no progress");
    end
endmodule
