    string filename,saif_path,saif_output,result_directory="build/optimization/complete_soc/ffn_trb_threebank/results";
    string firmware_path="build/optimization/firmware/ffn_trb_threebank/firmware_itcm.hex";
    reg [16:0] payload_addr[0:11679];
    reg [31:0] payload[0:11679];
    reg [12671:0] output_seen;
    integer triples=0, result_acks=0, result_index;
    wire source_fire=dut.ld_cmd_valid&&dut.ld_cmd_ready;
    wire result_fire=dut.wb_valid&&dut.wb_ready;
    wire result_ack=dut.wb_ack_valid&&dut.wb_ack_ready;
`ifndef KWT_UNIFIED_GATE
    wire host_dual=dut.shared_memory.host_dual;
    wire [4:0] read_bank=dut.shared_memory.joined_bank_word[16:12];
    wire [4:0] write_bank=dut.wb_addr[16:12];
    wire [4:0] host_bank=dut.shared_memory.host_bank_word[16:12];
`endif
    always @(posedge clk) if(rst_n) begin
        cycles<=cycles+1;
        if(cpu_fire&&cpu_address[31:8]==24'ha007ff&&!cpu_read) begin
            case(cpu_address[7:0])
                0: task_request=cpu_data;
                8: task_done=cpu_data;
                20: $fatal(1,"UNIFIED_FIRMWARE_ERROR code=%h pc=%h",cpu_data,inspect_pc);
                24: if(cpu_data==32'hcafe1234) firmware_done=1;
                default: ;
            endcase
        end
        if(activity_window&&source_fire) ld_dma_reads=ld_dma_reads+1;
        if(activity_window&&host_cmd_valid&&host_cmd_ready&&!host_cmd_read) begin
            if(host_cmd_addr<3168||(host_cmd_addr>=32768&&host_cmd_addr<41280)) host_payload=host_payload+1;
            else if(host_cmd_addr>=131008) host_control=host_control+1;
            else ld_setup_words=ld_setup_words+1;
        end
        if(activity_window&&result_fire) begin
            result_index=int'(dut.wb_addr)-16384;
            if(result_index<0||result_index>=12672) $fatal(1,"RESULT_ADDRESS %h",dut.wb_addr);
            if(output_seen[result_index]) $fatal(1,"RESULT_DUPLICATE %d",result_index);
            if(dut.wb_data!=={expected[2*result_index+1],expected[2*result_index]})
                $fatal(1,"RESULT_DATA case=%d address=%h got=%h expected=%h cycle=%d",current_case,dut.wb_addr,
                       dut.wb_data,{expected[2*result_index+1],expected[2*result_index]},cycles-start_cycle);
            output_seen[result_index]=1;
            ld_dma_writes=ld_dma_writes+1;
            last_write=cycles;
`ifndef KWT_UNIFIED_GATE
            if(dut.shared_memory.result_commit!==1) $fatal(1,"RESULT_NO_PHYSICAL_COMMIT");
            if(host_dual&&source_fire) begin
                if(write_bank==read_bank||write_bank==host_bank||read_bank==host_bank)
                    $fatal(1,"THREE_BANK_COLLISION");
                triples=triples+1;
            end
`endif
        end
        if((activity_window||ld_dma_writes==12672)&&result_ack) begin
            result_acks=result_acks+1;
            ld_last_ack=cycles;
        end
    end

`ifdef KWT_UNIFIED_GATE
    string sdf_path;
    initial if($value$plusargs("SDF=%s",sdf_path))
        $sdf_annotate(sdf_path,dut,,"build/optimization/complete_soc/ffn_trb_threebank/sdf_annotation.log","MAXIMUM");
`endif
    initial begin : clock_observation
        realtime edge_time;
        wait(system_reset_n===1'b1);
        @(posedge system_clk);edge_time=$realtime;
        @(posedge system_clk);
        $display("COMPLETE_SOC_MAIN_PERIOD_NS=%0.9f",$realtime-edge_time);
    end
    integer progress_cycle=0;
    always @(negedge system_clk) if(system_reset_n) begin
        progress_cycle=progress_cycle+1;
        if(progress_cycle==100||progress_cycle==1000||progress_cycle==10000)
            $display("THREEBANK_CPU_PROGRESS cycle=%0d pc=%h task=%0d reads=%0d writes=%0d",
                     progress_cycle,inspect_pc,task_request,ld_dma_reads,ld_dma_writes);
        if(progress_cycle==100||progress_cycle==1000||progress_cycle==10000) $fflush;
    end
    initial begin : run
        integer task_number,out_file;
        reg [31:0] value;
        first_task=1;
        if($value$plusargs("FIRST_TASK=%d",first_task)) begin end
        if($value$plusargs("TASKS=%d",requested_tasks)) begin end
        if($value$plusargs("RESULT_DIR=%s",result_directory)) begin end
        if($value$plusargs("FIRMWARE=%s",firmware_path)) begin end
        if($value$plusargs("BOOT_WORDS=%d",boot_count)) begin end
`ifndef KWT_UNIFIED_GATE
`ifndef VERILATOR
        activity_enabled=$value$plusargs("SAIF=%s",saif_path);
        if(activity_enabled) begin $set_gate_level_monitoring("rtl_on");$set_toggle_region(dut);end
`endif
`endif
        $readmemh(firmware_path,boot_words);
/* BOOT */
        for(task_number=0;task_number<requested_tasks;task_number=task_number+1) begin
            wait(task_request==task_number);
            current_case=first_task+2*task_number;
            filename=$sformatf("build/optimization/ffn_ar_area/frozen/images/task_%02d_expected.hex",current_case);
            $readmemh(filename,expected);
            filename=$sformatf("build/optimization/complete_soc/ffn_trb_threebank/packed_inputs/task_%02d_payload.hex",(current_case+1)/2);
            $readmemh(filename,payload);
            filename=$sformatf("build/optimization/complete_soc/ffn_trb_threebank/packed_inputs/task_%02d_addresses.hex",(current_case+1)/2);
            $readmemh(filename,payload_addr);
            @(negedge clk);
            start_cycle=cycles;activity_window=1;activity_begin=$realtime;
            output_seen=0;ld_dma_reads=0;ld_dma_writes=0;result_acks=0;
            host_payload=0;host_control=0;ld_setup_words=0;triples=0;
`ifndef KWT_UNIFIED_GATE
`ifndef VERILATOR
            if(activity_enabled) $toggle_start();
`endif
`endif
            host_cmd_valid=1;host_cmd_read=0;host_cmd_addr=0;host_cmd_wdata=payload[0];
            @(posedge clk);
            while(!host_cmd_ready) @(posedge clk);
            put_word(16383,32'h11223344);
            put_word(29056,32'h55667788);
            put_word(32767,32'h13572468);
            put_word(41472,32'h24681357);
            put_word(59456,32'habcddcba);
            put_word(131011,requested_tasks);
            put_word(131021,0);
            put_word(131022,1);
            put_word(131009,task_number+1);
            put_word(131021,1);
            for(integer i=1;i<11680;i=i+1) put_word(int'(payload_addr[i]),payload[i]);
            host_idle();
            wait(ld_dma_writes==12672);
            @(negedge clk);
            activity_window=0;activity_end=$realtime;task_cycles=last_write-start_cycle+1;
`ifndef KWT_UNIFIED_GATE
`ifndef VERILATOR
            if(activity_enabled) begin
                $toggle_stop();
                saif_output=$sformatf("%s_%02d.saif",saif_path,current_case);
                $toggle_report(saif_output,1.0e-9,"complete_soc_tb.dut");
                $display("UNIFIED_SAIF_SAVED case=%0d path=%s duration_ns=%0.6f cycles=%0d",current_case,saif_output,activity_end-activity_begin,task_cycles);
            end
`endif
`endif
            wait(task_done==task_number);
            if(ld_dma_reads!=11680||result_acks!=12672||host_payload!=11680||host_control!=5||ld_setup_words!=5)
                $fatal(1,"COLD_COUNTS reads=%0d acks=%0d host=%0d control=%0d guards=%0d",ld_dma_reads,result_acks,host_payload,host_control,ld_setup_words);
            out_file=$fopen($sformatf("%s/task_%02d_codes.hex",result_directory,current_case),"w");
            for(integer j=0;j<12672;j=j+1) begin
                get_word(16384+j,value);
                if(value!=={expected[2*j+1],expected[2*j]})
                    $fatal(1,"RESULT_READBACK case=%d index=%d actual=%h",current_case,j,value);
                $fdisplay(out_file,"%04x\n%04x",value[15:0],value[31:16]);
            end
            $fclose(out_file);
            check_guard(16383,32'h11223344);check_guard(29056,32'h55667788);
            check_guard(32767,32'h13572468);check_guard(41472,32'h24681357);check_guard(59456,32'habcddcba);
            $display("THREEBANK_COUNTS case=%0d triples=%0d reads=%0d writes=%0d acks=%0d last_commit=%0d last_ack=%0d",
                current_case,triples,ld_dma_reads,ld_dma_writes,result_acks,last_write-start_cycle,ld_last_ack-start_cycle);
            $display("UNIFIED_PUBLIC_TASK_PASS case=%0d mode=1 source=%0d outputs=25344 checked_physical_addresses=%0d cycles=%0d cpu_data_reads=0 host_payload=11680 host_control=5",
                     current_case,(current_case-1)/2,$countones(output_seen),task_cycles);
            $fflush;
        end
        wait(firmware_done);
        $display("UNIFIED_PUBLIC_ALL_PASS tasks=%0d",requested_tasks);
        $finish;
    end
endmodule

