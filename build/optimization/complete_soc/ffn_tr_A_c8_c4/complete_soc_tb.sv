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
    integer output_count=0,trace_received=0,task_request=-1,layer_request=-1,task_done=-1;
    integer output_stores=0,host_payload=0,host_control=0,data_reads=0,starts=0;
    longint unsigned cycles=0,start_cycle=0,last_write=0,task_cycles=0;
longint unsigned res_time_host_initial_begin=0,res_time_host_initial_end=0,res_time_parameter_request=0,res_time_parameter_injection_end=0,res_time_input_first=0,res_time_input_last=0,res_time_parameter_first=0,res_time_parameter_last=0,res_time_mac_first=0,res_time_mac_last=0,res_time_cpu_output_first=0;

    bit activity_window=0,activity_enabled=0;
    string filename,mode_name,saif_path,saif_output,result_directory="build/optimization/complete_soc/ffn_tr_A_c8_c4/results";
    string firmware_path="build/optimization/firmware/ffn_tr_A_c8_c4/firmware_itcm.hex";
    realtime activity_begin,activity_end;
    wire cpu_fire=dut.shared_memory.cpu_cmd_valid&&dut.shared_memory.cpu_cmd_ready;
    wire [31:0] cpu_address=dut.shared_memory.cpu_cmd_addr;
    wire [31:0] cpu_data=dut.shared_memory.cpu_cmd_wdata;
    wire cpu_read=dut.shared_memory.cpu_cmd_read;
    wire [3:0] cpu_mask=dut.shared_memory.cpu_cmd_wmask;
    bit firmware_done=0;
`ifndef KWT_UNIFIED_GATE
    `include "sram_probes.svh"
    longint unsigned internal_read16=0,internal_write16=0,shared_read32=0,shared_write32=0;
    longint unsigned itcm_read64=0,itcm_write64=0,dtcm_read32=0,dtcm_write32=0;
    always @(posedge clk) if(activity_window) begin
        internal_read16<=internal_read16+$countones(ram_en&~ram_we);
        internal_write16<=internal_write16+$countones(ram_en&ram_we);
        if(dut.shared_memory.memory.en) begin
            if(dut.shared_memory.memory.we) shared_write32<=shared_write32+1;
            else shared_read32<=shared_read32+1;
        end
    end
    always @(posedge dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.clk)
        if(activity_window&&dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.cs) begin
            if(dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_itcm_ram.we) itcm_write64<=itcm_write64+1;
            else itcm_read64<=itcm_read64+1;
        end
    always @(posedge dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_dtcm_ram.clk)
        if(activity_window&&dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_dtcm_ram.cs) begin
            if(dut.soc.u_e203_subsys_main.u_e203_cpu_top.u_e203_srams.u_e203_dtcm_ram.we) dtcm_write32<=dtcm_write32+1;
            else dtcm_read32<=dtcm_read32+1;
        end
`endif
`ifdef KWT_UNIFIED_GATE
    string sdf_path;
    initial begin
        if($value$plusargs("SDF=%s",sdf_path))
            $sdf_annotate(sdf_path,dut,,"build/optimization/complete_soc/ffn_tr_A_c8_c4/sdf_annotation.log","MAXIMUM");
    end
`endif

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

    always @(posedge clk) if(rst_n) begin
        cycles<=cycles+1;
        if(cpu_fire) begin
            if(cpu_address[31:8]==24'ha007ff&&!cpu_read) begin
                case(cpu_address[7:0])
                    0: task_request=cpu_data;
                    8: task_done=cpu_data;
                    20: $fatal(1,"UNIFIED_FIRMWARE_ERROR code=%h pc=%h",cpu_data,inspect_pc);
                    24: if(cpu_data==32'hcafe1234) firmware_done=1;
                    48: layer_request=cpu_data;
                    default: ;
                endcase
            end else if(cpu_address>=32'ha0000000&&cpu_address<32'ha007ff00&&current_case>=0) begin
                if(cpu_read) data_reads=data_reads+1;
                else begin
                    if(cpu_address<32'ha0010000||cpu_address>=32'ha0010000+output_count*2)
                        $fatal(1,"UNIFIED_CPU_WRITE_OUTSIDE_OUTPUT address=%h",cpu_address);
                    output_stores=output_stores+int'(cpu_mask[1:0]==3)+int'(cpu_mask[3:2]==3);
                    if(res_time_cpu_output_first==0)res_time_cpu_output_first=cycles-start_cycle;last_write=cycles;
                end
            end
        end
`ifndef KWT_UNIFIED_GATE
        if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.kwt_cmd_valid&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.kwt_cmd_ready&&!dut.soc.u_e203_subsys_main.u_e203_subsys_perips.kwt_cmd_read&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.kwt_cmd_addr[7:0]==24&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.kwt_cmd_wdata[0])
            starts=starts+1;
