`timescale 1ns/1fs
module complete_soc_tb;
    reg reference_clk=0,ls_clk=0,rst_n=0;
    reg boot_phase=1;
    wire system_clk,system_reset_n;
    wire clk=boot_phase?reference_clk:system_clk;
    initial begin
`ifdef KWT_UNIFIED_GATE
        #100;
`endif
        forever #3.333333333 reference_clk=~reference_clk;
    end
    always #15258.7890625 ls_clk=~ls_clk;

    reg host_cmd_valid=0,host_cmd_read=0;
    wire host_cmd_ready,host_rsp_valid;
    reg [16:0] host_cmd_addr=0;
    reg [31:0] host_cmd_wdata=0;
    reg [3:0] host_cmd_wmask=15;
    wire host_rsp_ready=1;
    wire [31:0] host_rsp_rdata;
    `include "platform_instance.svh"
    `include "boot_count.svh"
    reg [63:0] boot_words[0:32767];
    reg [14:0] boot_address=0;
    reg [63:0] boot_data=0;
    reg [31:0] host_buffer[0:131071],modes[0:25],sources[0:25];
    reg [15:0] expected[0:25343];
    reg signed [63:0] expected_trace[0:1603799];
    bit trace_seen[0:1603799];
    integer stage_counts[0:13]='{6336,6336,6336,9801,9801,6336,6336,6336,6336,25344,25344,6336,6336,6336};
    integer offsets[0:13],per_layer=0;
    integer first_task=0,requested_tasks=1,current_case=-1,current_mode=0,current_source=0,boot_count=BOOT_WORDS;
    integer startup_group_joins=0;
    integer output_count=0,trace_received=0,task_request=-1,layer_request=-1,task_done=-1;
    integer output_stores=0,host_payload=0,host_control=0,data_reads=0,starts=0;
    integer ld_setup_words=0,ld_dma_reads=0,ld_dma_writes=0,ld_cpu_output_words=0;
    reg ld_final_pending=0,ld_result_complete=0;
    longint unsigned ld_last_commit=0,ld_last_ack=0;
    longint unsigned cycles=0,start_cycle=0,last_write=0,task_cycles=0;
longint unsigned res_time_host_initial_begin=0,res_time_host_initial_end=0,res_time_parameter_request=0,res_time_parameter_injection_end=0,res_time_input_first=0,res_time_input_last=0,res_time_parameter_first=0,res_time_parameter_last=0,res_time_mac_first=0,res_time_mac_last=0,res_time_cpu_output_first=0;

    bit activity_window=0,activity_enabled=0;
    realtime activity_begin,activity_end;
    wire cpu_fire=(!dut.shared_memory.cpu_cmd_valid_BAR)&&dut.shared_memory.cpu_cmd_ready;
    wire [31:0] cpu_address=dut.shared_memory.cpu_cmd_addr;
    wire [31:0] cpu_data=dut.shared_memory.cpu_cmd_wdata;
    wire cpu_read=dut.shared_memory.cpu_cmd_read;
    bit firmware_done=0;
    task command_phase;
`ifdef KWT_UNIFIED_TIMED
        if(!clk) @(posedge clk);
        #0.7;
