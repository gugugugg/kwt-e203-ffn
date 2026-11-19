module threebank_core_tb;
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0, start=0;
    wire busy,done,error;
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
    wire ld_cmd_valid,ld_cmd_ready,ld_rsp_valid,ld_rsp_ready,ld_rsp_err;
    wire [31:0] ld_cmd_addr,ld_rsp_rdata;
    wire ld_cmd_read=1;
    wire [31:0] ld_cmd_wdata=0;
    wire [3:0] ld_cmd_wmask=0;
    wire wb_valid,wb_ready,wb_ack_valid,wb_ack_ready;
    wire [16:0] wb_addr;
    wire [31:0] wb_data;
    kwt_threebank_core core(.*);
    kwt_shared_icb_sm40 mem(.*);

    reg [16:0] addresses[0:11679];
    reg [31:0] words[0:11679];
    reg [15:0] expected[0:25343];
    reg [12671:0] seen;
    integer cycle=0,origin=0,last_commit=0,acks=0,writes=0,reads=0,triples=0,case_no=1;
    integer number_of_cases=1, index;
    integer output_stalls=0;
    initial if($test$plusargs("CPU_PRESSURE")) begin
        wait(writes>=32);
        for(integer burst=0;burst<4;burst=burst+1) begin
            for(integer req=0;req<64;req=req+1) begin
                @(negedge clk);
                wait(wb_valid);
                cpu_cmd_valid=1;
                cpu_cmd_addr=32'ha0000000+{13'b0,wb_addr,2'b00};
                @(posedge clk);
                while(!cpu_cmd_ready) @(posedge clk);
                @(negedge clk);cpu_cmd_valid=0;
                repeat(2) @(negedge clk);
            end
            repeat(128) @(negedge clk);
        end
    end
    always @(posedge clk) begin
        cycle<=cycle+1;
        if(busy&&ld_cmd_valid&&ld_cmd_ready) reads=reads+1;
        if(wb_valid&&!wb_ready) output_stalls=output_stalls+1;
        if(error) $fatal(1,"read response error");
        if(wb_valid&&wb_ready) begin
            index=int'(wb_addr)-16384;
            if(seen[index]||wb_data!=={expected[2*index+1],expected[2*index]})
                $fatal(1,"value case=%0d index=%0d got=%h expected=%h cycle=%0d",case_no,index,
                    wb_data,{expected[2*index+1],expected[2*index]},cycle-origin);
            seen[index]=1;writes=writes+1;last_commit=cycle-origin;
            if(mem.host_dual&&ld_cmd_valid&&ld_cmd_ready) triples=triples+1;
        end
        if(wb_ack_valid&&wb_ack_ready) acks=acks+1;
    end
    task put_word(input [16:0] address,input [31:0] data);
        @(negedge clk);host_cmd_valid=1;host_cmd_addr=address;host_cmd_wdata=data;
        @(posedge clk);
        while(!host_cmd_ready) @(posedge clk);
    endtask
    initial begin
        if($value$plusargs("TASKS=%d",number_of_cases)) begin end
        repeat(3) @(negedge clk);rst_n=1;
        for(case_no=1;case_no<=number_of_cases;case_no=case_no+1) begin
            $readmemh($sformatf("build/optimization/complete_soc/ffn_trb_threebank/packed_inputs/task_%02d_payload.hex",case_no),words);
            $readmemh($sformatf("build/optimization/complete_soc/ffn_trb_threebank/packed_inputs/task_%02d_addresses.hex",case_no),addresses);
            $readmemh($sformatf("build/optimization/ffn_ar_area/frozen/images/task_%02d_expected.hex",2*case_no-1),expected);
            @(negedge clk);
            seen=0;writes=0;reads=0;acks=0;triples=0;origin=cycle;
            fork
                begin
                    put_word(0,words[0]);put_word(131021,1);
                    for(integer i=1;i<11680;i=i+1) put_word(addresses[i],words[i]);
                    @(negedge clk);host_cmd_valid=0;
                end
                begin
                    repeat(186) @(negedge clk);start=1;
                    @(negedge clk);start=0;
                end
            join
            wait(done);
            @(negedge clk);
            if(!(&seen)||writes!=12672||reads!=11680||acks!=12672)
                $fatal(1,"complete counts %0d %0d %0d",writes,reads,acks);
            if($test$plusargs("CPU_PRESSURE")) begin
                if(output_stalls==0) $fatal(1,"CPU contention never stalled result writes");
                $display("THREEBANK_RESULT_PRESSURE_PASS stalls=%0d",output_stalls);
            end
            $display("THREEBANK_CORE_PASS case=%0d cycles=%0d triples=%0d reads=%0d writes=%0d acks=%0d",
                case_no,last_commit+1,triples,reads,writes,acks);
        end
        $finish;
    end
    initial begin
        repeat(50000*12) @(posedge clk);
        $fatal(1,"task did not complete case=%0d cycle=%0d reads=%0d writes=%0d",case_no,cycle-origin,reads,writes);
    end
endmodule

