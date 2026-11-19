`timescale 1ns/1fs
module complete_soc_tb;
reg ld_gate_mem_write;reg [16:0] ld_gate_mem_address;reg [3:0] ld_gate_mem_mask;

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
    integer output_count=0,trace_received=0,task_request=-1,layer_request=-1,task_done=-1;
    integer output_stores=0,host_payload=0,host_control=0,data_reads=0,starts=0;
    integer ld_setup_words=0,ld_dma_reads=0,ld_dma_writes=0,ld_cpu_output_words=0;
    reg ld_final_pending=0,ld_result_complete=0;
    longint unsigned ld_last_commit=0,ld_last_ack=0;
    longint unsigned cycles=0,start_cycle=0,last_write=0,task_cycles=0;
longint unsigned res_time_host_initial_begin=0,res_time_host_initial_end=0,res_time_parameter_request=0,res_time_parameter_injection_end=0,res_time_input_first=0,res_time_input_last=0,res_time_parameter_first=0,res_time_parameter_last=0,res_time_mac_first=0,res_time_mac_last=0,res_time_cpu_output_first=0;

    bit activity_window=0,activity_enabled=0;
    string filename,mode_name,saif_path,saif_output,result_directory="build/optimization/complete_soc/ffn_m3_retire/results";
    string firmware_path="build/optimization/firmware/ffn_sr_r3o/firmware_itcm.hex";
    realtime activity_begin,activity_end;
    wire cpu_fire=(~dut.shared_memory.cpu_cmd_valid_BAR)&&dut.shared_memory.cpu_cmd_ready;
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
        if(ld_gate_mem_write) begin
            if(1'b1) shared_write32<=shared_write32+1;
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


    task command_phase;
`ifdef KWT_UNIFIED_TIMED
        if(!clk) @(posedge clk);
        #0.7;
`else
        @(negedge clk);
`endif
    endtask