`endif
    end

`ifndef KWT_UNIFIED_GATE
    wire trace_valid=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.trace_valid;
    wire [3:0] trace_layer=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.trace_layer;
    wire [3:0] trace_stage=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.trace_stage;
    wire [14:0] trace_index=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.trace_index;
    wire signed [63:0] trace_data=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.trace_data;
    always @(negedge clk) if(rst_n&&trace_valid) begin : trace_check
        integer position;
        reg signed [63:0] value;
        position=current_mode?int'(trace_index):trace_layer*per_layer+offsets[trace_stage]+trace_index;
        value=current_mode?$signed(expected[trace_index]):expected_trace[position];
        if(trace_seen[position]||trace_data!==value)
            $fatal(1,"UNIFIED_CPU_TRACE_FAIL case=%0d layer=%0d stage=%0d index=%0d got=%0d expected=%0d",current_case,trace_layer,trace_stage,trace_index,trace_data,value);
        trace_seen[position]=1;trace_received=trace_received+1;
    end
`endif
    always @(negedge clk) if(rst_n&&cycles!=0&&cycles%10000000==0) begin
        $display("UNIFIED_CPU_PROGRESS cycles=%0d case=%0d layer=%0d pc=%h trace=%0d",cycles,current_case,layer_request,inspect_pc,trace_received);$fflush();
    end
`ifdef KWT_UNIFIED_GATE
    always @(negedge clk) if(rst_n&&(cycles==1000||cycles%1000000==0)) begin
        $display("UNIFIED_GATE_PROGRESS cycles=%0d case=%0d pc=%h request=%0d layer=%0d stores=%0d",cycles,current_case,inspect_pc,task_request,layer_request,output_stores);$fflush();
    end
`endif


    initial if($test$plusargs("BOOT_DIAGNOSTICS")) forever begin
        #10000000;
        $display("COMPLETE_SOC_SNAPSHOT time_ns=%0.1f cycles=%0d clock=%b reset=%b pc=%h request=%0d layer=%0d trace=%0d",$realtime,cycles,system_clk,system_reset_n,inspect_pc,task_request,layer_request,trace_received);$fflush();
    end
    initial begin : measure_main_clock
        realtime edge_time;
        wait(system_reset_n===1'b1);
        @(posedge system_clk);edge_time=$realtime;
        @(posedge system_clk);
        $display("COMPLETE_SOC_MAIN_PERIOD_NS=%0.9f",$realtime-edge_time);$fflush();
    end
    integer boot_cycles=0;
    always @(negedge system_clk) if(system_reset_n) begin
        boot_cycles=boot_cycles+1;
        if(boot_cycles==100||boot_cycles==1000||boot_cycles==10000||boot_cycles==100000)
            begin $display("COMPLETE_SOC_BOOT cycles=%0d pc=%h request=%0d",boot_cycles,inspect_pc,task_request);$fflush();end
    end

    initial begin : run
        reg [31:0] value;
        integer task_number,layer,parameter_words,metadata_words,parameter_end;
        integer out_file;
        for(integer s=0;s<14;s=s+1) begin offsets[s]=per_layer;per_layer=per_layer+stage_counts[s];end
        if($value$plusargs("FIRST_TASK=%d",first_task)) begin end
        if($value$plusargs("TASKS=%d",requested_tasks)) begin end
        if($value$plusargs("RESULT_DIR=%s",result_directory)) begin end
        if($value$plusargs("FIRMWARE=%s",firmware_path)) begin end
        if($value$plusargs("BOOT_WORDS=%d",boot_count)) begin end
`ifndef KWT_UNIFIED_GATE
        activity_enabled=$value$plusargs("SAIF=%s",saif_path);
        if(activity_enabled) begin $set_gate_level_monitoring("rtl_on");$set_toggle_region(dut);end
