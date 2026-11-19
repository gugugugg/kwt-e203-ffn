// Public, unmodified e203_cpu_top + ICB accelerator + 512 KiB functional shared SRAM.
// Simulation mailbox is host fixture/control only, never an accelerator bus master.
`include "e203_defines.v"
module kwt_cpu_soc(
    input wire clk,rst_n,
    output wire [31:0] inspect_pc,
    output reg sim_done=0,sim_pass=0
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
    reg [15:0] expected[0:25343];
    reg [7:0] task_shifts[0:13];
    integer requested_tasks=14;
    integer current_task=0,phase=0,verified_tasks=0;
    reg host_request=0;
    integer host_task=0;
    reg [31:0] host_ready=0;
    reg [63:0] cycles=0,commits=0,task_commits=0,phase_start=0,first_input_read=0,last_output_write=0;
    reg [31:0] clear_words=0,load_words=0,starts=0,output_reads=0,output_stores=0;
    reg [31:0] shared_reads=0,shared_writes=0;
    integer data_index,byte_index;
    integer result_fd,mismatch;
    string image_name,result_name;
    string result_directory="build/cpu/results";
    initial begin
        if($value$plusargs("TASKS=%d",requested_tasks)) begin end
        if($value$plusargs("RESULT_DIR=%s",result_directory)) begin end
        if(requested_tasks<1 || requested_tasks>14) $fatal(1,"Invalid task count");
        $readmemh("build/cpu/firmware_itcm.hex",u_cpu.u_e203_srams.u_e203_itcm_ram.u_e203_itcm_gnrl_ram.u_sirv_sim_ram.mem_r);
        $readmemh("build/cpu/images/task_shifts.hex",task_shifts);
    end
    wire commit_fire=u_cpu.u_e203_cpu.u_e203_core.u_e203_exu.u_e203_exu_commit.alu_cmt_i_valid &&
                     u_cpu.u_e203_cpu.u_e203_core.u_e203_exu.u_e203_exu_commit.alu_cmt_i_ready;
    always @(posedge clk) begin
        if(!rst_n) begin cycles<=0; commits<=0; end
        else begin cycles<=cycles+1; if(commit_fire) commits<=commits+1; end
    end

    // Real CPU system-memory ICB, with reproducible command and response waits.
    reg memory_pending=0;
    reg [1:0] memory_delay=0;
    assign mem_icb_cmd_ready=!memory_pending && !mem_icb_rsp_valid && (cycles%5!=0);
    always @(posedge clk) begin
        if(!rst_n) begin
            memory_pending<=0; memory_delay<=0; mem_icb_rsp_valid<=0;
            mem_icb_rsp_err<=0; mem_icb_rsp_rdata<=0; host_ready<=0;
            shared_reads<=0; shared_writes<=0; output_stores<=0;
        end else begin
            if(host_request) begin
                image_name=$sformatf("build/cpu/images/task_%02d_shared.hex",host_task);
                $readmemh(image_name,shared_sram);
                image_name=$sformatf("build/rtl/vectors/task_%02d_expected.hex",host_task);
                $readmemh(image_name,expected);
                host_ready<=32'(host_task+1);
                output_stores<=0; shared_reads<=0; shared_writes<=0;
                first_input_read<=0; last_output_write<=0;
            end
            if(mem_icb_rsp_valid && mem_icb_rsp_ready) mem_icb_rsp_valid<=0;
            if(memory_pending) begin
                if(memory_delay!=0) memory_delay<=memory_delay-1'b1;
                else begin memory_pending<=0; mem_icb_rsp_valid<=1; end
            end
            if(mem_icb_cmd_valid && mem_icb_cmd_ready) begin
                memory_pending<=1; memory_delay<=2'(cycles%3);
                mem_icb_rsp_err<=!(mem_icb_cmd_addr>=32'ha0000000 && mem_icb_cmd_addr<32'ha0080000);
                mem_icb_rsp_rdata<=0;
                if(mem_icb_cmd_addr>=32'ha0000000 && mem_icb_cmd_addr<32'ha0080000) begin
                    if(mem_icb_cmd_read) begin
                        shared_reads<=shared_reads+1;
                        mem_icb_rsp_rdata<=shared_sram[mem_icb_cmd_addr[18:2]];
                        if(phase==2 && first_input_read==0 && mem_icb_cmd_addr<32'ha0003180)
                            first_input_read<=cycles;
                    end else begin
                        shared_writes<=shared_writes+1;
                        for(byte_index=0;byte_index<4;byte_index=byte_index+1)
                            if(mem_icb_cmd_wmask[byte_index])
                                shared_sram[mem_icb_cmd_addr[18:2]][byte_index*8+:8]<=mem_icb_cmd_wdata[byte_index*8+:8];
                        if(mem_icb_cmd_addr>=32'ha0010000 && mem_icb_cmd_addr<32'ha001c600) begin
                            output_stores<=output_stores+32'(mem_icb_cmd_wmask[1:0]==2'b11)+32'(mem_icb_cmd_wmask[3:2]==2'b11);
                            last_output_write<=cycles;
                        end
                    end
                end
            end
        end
    end

    // PPI local decode, preserving the CPU's actual ICB master traffic.
    wire accelerator_select=ppi_icb_cmd_addr[31:8]==24'h100400;
    wire mailbox_select=ppi_icb_cmd_addr[31:8]==24'h100410;
    reg route_pending=0,route_accelerator=0;
    reg mailbox_valid=0,mailbox_error=0;
    reg [31:0] mailbox_data=0;
    wire accelerator_cmd_ready,accelerator_rsp_valid,accelerator_rsp_err;
    wire [31:0] accelerator_rsp_data;
    wire command_fire=ppi_icb_cmd_valid && ppi_icb_cmd_ready;
    assign ppi_icb_cmd_ready=!route_pending && (accelerator_select?accelerator_cmd_ready:!mailbox_valid);
    assign ppi_icb_rsp_valid=route_pending && (route_accelerator?accelerator_rsp_valid:mailbox_valid);
    assign ppi_icb_rsp_rdata=route_accelerator?accelerator_rsp_data:mailbox_data;
    assign ppi_icb_rsp_err=route_accelerator?accelerator_rsp_err:mailbox_error;
    kwt_icb_ffn accelerator(.clk(clk),.rst_n(rst_n),
        .icb_cmd_valid(ppi_icb_cmd_valid && !route_pending && accelerator_select),
        .icb_cmd_ready(accelerator_cmd_ready),.icb_cmd_addr(ppi_icb_cmd_addr[7:0]),
        .icb_cmd_read(ppi_icb_cmd_read),.icb_cmd_wdata(ppi_icb_cmd_wdata),.icb_cmd_wmask(ppi_icb_cmd_wmask),
        .icb_rsp_valid(accelerator_rsp_valid),.icb_rsp_ready(route_pending && route_accelerator && ppi_icb_rsp_ready),
        .icb_rsp_rdata(accelerator_rsp_data),.icb_rsp_err(accelerator_rsp_err));

    always @(posedge clk) begin
        if(!rst_n) begin
            route_pending<=0; route_accelerator<=0; mailbox_valid<=0; mailbox_error<=0; mailbox_data<=0;
            sim_done<=0; sim_pass<=0; host_request<=0; phase<=0;
            clear_words<=0; load_words<=0; starts<=0; output_reads<=0;
        end else begin
            host_request<=0;
            if(ppi_icb_rsp_valid && ppi_icb_rsp_ready) begin route_pending<=0; mailbox_valid<=0; end
            if(command_fire) begin
                route_pending<=1; route_accelerator<=accelerator_select;
                if(accelerator_select) begin
                    if(!ppi_icb_cmd_read && ppi_icb_cmd_addr[7:0]==8'h10) begin
                        if(phase==1) clear_words<=clear_words+1;
                        if(phase==2) load_words<=load_words+1;
                    end
                    if(!ppi_icb_cmd_read && ppi_icb_cmd_addr[7:0]==0 && ppi_icb_cmd_wdata[0]) starts<=starts+1;
                    if(ppi_icb_cmd_read && ppi_icb_cmd_addr[7:0]==8'h18) output_reads<=output_reads+1;
                end else begin
                    mailbox_valid<=1; mailbox_error<=!mailbox_select; mailbox_data<=0;
                    if(mailbox_select) begin
                        if(ppi_icb_cmd_read) begin
                            case(ppi_icb_cmd_addr[7:0])
                                8'h04: mailbox_data<=host_ready;
                                8'h0c: mailbox_data<=32'(requested_tasks);
                                8'h2c: mailbox_data<={24'b0,task_shifts[current_task]};
                                default: mailbox_error<=1;
                            endcase
                        end else begin
                            case(ppi_icb_cmd_addr[7:0])
                                8'h00: begin
                                    if(ppi_icb_cmd_wdata!=32'(verified_tasks)) $fatal(1,"Out-of-order fixture request");
                                    host_task<=int'(ppi_icb_cmd_wdata); current_task<=int'(ppi_icb_cmd_wdata); host_request<=1;
                                    clear_words<=0; load_words<=0; starts<=0; output_reads<=0;
                                end
                                8'h10: begin
                                    phase<=int'(ppi_icb_cmd_wdata);
                                    if(ppi_icb_cmd_wdata==2) begin phase_start<=cycles; task_commits<=commits; end
                                end
                                8'h08: begin
                                    if(ppi_icb_cmd_wdata!=32'(current_task) || verified_tasks!=current_task) $fatal(1,"CPU task completion order");
                                    if(clear_words!=23744 || load_words!=23744 || starts!=1 || output_reads!=25344 || output_stores!=25344)
                                        $fatal(1,"Incomplete real CPU traffic clear=%0d load=%0d start=%0d read=%0d store=%0d",clear_words,load_words,starts,output_reads,output_stores);
                                    mismatch=0;
                                    result_name=$sformatf("%s/task_%02d_codes.hex",result_directory,current_task);
                                    result_fd=$fopen(result_name,"w");
                                    if(result_fd==0) $fatal(1,"Cannot open CPU result file");
                                    for(data_index=0;data_index<25344;data_index=data_index+1) begin
                                        if(shared_sram[(65536+data_index*2)/4][(data_index%2)*16+:16]!==expected[data_index]) mismatch=mismatch+1;
                                        $fdisplay(result_fd,"%04x",shared_sram[(65536+data_index*2)/4][(data_index%2)*16+:16]);
                                    end
                                    $fclose(result_fd);
                                    if(mismatch!=0 || shared_sram[16383]!==32'h11223344 || shared_sram[29056]!==32'h55667788)
                                        $fatal(1,"CPU shared-SRAM output/guard mismatch task=%0d count=%0d",current_task,mismatch);
                                    $display("CPU_TASK_PASS task=%0d words=25344 clear=23744 load=23744 starts=1 read=25344 store=25344 phase_cycles=%0d load_to_writeback_cycles=%0d alu_commits=%0d shared_reads=%0d shared_writes=%0d",current_task,last_output_write-phase_start+1,last_output_write-first_input_read+1,commits-task_commits,shared_reads,shared_writes);
                                    $fflush(); verified_tasks<=verified_tasks+1;
                                end
                                8'h14: begin $display("CPU_FIRMWARE_FAIL code=%h pc=%h",ppi_icb_cmd_wdata,inspect_pc); sim_done<=1; sim_pass<=0; end
                                8'h18: begin
                                    if(ppi_icb_cmd_wdata!=32'hcafe1234 || verified_tasks!=requested_tasks) $fatal(1,"Incomplete CPU run");
                                    $display("CPU_ALL_PASS tasks=%0d output_words=%0d alu_commits=%0d",verified_tasks,verified_tasks*25344,commits);
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
    end
endmodule