`ifndef KWT_UNIFIED_GATE
    integer retire_pairs=0,retire_adjacent=0,retire_direct=0;
    integer retire_held_peak=0,retire_reserved_peak=0;
    integer retire_wait[0:2];
    reg retire_previous_pair=0,retire_in_window=0;
`endif
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
                    20: $fatal(1,"UNIFIED_FIRMWARE_ERROR code=%h",cpu_data);
                    24: if(cpu_data==32'hcafe1234) firmware_done=1;
                    48: layer_request=cpu_data;
                    default: ;
                endcase
            end else if(cpu_address>=32'ha0000000&&cpu_address<32'ha007ff00&&current_case>=0) begin
                if(cpu_read) data_reads=data_reads+1;
                else begin
                    if(cpu_address<32'ha0010000||cpu_address>=32'ha0010000+output_count*2)
                        $fatal(1,"UNIFIED_CPU_WRITE_OUTSIDE_OUTPUT address=%h",cpu_address);
                    ld_cpu_output_words=ld_cpu_output_words+1;
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
    wire trace_pair_valid=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.trace_pair_valid;
    wire signed [63:0] trace_high=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.trace_high;
    always @(negedge clk) if(rst_n&&trace_valid) begin : trace_check
        integer position;
        reg signed [63:0] value;
        position=current_mode?int'(trace_index):trace_layer*per_layer+offsets[trace_stage]+trace_index;
        value=current_mode?$signed(expected[trace_index]):expected_trace[position];
        if(trace_seen[position]||trace_data!==value)
            $fatal(1,"UNIFIED_CPU_TRACE_FAIL case=%0d layer=%0d stage=%0d index=%0d got=%0d expected=%0d",current_case,trace_layer,trace_stage,trace_index,trace_data,value);
        trace_seen[position]=1;trace_received=trace_received+1;
        if(trace_pair_valid)begin
            position=position+1;
            value=$signed(expected[trace_index+1]);
            if(trace_seen[position]||trace_high!==value)
                $fatal(1,"UNIFIED_CPU_TRACE_HIGH_FAIL case=%0d index=%0d got=%0d expected=%0d",current_case,trace_index+1,trace_high,value);
            trace_seen[position]=1;trace_received=trace_received+1;
        end
    end
`endif
    always @(negedge clk) if(rst_n&&cycles!=0&&cycles%10000000==0) begin
        $display("UNIFIED_CPU_PROGRESS cycles=%0d case=%0d layer=%0d trace=%0d",cycles,current_case,layer_request,trace_received);$fflush();
    end
`ifdef KWT_UNIFIED_GATE
    always @(negedge clk) if(rst_n&&(cycles==1000||cycles%1000000==0)) begin
        $display("UNIFIED_GATE_PROGRESS cycles=%0d case=%0d request=%0d layer=%0d stores=%0d",cycles,current_case,task_request,layer_request,output_stores);$fflush();
    end
`endif


    initial if($test$plusargs("BOOT_DIAGNOSTICS")) forever begin
        #10000000;
        $display("COMPLETE_SOC_SNAPSHOT time_ns=%0.1f cycles=%0d clock=%b reset=%b request=%0d layer=%0d trace=%0d",$realtime,cycles,system_clk,system_reset_n,task_request,layer_request,trace_received);$fflush();
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
            begin $display("COMPLETE_SOC_BOOT cycles=%0d request=%0d",boot_cycles,task_request);$fflush();end
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
        $readmemh("build/optimization/ffn_ar_area/frozen/images/case_modes.hex",modes);
        $readmemh("build/optimization/ffn_ar_area/frozen/images/case_sources.hex",sources);
        $readmemh(firmware_path,boot_words);
`ifdef KWT_UNIFIED_GATE
        #10;
`endif
        wait(system_reset_n===1'b0);
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
            current_case=first_task+task_number;current_mode=modes[current_case];current_source=sources[current_case];
            if(current_mode) mode_name="linear";else mode_name="encoder";
            output_count=current_mode?25344:6336;parameter_words=current_mode?8704:25856;metadata_words=current_mode?64:16;
            output_stores=0;ld_dma_reads=0;ld_dma_writes=0;ld_cpu_output_words=0;ld_final_pending=0;ld_result_complete=0;ld_last_commit=0;ld_last_ack=0;trace_received=0;data_reads=0;host_payload=0;host_control=0;starts=0;layer_request=-1;
`ifndef KWT_UNIFIED_GATE
            internal_read16=0;internal_write16=0;shared_read32=0;shared_write32=0;
            itcm_read64=0;itcm_write64=0;dtcm_read32=0;dtcm_write32=0;
`endif
            filename=$sformatf("build/optimization/ffn_ar_area/frozen/images/task_%02d_shared.hex",current_case);$readmemh(filename,host_buffer);
            filename=$sformatf("build/optimization/ffn_ar_area/frozen/images/task_%02d_expected.hex",current_case);$readmemh(filename,expected,0,output_count-1);
`ifndef KWT_UNIFIED_GATE
            if(!current_mode) begin filename=$sformatf("build/encoder/vectors/task_%02d_trace.hex",current_source);$readmemh(filename,expected_trace);end
            foreach(trace_seen[s]) trace_seen[s]=0;
`endif
            if(current_mode)begin
                filename=$sformatf("build/optimization/complete_soc/ffn_m3_retire/packed_inputs/task_%02d_packed.hex",current_case);
                $readmemh(filename,host_buffer,0,3167);
            end
            @(negedge clk);
            start_cycle=cycles;res_time_host_initial_begin=0;res_time_input_first=0;res_time_parameter_first=0;res_time_mac_first=0;res_time_cpu_output_first=0;activity_window=1;activity_begin=$realtime;
`ifndef KWT_UNIFIED_GATE
            if(activity_enabled) $toggle_start();
`endif
            for(integer a=0;a<3168;a=a+1) begin put_word(a,host_buffer[a]);host_payload=host_payload+1;end
            put_word(16383,host_buffer[16383]);put_word(16384+output_count/2,host_buffer[16384+output_count/2]);
            put_word(32767,host_buffer[32767]);put_word(32768+parameter_words,host_buffer[32768+parameter_words]);
            put_word(59392+metadata_words,host_buffer[59392+metadata_words]);
            ld_setup_words=5;
            put_word(131011,requested_tasks);put_word(131021,0);put_word(131022,current_mode);put_word(131009,task_number+1);host_control=4;res_time_host_initial_end=cycles-start_cycle;
            host_idle();
            for(layer=0;layer<(current_mode?1:12);layer=layer+1) begin
                wait(layer_request==layer);res_time_parameter_request=cycles-start_cycle;
                filename=$sformatf("build/optimization/ffn_ar_area/frozen/images/%s_layer_%02d_parameters.hex",mode_name,current_mode?current_source:layer);
                $readmemh(filename,host_buffer,32768,32768+parameter_words-1);
                filename=$sformatf("build/optimization/ffn_ar_area/frozen/images/%s_layer_%02d_metadata.hex",mode_name,current_mode?current_source:layer);
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
            if(data_reads!=(current_mode?0:321826)) $fatal(1,"UNIFIED_CPU_PAYLOAD_READ_COUNT case=%0d reads=%0d",current_case,data_reads);
            if(host_payload!=(current_mode?11936:450752)) $fatal(1,"UNIFIED_HOST_PAYLOAD_COUNT");
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
        $display("M3_RETIRE_COUNTS paired_reads=%0d adjacent_pairs=%0d ring_peak=%0d reserved_peak=%0d direct_words=%0d stalls0=%0d stalls1=%0d stalls2=%0d",
            retire_pairs,retire_adjacent,retire_held_peak,retire_reserved_peak,retire_direct,
            retire_wait[0],retire_wait[1],retire_wait[2]);
        $display("FFN_ROUND3_PHASE case=%0d load_active=%0d mac_active=%0d emit_active=%0d fifo_blocked=%0d bus_wait=%0d sram_reads=%0d sram_writes=%0d first_load=%0d first_mac=%0d first_emit=%0d last_emit=%0d",current_case,r3_load_cycles,r3_mac_cycles,r3_emit_cycles,r3_fifo_blocked,r3_bus_wait,internal_read16,internal_write16,r3_first_load,r3_first_mac,r3_first_emit,r3_last_emit);
`endif
        
`ifndef KWT_UNIFIED_GATE
$display("FFN_NEXT_COUNTS case=%0d input_reads=%0d input_writes=%0d weight_reads=%0d weight_writes=%0d bias_reads=%0d bias_writes=%0d shift_reads=%0d shift_writes=%0d stash_reads=%0d stash_writes=%0d wait_input=%0d stash_cycles=%0d input_cycles=%0d input_mac_overlap=%0d",current_case,res_input_reads,res_input_writes,res_weight_reads,res_weight_writes,res_bias_reads,res_bias_writes,res_shift_reads,res_shift_writes,res_stash_reads,res_stash_writes,res_wait_input,res_stash_cycles,res_input_cycles,res_input_mac_overlap);
$display("FFN_TRANSPORT_PHASE case=%0d host_initial_begin=%0d host_initial_end=%0d parameter_request=%0d parameter_injection_end=%0d input_first=%0d input_last=%0d parameter_first=%0d parameter_last=%0d mac_first=%0d mac_last=%0d result_writeback_first=%0d first_emit=%0d last_emit=%0d result_last_store=%0d",current_case,res_time_host_initial_begin,res_time_host_initial_end,res_time_parameter_request,res_time_parameter_injection_end,res_time_input_first,res_time_input_last,res_time_parameter_first,res_time_parameter_last,res_time_mac_first,res_time_mac_last,res_time_cpu_output_first,r3_first_emit,r3_last_emit,last_write-start_cycle);
$display("TRANSPORT_FIFO_PHASE case=%0d full=%0d empty=%0d empty_after_full=%0d starts=%0d",current_case,tr_fifo_full,tr_fifo_empty,tr_fifo_empty_after_full,tr_start_count);
`endif

`ifndef KWT_UNIFIED_GATE
$display("LOADING_DMA_COUNTS case=%0d host_payload=%0d host_setup=%0d host_control=%0d dma_reads=%0d dma_writes=%0d cpu_output_words=%0d last_commit=%0d last_ack=%0d",current_case,host_payload,ld_setup_words,host_control,ld_dma_reads,ld_dma_writes,ld_cpu_output_words,ld_last_commit-start_cycle,ld_last_ack-start_cycle);
`endif
`ifndef KWT_UNIFIED_GATE
$display("LOGIC_POWER_COUNTS case=%0d busy=%0d pipe_blocked=%0d handoff=%0d wait_busy=%0d launches=%0d simultaneous_commands=%0d",current_case,pd_busy,pd_pipe_blocked,pd_handoff,pd_wait_busy,pd_launches,pd_overlap);
`endif
`ifndef KWT_UNIFIED_GATE
        $display("LOGIC_POWER_COMPUTE_COUNTS case=%0d initial_bias_pairs=%0d seed_consumes=%0d next_bias_requests=%0d first_requests=%0d follow_requests=%0d reseed_pairs=%0d shadow_captures=%0d push_cycles=%0d push_words=%0d pair_pushes=%0d",current_case,ap_initial_bias_pairs,jp_seed_consumes,ap_next_bias_requests,ap_first_requests,ap_follow_requests,ap_reseed_pairs,ap_shadow_captures,ap_push_cycles,ap_push_words,ap_pair_pushes);
`endif
        `ifndef KWT_UNIFIED_GATE
$display("C16_EFFICIENCY_EVENTS case=%0d read_handoffs=%0d write_handoffs=%0d",current_case,ce_read_handoffs,ce_write_handoffs);
`endif
`ifndef KWT_UNIFIED_GATE
$display("AR_AREA_EVENTS case=%0d root_edges=%0d shift_edges=%0d init_cycles=%0d direct_tiles=%0d direct_rows=%0d a_req_input_wait=%0d",current_case,wen_root_edges,wen_shift_edges,wen_init_cycles,wen_direct_tiles,wen_direct_rows,wen_a_req_wait);
`endif
if(!ld_result_complete)$fatal(1,"CFE_MAPPED_FINAL_ACK_NOT_OBSERVED");
$display("SR_AREA_MAPPED_ACK case=%0d last_commit=%0d last_ack=%0d",current_case,ld_last_commit-start_cycle,ld_last_ack-start_cycle);
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
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.emission&&!dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.fifo_push) r3_fifo_blocked=r3_fifo_blocked+1;
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.icb_cmd_valid&&!dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.icb_cmd_ready) r3_bus_wait=r3_bus_wait+1;
            r3_sram_reads=r3_sram_reads+$countones(ram_en&~ram_we);
            r3_sram_writes=r3_sram_writes+$countones(ram_en&ram_we);
        end
    end