`endif
        $readmemh("build/optimization/images/Q2_range/case_modes.hex",modes);
        $readmemh("build/optimization/images/Q2_range/case_sources.hex",sources);
        $readmemh(firmware_path,boot_words);
`ifdef KWT_UNIFIED_GATE
        #10;
`endif
        force dut.shared_memory.clk=reference_clk;
        force dut.shared_memory.rst_n=1'b0;
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
        for(integer b=0;b<64;b=b+1) put_word(131008+b,b==3?32'(requested_tasks):0);
        host_idle();
        repeat(4) @(negedge clk);
        release dut.shared_memory.clk;
        release dut.shared_memory.rst_n;
        boot_phase=0;
        @(negedge reference_clk);rst_n=1;
        wait(system_reset_n===1'b1);
        $display("COMPLETE_SOC_RESET_RELEASED time_ns=%0.3f pc=%h",$realtime,inspect_pc);$fflush();
        for(task_number=0;task_number<requested_tasks;task_number=task_number+1) begin
            wait(task_request==task_number);
            current_case=first_task+task_number;current_mode=modes[current_case];current_source=sources[current_case];
            if(current_mode) mode_name="linear";else mode_name="encoder";
            output_count=current_mode?25344:6336;parameter_words=current_mode?8704:25856;metadata_words=current_mode?64:16;
            output_stores=0;trace_received=0;data_reads=0;host_payload=0;host_control=0;starts=0;layer_request=-1;
`ifndef KWT_UNIFIED_GATE
            internal_read16=0;internal_write16=0;shared_read32=0;shared_write32=0;
            itcm_read64=0;itcm_write64=0;dtcm_read32=0;dtcm_write32=0;
`endif
            filename=$sformatf("build/optimization/images/Q2_range/task_%02d_shared.hex",current_case);$readmemh(filename,host_buffer);
            filename=$sformatf("build/optimization/images/Q2_range/task_%02d_expected.hex",current_case);$readmemh(filename,expected,0,output_count-1);
`ifndef KWT_UNIFIED_GATE
            if(!current_mode) begin filename=$sformatf("build/encoder/vectors/task_%02d_trace.hex",current_source);$readmemh(filename,expected_trace);end
            foreach(trace_seen[s]) trace_seen[s]=0;
`endif
            @(negedge clk);
            start_cycle=cycles;res_time_host_initial_begin=0;res_time_input_first=0;res_time_parameter_first=0;res_time_mac_first=0;res_time_cpu_output_first=0;activity_window=1;activity_begin=$realtime;
`ifndef KWT_UNIFIED_GATE
            if(activity_enabled) $toggle_start();
`endif
            for(integer a=0;a<131072;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
            put_word(131011,requested_tasks);put_word(131021,0);put_word(131022,current_mode);put_word(131009,task_number+1);host_control=4;res_time_host_initial_end=cycles-start_cycle;
            host_idle();
            for(layer=0;layer<(current_mode?1:12);layer=layer+1) begin
                wait(layer_request==layer);res_time_parameter_request=cycles-start_cycle;
                filename=$sformatf("build/optimization/images/Q2_range/%s_layer_%02d_parameters.hex",mode_name,current_mode?current_source:layer);
                $readmemh(filename,host_buffer,32768,32768+parameter_words-1);
                filename=$sformatf("build/optimization/images/Q2_range/%s_layer_%02d_metadata.hex",mode_name,current_mode?current_source:layer);
                $readmemh(filename,host_buffer,59392,59392+metadata_words-1);
                parameter_end=current_mode?32768+parameter_words-1:59407;
                for(integer a=32768;a<=parameter_end;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
                if(current_mode) for(integer a=59392;a<59392+metadata_words;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
                put_word(131021,layer+1);host_control=host_control+1;res_time_parameter_injection_end=cycles-start_cycle;host_idle();
            end
            wait(output_stores==output_count);
            @(negedge clk);
            activity_window=0;activity_end=$realtime;task_cycles=last_write-start_cycle+1;
`ifndef KWT_UNIFIED_GATE
            $display("UNIFIED_SRAM_COUNTS case=%0d internal_read16=%0d internal_write16=%0d shared_read32=%0d shared_write32=%0d itcm_read64=%0d itcm_write64=%0d dtcm_read32=%0d dtcm_write32=%0d",current_case,internal_read16,internal_write16,shared_read32,shared_write32,itcm_read64,itcm_write64,dtcm_read32,dtcm_write32);$fflush();
