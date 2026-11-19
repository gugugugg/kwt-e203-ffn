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
    wire [31:0] inspect_pc=dut.soc.u_e203_subsys_main.u_e203_cpu_top.inspect_pc;
    reg host_cmd_valid=0,host_cmd_read=0;
    wire host_cmd_ready,host_rsp_valid,host_rsp_err;
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
    wire cpu_fire=dut.soc.u_e203_subsys_main.mem_icb_cmd_valid&&dut.soc.u_e203_subsys_main.mem_icb_cmd_ready;
    wire [31:0] cpu_address=dut.soc.u_e203_subsys_main.mem_icb_cmd_addr;
    wire [31:0] cpu_data=dut.soc.u_e203_subsys_main.mem_icb_cmd_wdata;
    wire cpu_read=dut.soc.u_e203_subsys_main.mem_icb_cmd_read;
    wire [3:0] cpu_mask=dut.soc.u_e203_subsys_main.mem_icb_cmd_wmask;
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

    string filename,saif_path,saif_output,result_directory="build/optimization/complete_soc/ffn_che_PR/results";
    string firmware_path="build/optimization/firmware/ffn_trb_threebank/firmware_itcm.hex";
    reg [16:0] payload_addr[0:11679];
    reg [31:0] payload[0:11679];
    reg [12671:0] output_seen;
    integer result_acks=0, result_index;
    reg [31:0] wire_count [0:0];
    wire source_fire=dut.soc.u_e203_subsys_main.ld_cmd_valid&&dut.soc.u_e203_subsys_main.ld_cmd_ready&&dut.soc.u_e203_subsys_main.ld_cmd_read;
    wire result_fire=dut.shared_memory.memory.en&&dut.shared_memory.memory.we&&
        dut.shared_memory.memory.addr>=16384&&dut.shared_memory.memory.addr<29056;
    wire result_ack=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.wb_ack_valid&&
        dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.wb_ack_ready;