`endif

`ifndef KWT_UNIFIED_GATE
integer res_input_reads=0;always @(posedge system_clk) if(activity_window) res_input_reads=res_input_reads+(int'(ram_en[0]&&!ram_we[0])+int'(ram_en[1]&&!ram_we[1]));
integer res_input_writes=0;always @(posedge system_clk) if(activity_window) res_input_writes=res_input_writes+(int'(ram_en[0]&&ram_we[0])+int'(ram_en[1]&&ram_we[1]));
integer res_weight_reads=0;always @(posedge system_clk) if(activity_window) res_weight_reads=res_weight_reads+(int'(ram_en[2]&&!ram_we[2])+int'(ram_en[3]&&!ram_we[3])+int'(ram_en[4]&&!ram_we[4])+int'(ram_en[5]&&!ram_we[5])+int'(ram_en[6]&&!ram_we[6])+int'(ram_en[7]&&!ram_we[7])+int'(ram_en[8]&&!ram_we[8])+int'(ram_en[9]&&!ram_we[9])+int'(ram_en[10]&&!ram_we[10])+int'(ram_en[11]&&!ram_we[11])+int'(ram_en[12]&&!ram_we[12])+int'(ram_en[13]&&!ram_we[13])+int'(ram_en[14]&&!ram_we[14])+int'(ram_en[15]&&!ram_we[15])+int'(ram_en[16]&&!ram_we[16])+int'(ram_en[17]&&!ram_we[17]));
integer res_weight_writes=0;always @(posedge system_clk) if(activity_window) res_weight_writes=res_weight_writes+(int'(ram_en[2]&&ram_we[2])+int'(ram_en[3]&&ram_we[3])+int'(ram_en[4]&&ram_we[4])+int'(ram_en[5]&&ram_we[5])+int'(ram_en[6]&&ram_we[6])+int'(ram_en[7]&&ram_we[7])+int'(ram_en[8]&&ram_we[8])+int'(ram_en[9]&&ram_we[9])+int'(ram_en[10]&&ram_we[10])+int'(ram_en[11]&&ram_we[11])+int'(ram_en[12]&&ram_we[12])+int'(ram_en[13]&&ram_we[13])+int'(ram_en[14]&&ram_we[14])+int'(ram_en[15]&&ram_we[15])+int'(ram_en[16]&&ram_we[16])+int'(ram_en[17]&&ram_we[17]));
integer res_bias_reads=0;always @(posedge system_clk) if(activity_window) res_bias_reads=res_bias_reads+(int'(ram_en[18]&&!ram_we[18])+int'(ram_en[19]&&!ram_we[19])+int'(ram_en[20]&&!ram_we[20])+int'(ram_en[21]&&!ram_we[21]));
integer res_bias_writes=0;always @(posedge system_clk) if(activity_window) res_bias_writes=res_bias_writes+(int'(ram_en[18]&&ram_we[18])+int'(ram_en[19]&&ram_we[19])+int'(ram_en[20]&&ram_we[20])+int'(ram_en[21]&&ram_we[21]));
integer res_shift_reads=0;always @(posedge system_clk) if(activity_window) res_shift_reads=res_shift_reads+(int'(ram_en[22]&&!ram_we[22]));
integer res_shift_writes=0;always @(posedge system_clk) if(activity_window) res_shift_writes=res_shift_writes+(int'(ram_en[22]&&ram_we[22]));
integer res_stash_reads=0;always @(posedge system_clk) if(activity_window) res_stash_reads=res_stash_reads+(int'(ram_en[23]&&!ram_we[23])+int'(ram_en[24]&&!ram_we[24])+int'(ram_en[25]&&!ram_we[25]));
integer res_stash_writes=0;always @(posedge system_clk) if(activity_window) res_stash_writes=res_stash_writes+(int'(ram_en[23]&&ram_we[23])+int'(ram_en[24]&&ram_we[24])+int'(ram_en[25]&&ram_we[25]));
integer res_trace=0;always @(posedge system_clk) if(!activity_window) res_trace=0;else if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.trace_valid) begin if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.trace_index!=res_trace) $fatal(1,"TRANSPORT_TRACE_ORDER");res_trace=res_trace+1+int'(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.trace_pair_valid);end
integer res_wait_input=0,res_stash_cycles=0,res_input_cycles=0,res_input_mac_overlap=0;
always @(posedge system_clk) if(activity_window) begin
if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.loading&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.load_kind==0) begin res_input_cycles=res_input_cycles+1;if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==7||dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==9)res_input_mac_overlap=res_input_mac_overlap+1;end
if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==15)res_wait_input=res_wait_input+1;
if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.loading)begin if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.load_kind==0)begin if(res_time_input_first==0)res_time_input_first=cycles-start_cycle;res_time_input_last=cycles-start_cycle;end else begin if(res_time_parameter_first==0)res_time_parameter_first=cycles-start_cycle;res_time_parameter_last=cycles-start_cycle;end end
if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==7||dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==9)begin if(res_time_mac_first==0)res_time_mac_first=cycles-start_cycle;res_time_mac_last=cycles-start_cycle;end
end
longint unsigned tr_fifo_full=0,tr_fifo_empty=0,tr_fifo_empty_after_full=0,tr_start_count=0;reg tr_seen_full=0;
always @(posedge system_clk) if(activity_window) begin if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.layer_start_valid&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.layer_start_ready)tr_start_count=tr_start_count+1;if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.fifo_count==16)begin tr_fifo_full=tr_fifo_full+1;tr_seen_full=1;end if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.icb_cmd_valid&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.icb_cmd_read&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.icb_cmd_addr==8'h34&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.fifo_count<2)begin tr_fifo_empty=tr_fifo_empty+1;if(tr_seen_full)tr_fifo_empty_after_full=tr_fifo_empty_after_full+1;end end
`endif

    wire ld_result_write=ld_gate_mem_write&&1'b1&&
        ld_gate_mem_address>=17'd16384&&ld_gate_mem_address<17'(16384+output_count/2);
    always @(posedge system_clk)begin
        if(ld_final_pending&&dut.ld_rsp_valid&&(!dut.ld_rsp_ready))begin
            ld_result_complete=1;ld_final_pending=0;ld_last_ack=cycles;
        end
        if(activity_window&&ld_result_write)begin
            if(res_time_cpu_output_first==0)res_time_cpu_output_first=cycles-start_cycle;
            output_stores=output_stores+int'(ld_gate_mem_mask[1:0]==3)+int'(ld_gate_mem_mask[3:2]==3);
            ld_last_commit=cycles;last_write=cycles;
            if(output_stores==output_count)ld_final_pending=1;
        end
    end

`ifndef KWT_UNIFIED_GATE
    always @(posedge system_clk)if(activity_window&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.ld_cmd_valid&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.ld_cmd_ready)begin
        if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.ld_cmd_read)ld_dma_reads=ld_dma_reads+1;else ld_dma_writes=ld_dma_writes+1;
    end
