`timescale 1ns/1ps
module ch_predictor_tb;
    reg clk=0, rst_n=0, restart=0, valid=0, ready=0;
    reg [31:0] word=0;
    wire old_ready,new_ready,old_valid,new_valid,old_done,new_done;
    wire [31:0] old_data,new_data;
    always #3.333 clk=~clk;
    kwt_lossless_decode_ch #(.INPUT_PACKET(1)) old_codec(clk,rst_n,restart,valid,old_ready,word,
        old_valid,ready,old_data,old_done);
    kwt_lossless_decode #(.INPUT_PACKET(1)) new_codec(clk,rst_n,restart,valid,new_ready,word,
        new_valid,ready,new_data,new_done);

    reg [31:0] encoded [0:4095];
    integer sent,received,rd_count,wr_count,wall,task_number;
    string name;
    wire consuming_prediction=old_codec.decode&&
        ((old_codec.index>=512&&old_codec.index<6144&&old_codec.input_lane==0)||
         (old_codec.index>=6144&&old_codec.tail_lane==0));

    always @(posedge clk) if(rst_n&&!restart) begin
        if({old_ready,old_valid,old_done,old_codec.decode} !==
           {new_ready,new_valid,new_done,new_codec.decode}) $fatal(1,"PR ready/valid/decode changed");
        if(old_valid && old_data!==new_data) $fatal(1,"PR output changed");
        if(old_codec.decode && old_codec.value!==new_codec.value) $fatal(1,"PR decoded symbol changed");
        if(consuming_prediction && old_codec.prediction!==new_codec.prediction)
            $fatal(1,"PR predictor changed at index %d",old_codec.index);
        if(new_codec.predictor_memory.rd && new_codec.predictor_memory.wr) $fatal(1,"PR port collision");
        if(new_codec.predictor_memory.rd) rd_count=rd_count+1;
        if(new_codec.predictor_memory.wr) wr_count=wr_count+1;
        if(valid&&old_ready) sent=sent+1;
        if(old_valid&&ready) received=received+1;
    end

    task drive_packet(input integer stop_after);
        integer total;
        begin
            total=1+int'(encoded[0][16:4]);
            sent=0;received=0;rd_count=0;wr_count=0;wall=0;
            while(!old_done && received<stop_after) begin
                @(negedge clk);
                valid=sent<total && (wall%11<7 || wall%29==0);
                word=encoded[sent];
                ready=wall%31<15 || wall%41==0;
                wall=wall+1;
                if(wall>30000) $fatal(1,"PR timeout");
                @(posedge clk); #0.01;
            end
            @(negedge clk); valid=0;ready=0;
            if(stop_after==3168) begin
                if(!old_done||!new_done||received!=3168||sent!=total||rd_count!=768||wr_count!=768)
                    $fatal(1,"PR counts %d %d %d %d",received,sent,rd_count,wr_count);
                $display("CH_PR_PASS case=%0d words=%0d output=%0d reads=%0d writes=%0d",task_number,sent,received,rd_count,wr_count);
            end
        end
    endtask

    initial begin
        repeat(3) @(negedge clk); rst_n=1;
        for(task_number=1;task_number<=12;task_number=task_number+1) begin
            name=$sformatf("%s/input_%02d.hex","reports/optimization/ffn_ch_efficiency/local",task_number);
            $readmemh(name,encoded);
            if(task_number==1) begin
                drive_packet(700);
                rst_n=0;
                repeat(4) @(negedge clk); rst_n=1;
            end
            drive_packet(3168);
            restart=1; @(negedge clk); restart=0;
        end
        $finish;
    end
endmodule
