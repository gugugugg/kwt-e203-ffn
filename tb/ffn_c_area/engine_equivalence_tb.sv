`timescale 1ns/1ps
module car_engine_equivalence_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,start=0,direction=0;
    reg [31:0] start_address=32'ha0000000,word_count=0;
    integer cycles=0,source_index=0,dest_count=0,descriptors=0;
    integer simultaneous=0,slot_two=0;
    reg error_source=0,error_destination=0;
    wire input_ready=(cycles%13)>=6,output_ready=(cycles%5)!=0;
    wire a_busy,a_done,a_error,b_busy,b_done,b_error;
    wire a_mv,a_mr,a_mrr,a_pv,a_pr,a_prr,b_mv,b_mr,b_mrr,b_pv,b_pr,b_prr;
    wire [31:0] a_ma,a_mw,a_pw,b_ma,b_mw,b_pw;
    wire [7:0] a_pa,b_pa;
    wire [3:0] a_mm,a_pm,b_mm,b_pm;
    reg mem_pending=0,mem_rsp_valid=0,mem_rsp_err=0,mem_saved_err=0;
    reg pio_pending=0,pio_rsp_valid=0,pio_rsp_err=0,pio_saved_err=0;
    reg [31:0] mem_rsp_rdata=0,mem_saved_data=0,pio_rsp_rdata=0,pio_saved_data=0;
    integer mem_delay=0,pio_delay=0;
    wire wait_source_for_dest_ack=!direction&&(word_count==9)&&(candidate_dut.pd_count==1)&&!pio_rsp_valid;
    wire mem_cmd_ready=(!mem_pending&&(!mem_rsp_valid||a_mrr))&&(cycles%4!=1)&&!wait_source_for_dest_ack;
    wire pio_cmd_ready=(!pio_pending&&(!pio_rsp_valid||a_prr))&&(cycles%6!=2);
    reference_engine reference_dut(.clk(clk),.rst_n(rst_n),.start(start),.direction(direction),.start_address(start_address),.word_count(word_count),
        .busy(a_busy),.done(a_done),.error(a_error),.input_ready(input_ready),.output_ready(output_ready),
        .mem_cmd_valid(a_mv),.mem_cmd_ready(mem_cmd_ready),.mem_cmd_addr(a_ma),.mem_cmd_read(a_mr),.mem_cmd_wdata(a_mw),.mem_cmd_wmask(a_mm),
        .mem_rsp_valid(mem_rsp_valid),.mem_rsp_ready(a_mrr),.mem_rsp_rdata(mem_rsp_rdata),.mem_rsp_err(mem_rsp_err),
        .pio_cmd_valid(a_pv),.pio_cmd_ready(pio_cmd_ready),.pio_cmd_addr(a_pa),.pio_cmd_read(a_pr),.pio_cmd_wdata(a_pw),.pio_cmd_wmask(a_pm),
        .pio_rsp_valid(pio_rsp_valid),.pio_rsp_ready(a_prr),.pio_rsp_rdata(pio_rsp_rdata),.pio_rsp_err(pio_rsp_err));
    kwt_ld_engine candidate_dut(.clk(clk),.rst_n(rst_n),.start(start),.direction(direction),.start_address(start_address),.word_count(word_count),
        .busy(b_busy),.done(b_done),.error(b_error),.input_ready(input_ready),.output_ready(output_ready),
        .mem_cmd_valid(b_mv),.mem_cmd_ready(mem_cmd_ready),.mem_cmd_addr(b_ma),.mem_cmd_read(b_mr),.mem_cmd_wdata(b_mw),.mem_cmd_wmask(b_mm),
        .mem_rsp_valid(mem_rsp_valid),.mem_rsp_ready(b_mrr),.mem_rsp_rdata(mem_rsp_rdata),.mem_rsp_err(mem_rsp_err),
        .pio_cmd_valid(b_pv),.pio_cmd_ready(pio_cmd_ready),.pio_cmd_addr(b_pa),.pio_cmd_read(b_pr),.pio_cmd_wdata(b_pw),.pio_cmd_wmask(b_pm),
        .pio_rsp_valid(pio_rsp_valid),.pio_rsp_ready(b_prr),.pio_rsp_rdata(pio_rsp_rdata),.pio_rsp_err(pio_rsp_err));
    function automatic [31:0] payload(input integer index);
        payload=32'h12340000^(32'h9e3779b9*index);
    endfunction
    always @(negedge clk)if(rst_n)begin
        if({a_busy,a_done,a_error,a_mv,a_mr,a_mrr,a_ma,a_mw,a_mm,a_pv,a_pr,a_prr,a_pa,a_pw,a_pm}!==
           {b_busy,b_done,b_error,b_mv,b_mr,b_mrr,b_ma,b_mw,b_mm,b_pv,b_pr,b_prr,b_pa,b_pw,b_pm})
            $fatal(1,"C_AREA_DMA_OUTPUT_EQUIVALENCE cycle=%0d descriptor=%0d",cycles,descriptors);
    end
    always @(posedge clk)begin
        cycles<=cycles+1;
        if(!rst_n||start)begin
            mem_pending<=0;mem_rsp_valid<=0;mem_rsp_err<=0;
            pio_pending<=0;pio_rsp_valid<=0;pio_rsp_err<=0;
            source_index<=0;dest_count<=0;
        end else begin
            if(candidate_dut.source_fire&&candidate_dut.dest_complete)simultaneous<=simultaneous+1;
            if(candidate_dut.pd_count==2)slot_two<=slot_two+1;
            if(mem_rsp_valid&&a_mrr)mem_rsp_valid<=0;
            if(mem_pending)begin
                if(mem_delay==0)begin mem_pending<=0;mem_rsp_valid<=1;mem_rsp_rdata<=mem_saved_data;mem_rsp_err<=mem_saved_err;end
                else mem_delay<=mem_delay-1;
            end
            if(pio_rsp_valid&&a_prr)pio_rsp_valid<=0;
            if(pio_pending)begin
                if(pio_delay==0)begin pio_pending<=0;pio_rsp_valid<=1;pio_rsp_rdata<=pio_saved_data;pio_rsp_err<=pio_saved_err;end
                else pio_delay<=pio_delay-1;
            end
            if(a_mv&&mem_cmd_ready)begin
                mem_pending<=1;mem_delay<=cycles%3;mem_saved_data<=payload(source_index);
                mem_saved_err<=(!direction&&error_source&&source_index==1)||(direction&&error_destination&&dest_count==1);
                if(a_mr)source_index<=source_index+1;
                else begin
                    if(!error_source&&!error_destination&&a_mw!==payload(dest_count))$fatal(1,"C_AREA_DMA_MEMORY_DATA");
                    dest_count<=dest_count+1;
                end
            end
            if(a_pv&&pio_cmd_ready)begin
                pio_pending<=1;pio_delay<=1+cycles%2;pio_saved_data<=payload(source_index);
                pio_saved_err<=(direction&&error_source&&source_index==1)||(!direction&&error_destination&&dest_count==1);
                if(a_pr)source_index<=source_index+1;
                else begin
                    if(!error_source&&!error_destination&&a_pw!==payload(dest_count))$fatal(1,"C_AREA_DMA_PIO_DATA");
                    dest_count<=dest_count+1;
                end
            end
        end
    end
    task run_descriptor(input integer words,input bit output_direction,input bit source_fault,input bit destination_fault);
        begin
            @(negedge clk);word_count=words;direction=output_direction;error_source=source_fault;error_destination=destination_fault;start=1;
            @(negedge clk);start=0;
            while(!a_done)@(negedge clk);
            if(a_error!=(source_fault||destination_fault))$fatal(1,"C_AREA_DMA_ERROR_STATUS");
            if(!source_fault&&!destination_fault&&dest_count!=words)$fatal(1,"C_AREA_DMA_DESTINATION_COUNT");
            descriptors=descriptors+1;
            $display("C_AREA_DMA_DESCRIPTOR_PASS words=%0d direction=%0d source_error=%0d destination_error=%0d",words,output_direction,source_fault,destination_fault);
            repeat(2)@(negedge clk);
        end
    endtask
    initial begin
        repeat(4)@(negedge clk);rst_n=1;
        for(integer d=0;d<2;d=d+1)begin
            run_descriptor(0,d,0,0);run_descriptor(1,d,0,0);run_descriptor(2,d,0,0);run_descriptor(9,d,0,0);
            run_descriptor(6,d,1,0);run_descriptor(6,d,0,1);
        end
        $display("C_AREA_DMA_EVENT_COUNTS descriptors=%0d simultaneous=%0d slot_two=%0d",descriptors,simultaneous,slot_two);
        if(descriptors!=12||simultaneous==0||slot_two==0)$fatal(1,"C_AREA_DMA_EVENT_COVERAGE");
        $display("C_AREA_DMA_EQUIVALENCE_ALL_PASS descriptors=%0d simultaneous=%0d slot_two=%0d",descriptors,simultaneous,slot_two);$finish;
    end
endmodule
