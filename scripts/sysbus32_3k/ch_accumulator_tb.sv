`timescale 1ns/1ps
module ch_accumulator_tb;
    reg clk=0,rst_n=0,start=0;
    reg cmd_ready=0,rsp_valid=0,wb_ready=0,ack=0;
    reg [31:0] rsp_data=0;
    wire [1:0] busy,done,error,priority_write,cmd_valid,rsp_ready,wb_valid,ack_ready;
    wire [31:0] cmd_addr [0:1], wb_data [0:1];
    wire [16:0] wb_addr [0:1];
    always #3.333 clk=~clk;
    kwt_threebank_core_ch old_core(clk,rst_n,start,busy[0],done[0],error[0],12'd3168,14'd8512,priority_write[0],
        cmd_valid[0],cmd_ready,cmd_addr[0],rsp_valid,rsp_ready[0],rsp_data,1'b0,
        wb_valid[0],wb_ready,wb_addr[0],wb_data[0],ack,ack_ready[0]);
    kwt_threebank_core new_core(clk,rst_n,start,busy[1],done[1],error[1],12'd3168,14'd8512,priority_write[1],
        cmd_valid[1],cmd_ready,cmd_addr[1],rsp_valid,rsp_ready[1],rsp_data,1'b0,
        wb_valid[1],wb_ready,wb_addr[1],wb_data[1],ack,ack_ready[1]);

    integer task_number,cycles,reads,writes,seen_acks,word_index,pair;
    reg [31:0] input_image [0:3167], parameter_image [0:8511];
    reg [15:0] expected [0:25343];
    reg [12671:0] seen;
    reg [31:0] reply [0:1];
    reg reply_head,reply_tail;
    integer queued;
    reg ack_pending;
    bit observe=0;
    string path;

    wire [15:0] emit=old_core.column_emit;
    for(genvar col=0;col<16;col=col+1) begin: columns
        wire execute=old_core.weight_columns[col].execute;
        wire ctx_select=old_core.weight_columns[col].context_select;
        wire tail=old_core.weight_columns[col].execute_tail;
        wire emit_side=old_core.weight_columns[col].emit_context;
        for(genvar row=0;row<4;row=row+1) begin: rows
            wire signed [35:0] old_a=old_core.weight_columns[col].lanes[row].acc_a;
            wire signed [35:0] old_b=old_core.weight_columns[col].lanes[row].acc_b;
            wire signed [35:0] new_a=new_core.weight_columns[col].lanes[row].acc_a;
            wire signed [35:0] new_b=new_core.weight_columns[col].lanes[row].acc_b;
            wire ca=new_core.weight_columns[col].lanes[row].clk_a;
            wire cb=new_core.weight_columns[col].lanes[row].clk_b;
            wire qualifies=execute&&(row!=3||!tail);
            integer a_edges=0,b_edges=0,expected_a=0,expected_b=0;
            always @(posedge ca) if(observe) a_edges=a_edges+1;
            always @(posedge cb) if(observe) b_edges=b_edges+1;
            always @(posedge clk) if(observe) begin
                if(emit[col]&&(emit_side ? old_b!==new_b : old_a!==new_a))
                    $fatal(1,"AG quantization context changed col=%0d row=%0d",col,row);
                if(qualifies&&!ctx_select) expected_a=expected_a+1;
                if(qualifies&&ctx_select) expected_b=expected_b+1;
                #0.01;
                if(a_edges!=expected_a||b_edges!=expected_b) $fatal(1,"AG clock edge col=%0d row=%0d",col,row);
                if(old_a!==new_a||old_b!==new_b) $fatal(1,"AG accumulator changed col=%0d row=%0d",col,row);
            end
        end
    end

    always @(posedge clk) if(observe) begin
        cycles=cycles+1;
        if(cycles>90000) $fatal(1,"AG timeout");
        if({busy[0],done[0],error[0],priority_write[0],cmd_valid[0],rsp_ready[0],wb_valid[0],ack_ready[0]} !==
           {busy[1],done[1],error[1],priority_write[1],cmd_valid[1],rsp_ready[1],wb_valid[1],ack_ready[1]})
            $fatal(1,"AG protocol changed");
        if(cmd_valid[0]&&cmd_addr[0]!==cmd_addr[1]) $fatal(1,"AG source address changed");
        if(wb_valid[0]&&{wb_addr[0],wb_data[0]}!=={wb_addr[1],wb_data[1]}) $fatal(1,"AG result changed");
        if(rsp_valid&&rsp_ready[0]) begin queued=queued-1;reply_head=!reply_head;end
        if(cmd_valid[0]&&cmd_ready) begin
            if(cmd_addr[0][31:16]==16'ha002) begin
                word_index=int'(cmd_addr[0][15:2]);
                reply[reply_tail]=parameter_image[word_index];
            end else begin
                word_index=int'(cmd_addr[0][13:2]);
                reply[reply_tail]=input_image[word_index];
            end
            reply_tail=!reply_tail;queued=queued+1;reads=reads+1;
        end
        if(ack&&ack_ready[0]) begin ack_pending=0;seen_acks=seen_acks+1;end
        if(wb_valid[0]&&wb_ready) begin
            pair=int'(wb_addr[0])-16384;
            if(pair<0||pair>=12672||seen[pair]) $fatal(1,"AG result address %d",pair);
            if(wb_data[0]!=={expected[pair*2+1],expected[pair*2]})
                $fatal(1,"AG golden mismatch %d got=%08x expected=%08x",pair,wb_data[0],{expected[pair*2+1],expected[pair*2]});
            seen[pair]=1;writes=writes+1;ack_pending=1;
        end
    end

    task run_layer(input integer stop_after);
        begin
            @(negedge clk);
            start=1;cmd_ready=0;rsp_valid=0;wb_ready=0;ack=0;
            cycles=0;reads=0;writes=0;seen_acks=0;seen=0;queued=0;ack_pending=0;reply_head=0;reply_tail=0;
            observe=1;
            @(negedge clk); start=0;
            while(!done[0]&&cycles<stop_after) begin
                cmd_ready=queued<2&&(cycles%11<8);
                rsp_valid=queued!=0; rsp_data=reply[reply_head];
                ack=ack_pending&&(cycles%13<8);
                wb_ready=(!ack_pending||ack)&&(cycles%17<12);
                @(negedge clk);
            end
            observe=0;cmd_ready=0;rsp_valid=0;wb_ready=0;ack=0;
            if(stop_after==90000) begin
                if(!done[0]||error[0]||reads!=11680||writes!=12672||seen_acks!=12672||!(&seen))
                    $fatal(1,"AG counts %d %d %d",reads,writes,seen_acks);
                $display("CH_AG_PASS case=%0d cycles=%0d reads=%0d writes=%0d acks=%0d",task_number,cycles,reads,writes,seen_acks);
            end
        end
    endtask

    initial begin
        repeat(40) @(negedge clk);rst_n=1;
        for(task_number=1;task_number<=12;task_number=task_number+1) begin
            path=$sformatf("reports/optimization/ffn_ch_efficiency/local/raw_input_%02d.hex",task_number);
            $readmemh(path,input_image);
            path=$sformatf("reports/optimization/ffn_ch_efficiency/local/raw_parameter_%02d.hex",task_number);
            $readmemh(path,parameter_image);
            path=$sformatf("build/optimization/ffn_ar_area/frozen/images/task_%02d_expected.hex",task_number*2-1);
            $readmemh(path,expected);
            if(task_number==1) begin
                run_layer(4000);
                rst_n=0; repeat(40) @(negedge clk); rst_n=1;
            end
            run_layer(90000);
        end
        $finish;
    end
endmodule