`endif

`ifndef KWT_UNIFIED_GATE
    generate for(genvar jp_lane=0;jp_lane<48;jp_lane=jp_lane+1)begin: jp_commit_observer
        integer products=0,seeds=0,outputs=0;
        always @(posedge dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.clk or negedge rst_n)begin
            if(!rst_n)begin products=0;seeds=0;outputs=0;end
            else if(activity_window)begin
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_quant_mask[jp_lane])begin
                    if(products!=64||seeds!=1)$fatal(1,"LOGIC_POWER_COMMIT_ORDER lane=%0d products=%0d seeds=%0d",jp_lane,products,seeds);
                    products=0;seeds=0;outputs=outputs+1;
                end
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_seed_mask[jp_lane])seeds=seeds+1;
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_mac_mask[jp_lane])products=products+1;
            end
        end
    end endgenerate

    integer jp_return_tile=0,jp_return_pair=0;
    reg jp_return_valid=0;
    always @(posedge dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.clk or negedge rst_n)begin
        if(!rst_n)jp_return_valid=0;
        else if(activity_window)begin
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.layer_start_valid&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.layer_start_ready)jp_return_valid=0;
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.ap_er_reseed)begin
                if(!jp_return_valid||jp_return_tile!=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.ap_er_target_tile||jp_return_pair!=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.lane[3:1])
                    $fatal(1,"LOGIC_POWER_BIAS_IDENTITY tile=%0d pair=%0d returned_tile=%0d returned_pair=%0d",dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.tile,dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.lane[3:1],jp_return_tile,jp_return_pair);
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_last_emit_row)jp_return_valid=0;
            end
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.ap_er_request)begin
                if(jp_return_valid)$fatal(1,"LOGIC_POWER_BIAS_RETURN_OVERWRITTEN");
                jp_return_tile=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.ap_er_target_tile;
                jp_return_pair=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.ap_er_request_pair;
                jp_return_valid=1;
            end
        end
    end



    integer wen_root_edges=0,wen_shift_edges=0,wen_init_cycles=0,wen_direct_tiles=0;
    integer wen_direct_rows=0,wen_a_req_wait=0;
    reg [3:0] wen_old_tile=0;
    reg [6:0] wen_old_row=0;
    reg wen_old_emit=0;
    always @(posedge dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.clk)begin
        if(!rst_n)begin wen_root_edges=0;wen_init_cycles=0;wen_direct_tiles=0;wen_direct_rows=0;wen_a_req_wait=0;wen_old_emit=0;wen_old_tile=0;wen_old_row=0;end
        else if(activity_window)begin
            wen_root_edges=wen_root_edges+1;
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.MAC_INIT)wen_init_cycles=wen_init_cycles+1;
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.A_REQ&&!dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.input_complete)wen_a_req_wait=wen_a_req_wait+1;
            wen_old_emit=(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.EMIT);wen_old_tile=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.tile;wen_old_row=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.row;
        end
    end
    always @(posedge dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.shift_clk or negedge rst_n)if(!rst_n)wen_shift_edges=0;else if(activity_window)wen_shift_edges=wen_shift_edges+1;
    always @(negedge dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.clk)if(rst_n&&activity_window&&wen_old_emit&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.state==dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.A_REQ)begin
        if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.row==wen_old_row&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.tile==wen_old_tile+1)wen_direct_tiles=wen_direct_tiles+1;
        if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.row==wen_old_row+2)wen_direct_rows=wen_direct_rows+1;
    end

    generate for(genvar cp_row=0;cp_row<3;cp_row=cp_row+1)begin: r3o_operands
        reg captured=0;
        reg [15:0] expected_operand;
        always @(posedge dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.clk)begin
            captured<=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.rst_n&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.capture_operands;
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.capture_operands)expected_operand<=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.ap_input_rdata[cp_row*16+:16];
        end
        for(genvar cp_copy=0;cp_copy<2;cp_copy=cp_copy+1)begin: copies
            always @(negedge dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.clk)if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.rst_n&&captured)
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_input_return[(cp_row*2+cp_copy)*16+:16]!==expected_operand)
                    $fatal(1,"R3O registered operand differs");
        end
    end endgenerate