`ifndef KWT_UNIFIED_GATE
    integer bus_trace=0;
    initial begin
        string file_name;
        if($value$plusargs("BUS_TRACE=%s",file_name)) begin
            bus_trace=$fopen(file_name,"w");
            if(!bus_trace) $fatal(1,"Cannot open BUS_TRACE");
        end
    end
    always @(posedge clk) if(bus_trace) begin
      if(activity_window) begin
        if(dut.shared_memory.memory.en) begin
            if(dut.shared_memory.memory.we)
                $fdisplay(bus_trace,"W %0d %05h %1h %08h",cycles-start_cycle,
                    dut.shared_memory.memory.addr,dut.shared_memory.memory.wmask,dut.shared_memory.memory.wdata);
            else $fdisplay(bus_trace,"R %0d %05h",cycles-start_cycle,dut.shared_memory.memory.addr);
        end
        if(dut.sysmem_icb_rsp_valid&&dut.sysmem_icb_rsp_ready) begin
            $fdisplay(bus_trace,"T %0d %1h %08h",cycles-start_cycle,dut.sysmem_icb_rsp_err,dut.sysmem_icb_rsp_rdata);
        end
      end
      if((activity_window||ld_dma_writes==12672)&&result_ack)
          $fdisplay(bus_trace,"A %0d",cycles-start_cycle);
    end
    final if(bus_trace) $fclose(bus_trace);
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
            result_index=int'(dut.shared_memory.memory.addr)-16384;
            if(result_index<0||result_index>=12672) $fatal(1,"RESULT_ADDRESS %h",dut.shared_memory.memory.addr);
            if(output_seen[result_index]) $fatal(1,"RESULT_DUPLICATE %d",result_index);
            if(dut.shared_memory.memory.wdata!=={expected[2*result_index+1],expected[2*result_index]})
                $fatal(1,"RESULT_DATA case=%d address=%h got=%h expected=%h cycle=%d",current_case,dut.shared_memory.memory.addr,
                       dut.shared_memory.memory.wdata,{expected[2*result_index+1],expected[2*result_index]},cycles-start_cycle);
            output_seen[result_index]=1;
            ld_dma_writes=ld_dma_writes+1;
            last_write=cycles;
            if(dut.shared_memory.memory.wmask!=4'hf) $fatal(1,"RESULT_MASK");
        end
        if((activity_window||ld_dma_writes==12672)&&result_ack) begin
            result_acks=result_acks+1;
            ld_last_ack=cycles;
        end
    end

`ifdef KWT_UNIFIED_GATE
    string sdf_path;
    initial if($value$plusargs("SDF=%s",sdf_path))
        $sdf_annotate(sdf_path,dut,,"build/optimization/complete_soc/ffn_che_PR/sdf_annotation.log","MAXIMUM");
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
`ifdef KWT_UNIFIED_GATE
        #10;
`endif
        force dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.cs=1'b1;
        force dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.we=1'b1;
        force dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.wem=8'hff;
        force dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.addr=boot_address;
        force dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.din=boot_data;
        force dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.clk=reference_clk;
        for(integer b=0;b<boot_count;b=b+1) begin
            @(negedge clk);boot_address=15'(b);boot_data=boot_words[b];
        end
        @(negedge clk);
        release dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.cs;
        release dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.we;
        release dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.wem;
        release dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.addr;
        release dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.din;
        release dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.clk;
        boot_phase=0;
        @(negedge reference_clk);rst_n=1;
        wait(system_reset_n===1'b1);
        for(integer b=0;b<64;b=b+1) put_word(131008+b,b==3?32'(requested_tasks):0);
        host_idle();
        $display("COMPLETE_SOC_RESET_RELEASED time_ns=%0.3f pc=%h",$realtime,inspect_pc);$fflush();

        for(task_number=0;task_number<requested_tasks;task_number=task_number+1) begin
            wait(task_request==task_number);
            current_case=first_task+2*task_number;
            filename=$sformatf("build/optimization/ffn_ar_area/frozen/images/task_%02d_expected.hex",current_case);
            $readmemh(filename,expected);
            filename=$sformatf("build/optimization/complete_soc/ffn_che_PR/packed_inputs/task_%02d_payload.hex",(current_case+1)/2);
            $readmemh(filename,payload);
            filename=$sformatf("build/optimization/complete_soc/ffn_che_PR/packed_inputs/task_%02d_addresses.hex",(current_case+1)/2);
            $readmemh(filename,payload_addr);
            filename=$sformatf("build/optimization/complete_soc/ffn_che_PR/packed_inputs/task_%02d_count.hex",(current_case+1)/2);
            $readmemh(filename,wire_count);
            @(negedge clk);
            start_cycle=cycles;activity_window=1;activity_begin=$realtime;
            output_seen=0;ld_dma_reads=0;ld_dma_writes=0;result_acks=0;
            host_payload=0;host_control=0;ld_setup_words=0;
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
            for(integer i=1;i<wire_count[0];i=i+1) put_word(int'(payload_addr[i]),payload[i]);
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
            if(ld_dma_reads!=wire_count[0]||result_acks!=12672||host_payload!=wire_count[0]||host_control!=5||ld_setup_words!=5)
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
            $display("SYSBUS3K_COUNTS case=%0d reads=%0d writes=%0d acks=%0d last_commit=%0d last_ack=%0d",
                current_case,ld_dma_reads,ld_dma_writes,result_acks,last_write-start_cycle,ld_last_ack-start_cycle);
            $display("UNIFIED_PUBLIC_TASK_PASS case=%0d mode=1 source=%0d outputs=25344 checked_physical_addresses=%0d cycles=%0d cpu_data_reads=0 host_payload=%0d host_control=5",
                     current_case,(current_case-1)/2,$countones(output_seen),task_cycles,host_payload);
            $fflush;
        end
        wait(firmware_done);
        $display("UNIFIED_PUBLIC_ALL_PASS tasks=%0d",requested_tasks);
        $finish;
    end
endmodule