`endif
`ifndef KWT_UNIFIED_GATE
            if(activity_enabled) begin
                $toggle_stop();
                saif_output=$sformatf("%s_%02d.saif",saif_path,current_case);
                $toggle_report(saif_output,1.0e-9,"complete_soc_tb.dut");
                $display("UNIFIED_SAIF_SAVED case=%0d path=%s duration_ns=%0.6f cycles=%0d",current_case,saif_output,activity_end-activity_begin,task_cycles);$fflush();
            end
`endif
            wait(task_done==task_number);
            if(data_reads!=(current_mode?11936:321826)) $fatal(1,"UNIFIED_CPU_PAYLOAD_READ_COUNT case=%0d reads=%0d",current_case,data_reads);
            if(host_payload!=(current_mode?139840:450752)) $fatal(1,"UNIFIED_HOST_PAYLOAD_COUNT");
`ifndef KWT_UNIFIED_GATE
            if(trace_received!=(current_mode?25344:1603800)) $fatal(1,"UNIFIED_TRACE_INCOMPLETE case=%0d count=%0d",current_case,trace_received);
            if(starts!=(current_mode?1:12)) $fatal(1,"UNIFIED_LAYER_START_COUNT");
`endif
            out_file=$fopen($sformatf("%s/task_%02d_codes.hex",result_directory,current_case),"w");
            for(integer a=0;a<output_count/2;a=a+1) begin
                get_word(16384+a,value);
                if(value!=={expected[a*2+1],expected[a*2]}) $fatal(1,"UNIFIED_SHARED_READBACK_FAIL case=%0d word=%0d got=%h expected=%h",current_case,a,value,{expected[a*2+1],expected[a*2]});
                $fdisplay(out_file,"%04x",value[15:0]);$fdisplay(out_file,"%04x",value[31:16]);
            end
            $fclose(out_file);
            check_guard(16383,32'h11223344);check_guard(16384+output_count/2,32'h55667788);
            check_guard(32767,32'h13572468);check_guard(32768+parameter_words,32'h24681357);
            check_guard(59392+metadata_words,32'habcddcba);
            
`ifndef KWT_UNIFIED_GATE
        $display("FFN_ROUND3_PHASE case=%0d load_active=%0d mac_active=%0d emit_active=%0d fifo_blocked=%0d bus_wait=%0d sram_reads=%0d sram_writes=%0d first_load=%0d first_mac=%0d first_emit=%0d last_emit=%0d",current_case,r3_load_cycles,r3_mac_cycles,r3_emit_cycles,r3_fifo_blocked,r3_bus_wait,internal_read16,internal_write16,r3_first_load,r3_first_mac,r3_first_emit,r3_last_emit);