`endif

`ifndef KWT_UNIFIED_GATE
    integer pd_busy=0,pd_pipe_blocked=0,pd_handoff=0,pd_wait_busy=0,pd_launches=0,pd_samples=0,pd_overlap=0;
    reg [2:0] pd_previous=0;
    wire pd_pipe_opportunity=1'b0;
    wire pd_handoff_opportunity=(dut.shared_memory.memory_arbiter.active&&dut.shared_memory.memory_arbiter.s_rsp_valid&&dut.shared_memory.memory_arbiter.s_rsp_ready&&
        (dut.shared_memory.memory_arbiter.a_cmd_valid||dut.shared_memory.memory_arbiter.b_cmd_valid)&&!dut.shared_memory.memory_arbiter.s_cmd_ready);
    wire pd_wait_opportunity=dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.busy&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.cpu_cmd_valid&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.cpu_cmd_read&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.cpu_cmd_addr==8'h50&&!dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.cpu_cmd_ready;
    always @(posedge system_clk)if(activity_window)begin
        if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.loading_dma.busy)pd_busy=pd_busy+1;
        if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.launch)pd_launches=pd_launches+1;
        if(pd_pipe_opportunity)pd_pipe_blocked=pd_pipe_blocked+1;
        if(pd_handoff_opportunity)pd_handoff=pd_handoff+1;
        if(pd_wait_opportunity)pd_wait_busy=pd_wait_busy+1;
        if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.loading_dma.mem_cmd_valid&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.loading_dma.mem_cmd_ready&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.loading_dma.pio_cmd_valid&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.loading_dma.pio_cmd_ready)pd_overlap=pd_overlap+1;
        if({pd_pipe_opportunity,pd_handoff_opportunity,pd_wait_opportunity}!=pd_previous&&pd_samples<64)begin
            $display("LOGIC_POWER_EVENT case=%0d cycle=%0d pipe=%0d handoff=%0d wait_busy=%0d fifo=%0d input_ready=%0d output_ready=%0d",current_case,cycles-start_cycle,pd_pipe_opportunity,pd_handoff_opportunity,pd_wait_opportunity,dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.fifo_count,dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.loading_dma.input_ready,dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.dma_frontend.loading_dma.output_ready);
            pd_samples=pd_samples+1;
        end
        pd_previous={pd_pipe_opportunity,pd_handoff_opportunity,pd_wait_opportunity};
    end
