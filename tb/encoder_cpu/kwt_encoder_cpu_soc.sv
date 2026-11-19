// Real pinned e203_cpu_top, ICB encoder and exactly 512 KiB shared SRAM.
// File staging buffer/expected arrays are HOST FIXTURES, never CPU-visible memory.
`include "e203_defines.v"
module kwt_encoder_cpu_soc(
    input wire clk,rst_n,
    output wire [31:0] inspect_pc,
    output reg sim_done=0,sim_pass=0,
    output wire [3:0] trace_task,
    output wire trace_valid,
    output wire [3:0] trace_layer,trace_stage,
    output wire [14:0] trace_index,
    output wire signed [63:0] trace_data
);
    wire ppi_icb_cmd_valid,ppi_icb_cmd_ready,ppi_icb_cmd_read,ppi_icb_rsp_valid,ppi_icb_rsp_ready,ppi_icb_rsp_err;
    wire [31:0] ppi_icb_cmd_addr,ppi_icb_cmd_wdata,ppi_icb_rsp_rdata;
    wire [3:0] ppi_icb_cmd_wmask;
    wire mem_icb_cmd_valid,mem_icb_cmd_ready,mem_icb_cmd_read,mem_icb_rsp_ready;
    reg mem_icb_rsp_valid=0,mem_icb_rsp_err=0;
    wire [31:0] mem_icb_cmd_addr,mem_icb_cmd_wdata;
    reg [31:0] mem_icb_rsp_rdata=0;
    wire [3:0] mem_icb_cmd_wmask;
    `include "e203_cpu_instance.svh"
    reg [31:0] shared_sram[0:131071];
    reg [31:0] host_file_buffer[0:131071];
    reg [15:0] expected[0:6335];
    integer requested_tasks=14,first_task=0,current_task=0,verified_tasks=0,host_task=0,host_layer=0;
    integer staged_layers=0;
    reg host_task_request=0,host_layer_request=0,host_active=0,host_is_layer=0;
    reg [16:0] host_address=0,host_last=0;
    reg [31:0] host_ready=0,layer_ready=0;
    reg [63:0] cycles=0,commits=0,task_commits=0,task_start=0,first_input_read=0,last_output_write=0;
    reg [31:0] load_counts[0:4];
    reg [31:0] layer_words[0:11],config_words[0:11],layer_starts[0:11];
    reg [31:0] starts=0,resets=0,output_reads=0,output_stores=0,shared_reads=0,shared_writes=0,host_writes=0;
    reg [2:0] selected_kind=0;
    integer i,byte_index,fd,mismatch;
    string filename,result_name;
    string result_directory="build/encoder_cpu/results";
    assign trace_task=4'(current_task);
    initial begin
        if($value$plusargs("TASKS=%d",requested_tasks)) begin end
        if($value$plusargs("FIRST_TASK=%d",first_task)) begin end
        if($value$plusargs("RESULT_DIR=%s",result_directory)) begin end
        if(requested_tasks<1||requested_tasks>14||first_task<0||first_task+requested_tasks>14) $fatal(1,"Invalid task range");
        $readmemh("build/encoder_cpu/firmware_itcm.hex",u_cpu.u_e203_srams.u_e203_itcm_ram.u_e203_itcm_gnrl_ram.u_sirv_sim_ram.mem_r);
    end
    wire commit_fire=u_cpu.u_e203_cpu.u_e203_core.u_e203_exu.u_e203_exu_commit.alu_cmt_i_valid &&
                     u_cpu.u_e203_cpu.u_e203_core.u_e203_exu.u_e203_exu_commit.alu_cmt_i_ready;
    always @(posedge clk) begin
        if(!rst_n) begin cycles<=0; commits<=0; end
        else begin cycles<=cycles+1; if(commit_fire) commits<=commits+1; end
    end
    reg memory_pending=0;
    reg [1:0] memory_delay=0;
    wire host_slot=host_active&&(cycles%4!=0);
    // Shared access arbitration: host writes and actual CPU requests never use
    // the memory port on the same cycle. CPU response waits are independent.
    assign mem_icb_cmd_ready=!memory_pending&&!mem_icb_rsp_valid&&(!host_active||!host_slot)&&(cycles%5!=0);
    always @(posedge clk) begin
        if(!rst_n) begin
            memory_pending<=0; memory_delay<=0; mem_icb_rsp_valid<=0; mem_icb_rsp_err<=0; mem_icb_rsp_rdata<=0;
            host_active<=0; host_ready<=0; layer_ready<=0; host_address<=0; host_last<=0; host_is_layer<=0;
            output_stores<=0; shared_reads<=0; shared_writes<=0; host_writes<=0; first_input_read<=0; last_output_write<=0;
        end else begin
            if(host_task_request) begin
                if(host_active) $fatal(1,"Overlapping host staging requests");
                filename=$sformatf("build/encoder_cpu/images/task_%02d_shared.hex",host_task);
                $readmemh(filename,host_file_buffer);
                filename=$sformatf("build/encoder_cpu/images/task_%02d_expected.hex",host_task);
                $readmemh(filename,expected);
                host_address<=0; host_last<=131071; host_active<=1; host_is_layer<=0;
                layer_ready<=0; output_stores<=0; shared_reads<=0; shared_writes<=0; host_writes<=0;
                first_input_read<=0; last_output_write<=0;
            end
            if(host_layer_request) begin
                if(host_active||!accelerator.core_layer_request||accelerator.core_layer!=4'(host_layer))
                    $fatal(1,"Layer staging not requested by actual encoder");
                filename=$sformatf("build/encoder_cpu/images/layer_%02d_parameters.hex",host_layer);
                $readmemh(filename,host_file_buffer,32768,58623);
                filename=$sformatf("build/encoder_cpu/images/layer_%02d_config.hex",host_layer);
                $readmemh(filename,host_file_buffer,59392,59407);
                host_address<=32768; host_last<=59407; host_active<=1; host_is_layer<=1;
            end
            if(host_slot) begin
                shared_sram[host_address]<=host_file_buffer[host_address];
                host_writes<=host_writes+1;
                if(host_address==host_last) begin
                    host_active<=0;
                    if(host_is_layer) layer_ready<=32'(host_layer+1);
                    else host_ready<=32'(host_task-first_task+1);
                end else host_address<=host_address+1'b1;
            end
            if(mem_icb_rsp_valid&&mem_icb_rsp_ready) mem_icb_rsp_valid<=0;
            if(memory_pending) begin
                if(memory_delay!=0) memory_delay<=memory_delay-1'b1;
                else begin memory_pending<=0; mem_icb_rsp_valid<=1; end
            end
            if(mem_icb_cmd_valid&&mem_icb_cmd_ready) begin
                memory_pending<=1; memory_delay<=2'(cycles%3); mem_icb_rsp_rdata<=0;
                mem_icb_rsp_err<=!(mem_icb_cmd_addr>=32'ha0000000&&mem_icb_cmd_addr<32'ha0080000);
                if(mem_icb_cmd_addr>=32'ha0000000&&mem_icb_cmd_addr<32'ha0080000) begin
                    if(mem_icb_cmd_read) begin
                        shared_reads<=shared_reads+1; mem_icb_rsp_rdata<=shared_sram[mem_icb_cmd_addr[18:2]];
                        if(first_input_read==0&&mem_icb_cmd_addr<32'ha0003180) first_input_read<=cycles;
                    end else begin
                        if(mem_icb_cmd_addr<32'ha0010000||mem_icb_cmd_addr>=32'ha0013180)
                            $fatal(1,"CPU wrote outside encoder output region: %h",mem_icb_cmd_addr);
                        shared_writes<=shared_writes+1;
                        for(byte_index=0;byte_index<4;byte_index=byte_index+1)
                            if(mem_icb_cmd_wmask[byte_index]) shared_sram[mem_icb_cmd_addr[18:2]][byte_index*8+:8]<=mem_icb_cmd_wdata[byte_index*8+:8];
                        output_stores<=output_stores+32'(mem_icb_cmd_wmask[1:0]==2'b11)+32'(mem_icb_cmd_wmask[3:2]==2'b11);
                        last_output_write<=cycles;
                    end
                end
            end
        end
    end
    wire accelerator_select=ppi_icb_cmd_addr[31:8]==24'h100400;
    wire mailbox_select=ppi_icb_cmd_addr[31:8]==24'h100410;
    reg route_pending=0,route_accelerator=0,mailbox_valid=0,mailbox_error=0;
    reg [31:0] mailbox_data=0;
    wire accelerator_cmd_ready,accelerator_rsp_valid,accelerator_rsp_err;
    wire [31:0] accelerator_rsp_data;
    wire command_slot=cycles%7!=0;
    wire response_slot=cycles%11!=0;
    wire command_fire=ppi_icb_cmd_valid&&ppi_icb_cmd_ready;
    assign ppi_icb_cmd_ready=!route_pending&&command_slot&&(accelerator_select?accelerator_cmd_ready:!mailbox_valid);
    assign ppi_icb_rsp_valid=route_pending&&response_slot&&(route_accelerator?accelerator_rsp_valid:mailbox_valid);
    assign ppi_icb_rsp_rdata=route_accelerator?accelerator_rsp_data:mailbox_data;
    assign ppi_icb_rsp_err=route_accelerator?accelerator_rsp_err:mailbox_error;
    kwt_icb_encoder accelerator(.clk(clk),.rst_n(rst_n),
        .icb_cmd_valid(ppi_icb_cmd_valid&&!route_pending&&command_slot&&accelerator_select),
        .icb_cmd_ready(accelerator_cmd_ready),.icb_cmd_addr(ppi_icb_cmd_addr[7:0]),
        .icb_cmd_read(ppi_icb_cmd_read),.icb_cmd_wdata(ppi_icb_cmd_wdata),.icb_cmd_wmask(ppi_icb_cmd_wmask),
        .icb_rsp_valid(accelerator_rsp_valid),.icb_rsp_ready(route_pending&&route_accelerator&&response_slot&&ppi_icb_rsp_ready),
        .icb_rsp_rdata(accelerator_rsp_data),.icb_rsp_err(accelerator_rsp_err),
        .trace_valid(trace_valid),.trace_layer(trace_layer),.trace_stage(trace_stage),.trace_index(trace_index),.trace_data(trace_data));
    always @(posedge clk) begin
        if(!rst_n) begin
            route_pending<=0; route_accelerator<=0; mailbox_valid<=0; mailbox_error<=0; mailbox_data<=0;
            sim_done<=0; sim_pass<=0; host_task_request<=0; host_layer_request<=0;
            starts<=0; resets<=0; output_reads<=0; staged_layers<=0; selected_kind<=0;
            for(i=0;i<5;i=i+1) load_counts[i]<=0;
            for(i=0;i<12;i=i+1) begin layer_words[i]<=0; config_words[i]<=0; layer_starts[i]<=0; end
        end else begin
            host_task_request<=0; host_layer_request<=0;
            if(ppi_icb_rsp_valid&&ppi_icb_rsp_ready) begin route_pending<=0; mailbox_valid<=0; end
            if(command_fire) begin
                route_pending<=1; route_accelerator<=accelerator_select;
                if(accelerator_select) begin
                    if(!ppi_icb_cmd_read) case(ppi_icb_cmd_addr[7:0])
                        8'h00: begin
                            if(ppi_icb_cmd_wdata==1) starts<=starts+1;
                            if(ppi_icb_cmd_wdata==2) resets<=resets+1;
                        end
                        8'h08: selected_kind<=ppi_icb_cmd_wdata[2:0];
                        8'h10: begin
                            if(selected_kind>4) $fatal(1,"Invalid CPU load kind");
                            load_counts[selected_kind]<=load_counts[selected_kind]+1;
                            if(selected_kind==1) layer_words[host_layer]<=layer_words[host_layer]+1;
                            if(selected_kind==2) config_words[host_layer]<=config_words[host_layer]+1;
                        end
                        8'h18: begin
                            if(layer_words[host_layer]!=51712||config_words[host_layer]!=32||layer_starts[host_layer]!=0)
                                $fatal(1,"CPU layer started without complete fresh parameters/config");
                            layer_starts[host_layer]<=layer_starts[host_layer]+1;
                            $display("CPU_ENCODER_LAYER_START task=%0d layer=%0d words=51712 config=32 cycle=%0d",current_task,host_layer,cycles-task_start); $fflush();
                        end
                        default: begin end
                    endcase
                    if(ppi_icb_cmd_read&&ppi_icb_cmd_addr[7:0]==8'h20) output_reads<=output_reads+1;
                end else begin
                    mailbox_valid<=1; mailbox_error<=!mailbox_select; mailbox_data<=0;
                    if(mailbox_select) begin
                        if(ppi_icb_cmd_read) case(ppi_icb_cmd_addr[7:0])
                            8'h04: mailbox_data<=host_ready;
                            8'h0c: mailbox_data<=32'(requested_tasks);
                            8'h34: mailbox_data<=layer_ready;
                            default: mailbox_error<=1;
                        endcase else case(ppi_icb_cmd_addr[7:0])
                            8'h00: begin
                                if(ppi_icb_cmd_wdata!=32'(verified_tasks)) $fatal(1,"Out-of-order CPU task");
                                current_task<=first_task+int'(ppi_icb_cmd_wdata); host_task<=first_task+int'(ppi_icb_cmd_wdata); host_task_request<=1;
                                starts<=0; resets<=0; output_reads<=0; staged_layers<=0; task_start<=cycles; task_commits<=commits;
                                for(i=0;i<5;i=i+1) load_counts[i]<=0;
                                for(i=0;i<12;i=i+1) begin layer_words[i]<=0; config_words[i]<=0; layer_starts[i]<=0; end
                            end
                            8'h30: begin
                                if(ppi_icb_cmd_wdata!=32'(staged_layers)||staged_layers>=12) $fatal(1,"CPU parameter staging order");
                                host_layer<=int'(ppi_icb_cmd_wdata); host_layer_request<=1; staged_layers<=staged_layers+1;
                            end
                            8'h08: begin
                                if(ppi_icb_cmd_wdata!=32'(current_task-first_task)||current_task!=verified_tasks+first_task||staged_layers!=12) $fatal(1,"CPU encoder completion order");
                                if(starts!=1||resets!=1||output_reads!=6336||output_stores!=6336||host_writes!=450752||
                                   load_counts[0]!=6336||load_counts[1]!=620544||load_counts[2]!=384||load_counts[3]!=8194||load_counts[4]!=8194)
                                    $fatal(1,"Incomplete CPU encoder traffic input=%0d param=%0d config=%0d exp=%0d gelu=%0d out=%0d stores=%0d host=%0d",load_counts[0],load_counts[1],load_counts[2],load_counts[3],load_counts[4],output_reads,output_stores,host_writes);
                                for(i=0;i<12;i=i+1) if(layer_words[i]!=51712||config_words[i]!=32||layer_starts[i]!=1) $fatal(1,"Missing layer %0d",i);
                                mismatch=0; result_name=$sformatf("%s/task_%02d_codes.hex",result_directory,current_task); fd=$fopen(result_name,"w");
                                if(fd==0) $fatal(1,"Cannot open actual CPU output");
                                for(i=0;i<6336;i=i+1) begin
                                    if(shared_sram[(65536+i*2)/4][(i%2)*16+:16]!==expected[i]) mismatch=mismatch+1;
                                    $fdisplay(fd,"%04x",shared_sram[(65536+i*2)/4][(i%2)*16+:16]);
                                end
                                $fclose(fd);
                                if(mismatch!=0||shared_sram[16383]!==32'h11223344||shared_sram[19552]!==32'h55667788||
                                   shared_sram[32767]!==32'h13572468||shared_sram[58624]!==32'h24681357||shared_sram[59408]!==32'habcddcba)
                                    $fatal(1,"Actual CPU encoder output/guard mismatch task=%0d count=%0d",current_task,mismatch);
                                $display("CPU_ENCODER_TASK_PASS task=%0d layers=12 words=6336 load_words=643652 host_words=450752 read=%0d store=%0d task_cycles=%0d load_to_writeback_cycles=%0d alu_commits=%0d shared_reads=%0d shared_writes=%0d",current_task,output_reads,output_stores,last_output_write-task_start+1,last_output_write-first_input_read+1,commits-task_commits,shared_reads,shared_writes);
                                $fflush(); verified_tasks<=verified_tasks+1;
                            end
                            8'h14: begin $display("CPU_FIRMWARE_FAIL code=%h pc=%h",ppi_icb_cmd_wdata,inspect_pc); $fflush(); sim_done<=1; sim_pass<=0; end
                            8'h18: begin
                                if(ppi_icb_cmd_wdata!=32'hcafe1234||verified_tasks!=requested_tasks) $fatal(1,"Incomplete encoder CPU run");
                                $display("CPU_ENCODER_ALL_PASS tasks=%0d first=%0d output_words=%0d alu_commits=%0d",verified_tasks,first_task,verified_tasks*6336,commits);
                                $fflush(); sim_done<=1; sim_pass<=1;
                            end
                            8'h20,8'h24,8'h28: begin $display("CPU_TRAP reg=%h value=%h",ppi_icb_cmd_addr[7:0],ppi_icb_cmd_wdata); $fflush(); end
                            default: mailbox_error<=1;
                        endcase
                    end
                end
            end
        end
    end
endmodule