`endif
        
`ifndef KWT_UNIFIED_GATE
$display("FFN_NEXT_COUNTS case=%0d input_reads=%0d input_writes=%0d weight_reads=%0d weight_writes=%0d bias_reads=%0d bias_writes=%0d shift_reads=%0d shift_writes=%0d stash_reads=%0d stash_writes=%0d wait_input=%0d stash_cycles=%0d input_cycles=%0d input_mac_overlap=%0d",current_case,res_input_reads,res_input_writes,res_weight_reads,res_weight_writes,res_bias_reads,res_bias_writes,res_shift_reads,res_shift_writes,res_stash_reads,res_stash_writes,res_wait_input,res_stash_cycles,res_input_cycles,res_input_mac_overlap);
$display("FFN_TRANSPORT_PHASE case=%0d host_initial_begin=%0d host_initial_end=%0d parameter_request=%0d parameter_injection_end=%0d input_first=%0d input_last=%0d parameter_first=%0d parameter_last=%0d mac_first=%0d mac_last=%0d cpu_output_first=%0d first_emit=%0d last_emit=%0d cpu_last_store=%0d",current_case,res_time_host_initial_begin,res_time_host_initial_end,res_time_parameter_request,res_time_parameter_injection_end,res_time_input_first,res_time_input_last,res_time_parameter_first,res_time_parameter_last,res_time_mac_first,res_time_mac_last,res_time_cpu_output_first,r3_first_emit,r3_last_emit,last_write-start_cycle);
$display("TRANSPORT_FIFO_PHASE case=%0d full=%0d empty=%0d empty_after_full=%0d starts=%0d",current_case,tr_fifo_full,tr_fifo_empty,tr_fifo_empty_after_full,tr_start_count);
`endif
$display("UNIFIED_PUBLIC_TASK_PASS case=%0d mode=%0d source=%0d outputs=%0d trace=%0d cycles=%0d cpu_data_reads=%0d host_payload=%0d host_control=%0d",current_case,current_mode,current_source,output_count,trace_received,task_cycles,data_reads,host_payload,host_control);$fflush();
        end
        wait(firmware_done);
        $display("UNIFIED_PUBLIC_ALL_PASS tasks=%0d",requested_tasks);$fflush();$finish;
    end

`ifndef KWT_UNIFIED_GATE

    longint unsigned r3_window_cycles=0,r3_load_cycles=0,r3_mac_cycles=0,
        r3_emit_cycles=0,r3_fifo_blocked=0,r3_bus_wait=0,r3_sram_reads=0,r3_sram_writes=0;
    longint unsigned r3_first_load=0,r3_first_mac=0,r3_first_emit=0,r3_last_emit=0;
    longint unsigned r3_observed_start=64'hffffffffffffffff;
    always @(negedge system_clk) begin
        if(start_cycle!=r3_observed_start) begin
            r3_observed_start=start_cycle;
            r3_window_cycles=0;r3_load_cycles=0;r3_mac_cycles=0;r3_emit_cycles=0;
            r3_fifo_blocked=0;r3_bus_wait=0;r3_sram_reads=0;r3_sram_writes=0;
            r3_first_load=0;r3_first_mac=0;r3_first_emit=0;r3_last_emit=0;
        end
        if(activity_window) begin
            r3_window_cycles=r3_window_cycles+1;
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.loading) begin
                r3_load_cycles=r3_load_cycles+1;
                if(!r3_first_load) r3_first_load=cycles-start_cycle;
            end
            if((dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==7)||(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==9)) begin
                r3_mac_cycles=r3_mac_cycles+1;
                if(!r3_first_mac) r3_first_mac=cycles-start_cycle;
            end
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.fifo_push) begin
                r3_emit_cycles=r3_emit_cycles+1;
                if(!r3_first_emit) r3_first_emit=cycles-start_cycle;
                r3_last_emit=cycles-start_cycle;
            end
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.emission&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.fifo_count==16&&!(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.pop_count!=0)) r3_fifo_blocked=r3_fifo_blocked+1;
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.icb_cmd_valid&&!dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.icb_cmd_ready) r3_bus_wait=r3_bus_wait+1;
            r3_sram_reads=r3_sram_reads+$countones(ram_en&~ram_we);
            r3_sram_writes=r3_sram_writes+$countones(ram_en&ram_we);
        end
    end