`else
        @(negedge clk);
`endif
    endtask
    task put_word(input integer address,input reg [31:0] value);
        command_phase();
        host_cmd_valid=1;host_cmd_read=0;host_cmd_addr=17'(address);host_cmd_wdata=value;
        @(posedge clk);
        while(!host_cmd_ready) @(posedge clk);
    endtask
    task host_idle;
        command_phase();host_cmd_valid=0;
    endtask
    task get_word(input integer address,output reg [31:0] value);
        command_phase();host_cmd_valid=1;host_cmd_read=1;host_cmd_addr=17'(address);
        @(posedge clk);
        while(!host_cmd_ready) @(posedge clk);
        command_phase();host_cmd_valid=0;
        @(posedge clk);
        while(!host_rsp_valid) @(posedge clk);
        value=host_rsp_rdata;
    endtask
    task check_guard(input integer address,input reg [31:0] expected_value);
        reg [31:0] value;
        get_word(address,value);
        if(value!==expected_value) $fatal(1,"UNIFIED_GUARD_FAIL case=%0d address=%0d got=%h expected=%h",current_case,address,value,expected_value);
    endtask

    string filename,saif_path,saif_output,result_directory="build/optimization/complete_soc/ffn_trb_threebank/results";
    string firmware_path="build/optimization/firmware/ffn_trb_threebank/firmware_itcm.hex";
    reg [16:0] payload_addr[0:11679];
    reg [31:0] payload[0:11679];
    reg [12671:0] output_seen;
    integer triples=0, result_acks=0, result_index;
    wire source_fire=dut.ld_cmd_valid&&dut.ld_cmd_ready;
    reg [3:0] result_bank_write;
    reg [16:0] physical_result_addr;
    reg [31:0] physical_result_data;
    always @* begin
        result_bank_write=0;physical_result_addr=0;physical_result_data=0;
        if(!dut.shared_memory.memory.banks_4__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_4__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_4__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_4__halves_1__macro.GWEN&&dut.shared_memory.memory.banks_4__halves_0__macro.WEN==0&&dut.shared_memory.memory.banks_4__halves_1__macro.WEN==0) begin
            result_bank_write[0]=1;physical_result_addr={5'd4,dut.shared_memory.memory.banks_4__halves_0__macro.A};physical_result_data={dut.shared_memory.memory.banks_4__halves_1__macro.D,dut.shared_memory.memory.banks_4__halves_0__macro.D};
        end
        if(!dut.shared_memory.memory.banks_5__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_5__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_5__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_5__halves_1__macro.GWEN&&dut.shared_memory.memory.banks_5__halves_0__macro.WEN==0&&dut.shared_memory.memory.banks_5__halves_1__macro.WEN==0) begin
            result_bank_write[1]=1;physical_result_addr={5'd5,dut.shared_memory.memory.banks_5__halves_0__macro.A};physical_result_data={dut.shared_memory.memory.banks_5__halves_1__macro.D,dut.shared_memory.memory.banks_5__halves_0__macro.D};
        end
        if(!dut.shared_memory.memory.banks_6__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_6__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_6__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_6__halves_1__macro.GWEN&&dut.shared_memory.memory.banks_6__halves_0__macro.WEN==0&&dut.shared_memory.memory.banks_6__halves_1__macro.WEN==0) begin
            result_bank_write[2]=1;physical_result_addr={5'd6,dut.shared_memory.memory.banks_6__halves_0__macro.A};physical_result_data={dut.shared_memory.memory.banks_6__halves_1__macro.D,dut.shared_memory.memory.banks_6__halves_0__macro.D};
        end
        if(!dut.shared_memory.memory.banks_7__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_7__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_7__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_7__halves_1__macro.GWEN&&dut.shared_memory.memory.banks_7__halves_0__macro.WEN==0&&dut.shared_memory.memory.banks_7__halves_1__macro.WEN==0&&dut.shared_memory.memory.banks_7__halves_0__macro.A<12'h180) begin
            result_bank_write[3]=1;physical_result_addr={5'd7,dut.shared_memory.memory.banks_7__halves_0__macro.A};physical_result_data={dut.shared_memory.memory.banks_7__halves_1__macro.D,dut.shared_memory.memory.banks_7__halves_0__macro.D};
        end
    end
    wire result_fire=|result_bank_write;
    always @(posedge clk) if(activity_window&&$countones(result_bank_write)>1) $fatal(1,"MULTIPLE_RESULT_MACRO_WRITES");
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
                20: $fatal(1,"UNIFIED_FIRMWARE_ERROR code=%h",cpu_data);
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
            result_index=int'(physical_result_addr)-16384;
            if(result_index<0||result_index>=12672) $fatal(1,"RESULT_ADDRESS %h",dut.wb_addr);
            if(output_seen[result_index]) $fatal(1,"RESULT_DUPLICATE %d",result_index);
            if(physical_result_data!=={expected[2*result_index+1],expected[2*result_index]})
                $fatal(1,"RESULT_DATA case=%d address=%h got=%h expected=%h cycle=%d",current_case,physical_result_addr,
                       physical_result_data,{expected[2*result_index+1],expected[2*result_index]},cycles-start_cycle);
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
            $display("THREEBANK_CPU_PROGRESS cycle=%0d task=%0d reads=%0d writes=%0d",
                     progress_cycle,task_request,ld_dma_reads,ld_dma_writes);
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
        @(negedge reference_clk);
        for(integer b=0;b<boot_count;b=b+1) begin
            case(b>>12)
                0: for(integer k=0;k<64;k=k+1) dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.u_sram_wrap_32KX64.memory.banks_0__wide_macro.mem[(b&4095)>>3][k*8+(b&7)]=boot_words[b][k];
                1: for(integer k=0;k<64;k=k+1) dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.u_sram_wrap_32KX64.memory.banks_1__wide_macro.mem[(b&4095)>>3][k*8+(b&7)]=boot_words[b][k];
                2: for(integer k=0;k<64;k=k+1) dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.u_sram_wrap_32KX64.memory.banks_2__wide_macro.mem[(b&4095)>>3][k*8+(b&7)]=boot_words[b][k];
                3: for(integer k=0;k<64;k=k+1) dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.u_sram_wrap_32KX64.memory.banks_3__wide_macro.mem[(b&4095)>>3][k*8+(b&7)]=boot_words[b][k];
                4: for(integer k=0;k<64;k=k+1) dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.u_sram_wrap_32KX64.memory.banks_4__wide_macro.mem[(b&4095)>>3][k*8+(b&7)]=boot_words[b][k];
                5: for(integer k=0;k<64;k=k+1) dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.u_sram_wrap_32KX64.memory.banks_5__wide_macro.mem[(b&4095)>>3][k*8+(b&7)]=boot_words[b][k];
                6: for(integer k=0;k<64;k=k+1) dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.u_sram_wrap_32KX64.memory.banks_6__wide_macro.mem[(b&4095)>>3][k*8+(b&7)]=boot_words[b][k];
                7: for(integer k=0;k<64;k=k+1) dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.u_sram_wrap_32KX64.memory.banks_7__wide_macro.mem[(b&4095)>>3][k*8+(b&7)]=boot_words[b][k];
            endcase
        end
        for(integer b=0;b<64;b=b+1) begin
            for(integer k=0;k<16;k=k+1) dut.shared_memory.memory.banks_31__halves_0__macro.mem[(4032+b)>>3][k*8+(b&7)]=b==3 ? ((requested_tasks >> (k+0)) & 1) : 1'b0;
            for(integer k=0;k<16;k=k+1) dut.shared_memory.memory.banks_31__halves_1__macro.mem[(4032+b)>>3][k*8+(b&7)]=b==3 ? ((requested_tasks >> (k+16)) & 1) : 1'b0;
        end
        host_idle();
        boot_phase=0;
        @(negedge reference_clk);rst_n=1;
        wait(system_reset_n===1'b1);
        $display("COMPLETE_SOC_RESET_RELEASED time_ns=%0.3f",$realtime);$fflush();

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