`endif

`ifndef KWT_UNIFIED_GATE
    integer ap_initial_bias_pairs=0,jp_seed_consumes=0,ap_next_bias_requests=0;
    integer ap_first_requests=0,ap_follow_requests=0,ap_reseed_pairs=0,ap_shadow_captures=0;
    integer ap_push_cycles=0,ap_push_words=0,ap_pair_pushes=0;
    longint unsigned ap_observed_start=64'hffffffffffffffff;
    always @(posedge system_clk or negedge dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.rst_n)begin
        if(!dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.rst_n)begin ap_initial_bias_pairs=0;jp_seed_consumes=0;ap_next_bias_requests=0;
            ap_first_requests=0;ap_follow_requests=0;ap_reseed_pairs=0;ap_shadow_captures=0;
            ap_push_cycles=0;ap_push_words=0;ap_pair_pushes=0; end
        else begin
            if(start_cycle!=ap_observed_start)begin
                ap_observed_start=start_cycle;
                ap_initial_bias_pairs=0;jp_seed_consumes=0;ap_next_bias_requests=0;
            ap_first_requests=0;ap_follow_requests=0;ap_reseed_pairs=0;ap_shadow_captures=0;
            ap_push_cycles=0;ap_push_words=0;ap_pair_pushes=0;
            end
            if(activity_window)begin
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.bias_capture)ap_initial_bias_pairs=ap_initial_bias_pairs+1;
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.ap_er_seed_wait)jp_seed_consumes=jp_seed_consumes+1;
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.ap_er_request)ap_next_bias_requests=ap_next_bias_requests+1;
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.ap_er_first_request)ap_first_requests=ap_first_requests+1;
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.ap_er_next_request)ap_follow_requests=ap_follow_requests+1;
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.ap_er_reseed)ap_reseed_pairs=ap_reseed_pairs+1;
                if(1'b0)ap_shadow_captures=ap_shadow_captures+1;
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_quant_commit)begin
                    ap_push_cycles=ap_push_cycles+1;
                    ap_push_words=ap_push_words+2;
                    if(1'b1)ap_pair_pushes=ap_pair_pushes+1;
                end
            end
        end
    end
`endif

`ifndef KWT_UNIFIED_GATE
    generate for(genvar car_lane=0;car_lane<48;car_lane=car_lane+1)begin: car_seed_lifecycle
        reg seeded=0;
        integer macs=0;
        always @(posedge dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.clk or negedge dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.rst_n)begin
            if(!dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.rst_n)begin seeded=0;macs=0;end
            else if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.layer_start_valid&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.layer_start_ready)begin seeded=0;macs=0;end
            else if(activity_window)begin
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_quant_mask[car_lane])begin
                    if(!seeded||macs!=64)$fatal(1,"AREA_AR_QUANT_WITHOUT_SEED lane=%0d macs=%0d",car_lane,macs);
                    seeded=0;macs=0;
                end
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_seed_mask[car_lane])begin seeded=1;macs=0;end
                else if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_mac_mask[car_lane])begin
                    if(!seeded)$fatal(1,"AREA_AR_MAC_WITHOUT_SEED lane=%0d",car_lane);
                    macs=macs+1;
                end
            end
        end
    end endgenerate