`endif

`ifndef KWT_UNIFIED_GATE
integer res_input_reads=0;always @(posedge system_clk) if(activity_window) res_input_reads=res_input_reads+(0);
integer res_input_writes=0;always @(posedge system_clk) if(activity_window) res_input_writes=res_input_writes+(0);
integer res_weight_reads=0;always @(posedge system_clk) if(activity_window) res_weight_reads=res_weight_reads+(int'(ram_en[0]&&!ram_we[0])+int'(ram_en[1]&&!ram_we[1])+int'(ram_en[2]&&!ram_we[2])+int'(ram_en[3]&&!ram_we[3])+int'(ram_en[4]&&!ram_we[4])+int'(ram_en[5]&&!ram_we[5])+int'(ram_en[6]&&!ram_we[6])+int'(ram_en[7]&&!ram_we[7])+int'(ram_en[8]&&!ram_we[8])+int'(ram_en[9]&&!ram_we[9])+int'(ram_en[10]&&!ram_we[10])+int'(ram_en[11]&&!ram_we[11])+int'(ram_en[12]&&!ram_we[12])+int'(ram_en[13]&&!ram_we[13])+int'(ram_en[14]&&!ram_we[14])+int'(ram_en[15]&&!ram_we[15]));
integer res_weight_writes=0;always @(posedge system_clk) if(activity_window) res_weight_writes=res_weight_writes+(int'(ram_en[0]&&ram_we[0])+int'(ram_en[1]&&ram_we[1])+int'(ram_en[2]&&ram_we[2])+int'(ram_en[3]&&ram_we[3])+int'(ram_en[4]&&ram_we[4])+int'(ram_en[5]&&ram_we[5])+int'(ram_en[6]&&ram_we[6])+int'(ram_en[7]&&ram_we[7])+int'(ram_en[8]&&ram_we[8])+int'(ram_en[9]&&ram_we[9])+int'(ram_en[10]&&ram_we[10])+int'(ram_en[11]&&ram_we[11])+int'(ram_en[12]&&ram_we[12])+int'(ram_en[13]&&ram_we[13])+int'(ram_en[14]&&ram_we[14])+int'(ram_en[15]&&ram_we[15]));
integer res_bias_reads=0;always @(posedge system_clk) if(activity_window) res_bias_reads=res_bias_reads+(int'(ram_en[16]&&!ram_we[16])+int'(ram_en[17]&&!ram_we[17])+int'(ram_en[18]&&!ram_we[18])+int'(ram_en[19]&&!ram_we[19]));
integer res_bias_writes=0;always @(posedge system_clk) if(activity_window) res_bias_writes=res_bias_writes+(int'(ram_en[16]&&ram_we[16])+int'(ram_en[17]&&ram_we[17])+int'(ram_en[18]&&ram_we[18])+int'(ram_en[19]&&ram_we[19]));
integer res_shift_reads=0;always @(posedge system_clk) if(activity_window) res_shift_reads=res_shift_reads+(int'(ram_en[20]&&!ram_we[20]));
integer res_shift_writes=0;always @(posedge system_clk) if(activity_window) res_shift_writes=res_shift_writes+(int'(ram_en[20]&&ram_we[20]));
integer res_stash_reads=0;always @(posedge system_clk) if(activity_window) res_stash_reads=res_stash_reads+(0);
integer res_stash_writes=0;always @(posedge system_clk) if(activity_window) res_stash_writes=res_stash_writes+(0);
integer res_trace=0;always @(posedge system_clk) if(!activity_window) res_trace=0;else if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.trace_valid) begin if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.trace_index!=res_trace) $fatal(1,"TRANSPORT_TRACE_ORDER");res_trace=res_trace+1;end
integer res_wait_input=0,res_stash_cycles=0,res_input_cycles=0,res_input_mac_overlap=0;
always @(posedge system_clk) if(activity_window) begin
if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.loading&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.load_kind==0) begin res_input_cycles=res_input_cycles+1;if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==7||dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==9)res_input_mac_overlap=res_input_mac_overlap+1;end
if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==15)res_wait_input=res_wait_input+1;
if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==11||dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==13)res_stash_cycles=res_stash_cycles+1;
if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.loading)begin if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.load_kind==0)begin if(res_time_input_first==0)res_time_input_first=cycles-start_cycle;res_time_input_last=cycles-start_cycle;end else begin if(res_time_parameter_first==0)res_time_parameter_first=cycles-start_cycle;res_time_parameter_last=cycles-start_cycle;end end
if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==7||dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==9)begin if(res_time_mac_first==0)res_time_mac_first=cycles-start_cycle;res_time_mac_last=cycles-start_cycle;end
end
longint unsigned tr_fifo_full=0,tr_fifo_empty=0,tr_fifo_empty_after_full=0,tr_start_count=0;reg tr_seen_full=0;
always @(posedge system_clk) if(activity_window) begin if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.layer_start_valid&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.layer_start_ready)tr_start_count=tr_start_count+1;if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.fifo_count==16)begin tr_fifo_full=tr_fifo_full+1;tr_seen_full=1;end if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.icb_cmd_valid&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.icb_cmd_read&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.icb_cmd_addr==8'h34&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.fifo_count<2)begin tr_fifo_empty=tr_fifo_empty+1;if(tr_seen_full)tr_fifo_empty_after_full=tr_fifo_empty_after_full+1;end end
`endif
endmodule