`endif

`ifndef KWT_UNIFIED_GATE
    generate for(genvar lane_id=0;lane_id<48;lane_id=lane_id+1)begin: ara_shift_lifecycle
        reg has_shift=0;
        reg signed [7:0] shift_at_seed;
        always @(posedge dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.clk or negedge dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.rst_n)begin
            if(!dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.rst_n)has_shift=0;
            else if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.layer_start_valid&&dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.layer_start_ready)has_shift=0;
            else if(activity_window)begin
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_quant_mask[lane_id])begin
                    if(!has_shift || (^dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.shifts[lane_id]===1'bx) || dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.shifts[lane_id]!==shift_at_seed)
                        $fatal(1,"ARA_SHIFT_CONSUMPTION lane=%0d row=%0d tile=%0d shift=%h expected=%h",
                            lane_id,dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.row,dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.tile,dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.shifts[lane_id],shift_at_seed);
                    has_shift=0;
                end
                if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_seed_mask[lane_id])begin
                    shift_at_seed=$signed(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_shift_return[(lane_id%2)*8+:8]);
                    has_shift=1;
                end
            end
        end
    end endgenerate
`endif

`ifndef KWT_UNIFIED_GATE
    integer ce_read_handoffs=0,ce_write_handoffs=0;
    always @(posedge system_clk)if(activity_window&&dut.shared_memory.joined_fire&&
            dut.shared_memory.joined_rsp_valid&&dut.shared_memory.joined_rsp_ready)begin
        if(!dut.shared_memory.memory_arbiter.owner||
           (dut.shared_memory.pending&&
            !(dut.shared_memory.early_response&&dut.shared_memory.next_fast_access))||
           dut.shared_memory.host_cmd_valid||dut.shared_memory.host_rsp_valid||
           dut.shared_memory.read_pending!=dut.shared_memory.joined_cmd_read)
            $fatal(1,"EFFICIENCY_HANDOFF_OWNER_DIRECTION");
        if(dut.shared_memory.joined_cmd_read)ce_read_handoffs=ce_read_handoffs+1;
        else ce_write_handoffs=ce_write_handoffs+1;
    end
`endif
`ifndef KWT_UNIFIED_GATE
    always @(posedge system_clk)begin
        if(!rst_n||(activity_window&&!retire_in_window))begin
            retire_pairs=0;retire_adjacent=0;retire_direct=0;
            retire_held_peak=0;retire_reserved_peak=0;retire_previous_pair=0;
            retire_wait[0]=0;retire_wait[1]=0;retire_wait[2]=0;
        end else if(activity_window)begin
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.output_queue.issue_count==2)begin
                retire_pairs=retire_pairs+1;
                if(retire_previous_pair)retire_adjacent=retire_adjacent+1;
            end
            retire_previous_pair=(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.output_queue.issue_count==2);
            if(retire_held_peak<int'(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.output_queue.held_count))retire_held_peak=int'(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.output_queue.held_count);
            if(retire_reserved_peak<int'(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.output_queue.held_count)+int'(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.output_queue.pending_count))
                retire_reserved_peak=int'(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.output_queue.held_count)+int'(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.output_queue.pending_count);
            retire_direct=retire_direct+int'(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.output_queue.bypass_count);
            if(dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.emission&&!dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.jp_quant_commit)
                retire_wait[dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.emit_row]=retire_wait[dut.soc.u_e203_subsys_main.u_e203_subsys_perips.accelerator.controller.core.emit_row]+1;
        end
        retire_in_window=activity_window;
    end
`endif

always @* begin ld_gate_mem_write=0;ld_gate_mem_address=0;ld_gate_mem_mask=0;
if((!dut.shared_memory.memory.banks_0__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_0__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_0__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_0__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd0,dut.shared_memory.memory.banks_0__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_0__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_0__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_0__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_0__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_0__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_0__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_0__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_0__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_0__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_0__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_0__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_0__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_1__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_1__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_1__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_1__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd1,dut.shared_memory.memory.banks_1__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_1__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_1__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_1__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_1__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_1__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_1__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_1__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_1__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_1__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_1__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_1__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_1__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_2__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_2__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_2__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_2__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd2,dut.shared_memory.memory.banks_2__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_2__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_2__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_2__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_2__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_2__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_2__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_2__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_2__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_2__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_2__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_2__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_2__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_3__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_3__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_3__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_3__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd3,dut.shared_memory.memory.banks_3__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_3__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_3__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_3__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_3__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_3__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_3__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_3__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_3__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_3__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_3__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_3__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_3__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_4__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_4__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_4__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_4__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd4,dut.shared_memory.memory.banks_4__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_4__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_4__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_4__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_4__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_4__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_4__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_4__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_4__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_4__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_4__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_4__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_4__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_5__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_5__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_5__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_5__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd5,dut.shared_memory.memory.banks_5__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_5__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_5__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_5__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_5__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_5__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_5__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_5__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_5__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_5__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_5__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_5__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_5__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_6__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_6__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_6__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_6__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd6,dut.shared_memory.memory.banks_6__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_6__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_6__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_6__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_6__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_6__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_6__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_6__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_6__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_6__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_6__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_6__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_6__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_7__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_7__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_7__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_7__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd7,dut.shared_memory.memory.banks_7__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_7__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_7__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_7__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_7__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_7__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_7__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_7__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_7__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_7__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_7__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_7__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_7__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_8__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_8__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_8__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_8__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd8,dut.shared_memory.memory.banks_8__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_8__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_8__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_8__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_8__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_8__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_8__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_8__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_8__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_8__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_8__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_8__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_8__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_9__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_9__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_9__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_9__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd9,dut.shared_memory.memory.banks_9__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_9__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_9__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_9__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_9__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_9__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_9__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_9__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_9__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_9__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_9__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_9__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_9__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_10__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_10__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_10__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_10__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd10,dut.shared_memory.memory.banks_10__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_10__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_10__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_10__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_10__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_10__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_10__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_10__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_10__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_10__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_10__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_10__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_10__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_11__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_11__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_11__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_11__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd11,dut.shared_memory.memory.banks_11__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_11__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_11__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_11__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_11__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_11__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_11__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_11__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_11__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_11__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_11__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_11__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_11__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_12__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_12__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_12__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_12__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd12,dut.shared_memory.memory.banks_12__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_12__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_12__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_12__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_12__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_12__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_12__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_12__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_12__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_12__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_12__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_12__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_12__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_13__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_13__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_13__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_13__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd13,dut.shared_memory.memory.banks_13__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_13__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_13__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_13__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_13__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_13__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_13__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_13__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_13__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_13__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_13__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_13__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_13__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_14__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_14__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_14__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_14__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd14,dut.shared_memory.memory.banks_14__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_14__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_14__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_14__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_14__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_14__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_14__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_14__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_14__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_14__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_14__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_14__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_14__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_15__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_15__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_15__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_15__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd15,dut.shared_memory.memory.banks_15__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_15__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_15__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_15__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_15__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_15__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_15__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_15__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_15__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_15__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_15__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_15__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_15__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_16__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_16__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_16__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_16__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd16,dut.shared_memory.memory.banks_16__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_16__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_16__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_16__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_16__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_16__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_16__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_16__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_16__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_16__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_16__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_16__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_16__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_17__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_17__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_17__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_17__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd17,dut.shared_memory.memory.banks_17__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_17__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_17__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_17__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_17__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_17__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_17__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_17__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_17__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_17__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_17__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_17__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_17__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_18__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_18__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_18__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_18__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd18,dut.shared_memory.memory.banks_18__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_18__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_18__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_18__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_18__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_18__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_18__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_18__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_18__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_18__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_18__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_18__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_18__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_19__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_19__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_19__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_19__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd19,dut.shared_memory.memory.banks_19__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_19__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_19__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_19__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_19__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_19__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_19__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_19__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_19__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_19__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_19__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_19__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_19__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_20__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_20__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_20__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_20__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd20,dut.shared_memory.memory.banks_20__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_20__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_20__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_20__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_20__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_20__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_20__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_20__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_20__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_20__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_20__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_20__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_20__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_21__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_21__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_21__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_21__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd21,dut.shared_memory.memory.banks_21__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_21__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_21__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_21__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_21__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_21__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_21__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_21__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_21__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_21__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_21__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_21__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_21__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_22__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_22__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_22__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_22__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd22,dut.shared_memory.memory.banks_22__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_22__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_22__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_22__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_22__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_22__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_22__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_22__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_22__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_22__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_22__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_22__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_22__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_23__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_23__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_23__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_23__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd23,dut.shared_memory.memory.banks_23__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_23__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_23__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_23__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_23__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_23__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_23__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_23__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_23__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_23__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_23__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_23__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_23__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_24__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_24__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_24__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_24__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd24,dut.shared_memory.memory.banks_24__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_24__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_24__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_24__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_24__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_24__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_24__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_24__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_24__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_24__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_24__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_24__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_24__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_25__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_25__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_25__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_25__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd25,dut.shared_memory.memory.banks_25__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_25__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_25__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_25__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_25__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_25__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_25__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_25__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_25__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_25__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_25__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_25__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_25__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_26__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_26__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_26__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_26__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd26,dut.shared_memory.memory.banks_26__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_26__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_26__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_26__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_26__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_26__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_26__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_26__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_26__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_26__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_26__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_26__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_26__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_27__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_27__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_27__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_27__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd27,dut.shared_memory.memory.banks_27__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_27__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_27__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_27__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_27__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_27__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_27__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_27__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_27__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_27__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_27__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_27__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_27__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_28__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_28__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_28__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_28__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd28,dut.shared_memory.memory.banks_28__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_28__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_28__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_28__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_28__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_28__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_28__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_28__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_28__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_28__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_28__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_28__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_28__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_29__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_29__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_29__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_29__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd29,dut.shared_memory.memory.banks_29__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_29__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_29__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_29__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_29__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_29__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_29__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_29__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_29__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_29__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_29__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_29__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_29__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_30__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_30__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_30__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_30__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd30,dut.shared_memory.memory.banks_30__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_30__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_30__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_30__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_30__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_30__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_30__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_30__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_30__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_30__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_30__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_30__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_30__halves_0__macro.WEN[0]};end
if((!dut.shared_memory.memory.banks_31__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_31__halves_0__macro.GWEN)||(!dut.shared_memory.memory.banks_31__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_31__halves_1__macro.GWEN))begin
ld_gate_mem_write=1;ld_gate_mem_address={5'd31,dut.shared_memory.memory.banks_31__halves_0__macro.A};
ld_gate_mem_mask={!dut.shared_memory.memory.banks_31__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_31__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_31__halves_1__macro.WEN[8],!dut.shared_memory.memory.banks_31__halves_1__macro.CEN&&!dut.shared_memory.memory.banks_31__halves_1__macro.GWEN&&!dut.shared_memory.memory.banks_31__halves_1__macro.WEN[0],!dut.shared_memory.memory.banks_31__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_31__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_31__halves_0__macro.WEN[8],!dut.shared_memory.memory.banks_31__halves_0__macro.CEN&&!dut.shared_memory.memory.banks_31__halves_0__macro.GWEN&&!dut.shared_memory.memory.banks_31__halves_0__macro.WEN[0]};end
end
endmodule
