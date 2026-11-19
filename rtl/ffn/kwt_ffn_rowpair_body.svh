    generate for(genvar stash_bank=0;stash_bank<2;stash_bank=stash_bank+1) begin: row_stash
        wire clearing=(state==CLEAR)&&(clear_index<128);
        wire writing=stash_write&&(stash_column[0]==stash_bank);
        wire reading=stash_read&&(stash_address[0]==stash_bank);
        wire memory_clk;
        kwt_ffn_clock_gate gate(.clk(clk),.enable(clearing||writing||reading),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(memory_clk));
        kwt_encoder_sram16x128 memory(.clk(memory_clk),.en(clearing||writing||reading),
            .we(clearing||writing),.addr(clearing?clear_index[6:0]:(writing?stash_column[7:1]:stash_address[7:1])),
            .wdata(clearing?16'd0:result_word),.rdata(stash_rdata[stash_bank*16+:16]));
    end endgenerate
    wire datapath_enable=bias_capture||(state==B_MAC)||(state==ROW1_MAC)||fifo_push||stash_write;
    wire datapath_clk;
    generate if(CLOCK_GATING) begin: row_datapath_gate
        kwt_ffn_clock_gate gate(.clk(clk),.enable(datapath_enable),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(datapath_clk));
    end else assign datapath_clk=clk;
    endgenerate
    generate for(genvar acc_group=0;acc_group<2;acc_group=acc_group+1) begin: row_accumulators
        wire mac_update=(acc_group==0)?(state==B_MAC):(state==ROW1_MAC);
        wire bias_update=bias_capture&&((acc_group==0)||(row<98));
        wire register_clk;
        if(@FINE_REG@) begin: fine_gate
            kwt_ffn_clock_gate gate(.clk(clk),.enable(bias_update||mac_update),
                .test_enable(clock_test_enable||!rst_n),.gated_clk(register_clk));
        end else assign register_clk=datapath_clk;
        for(genvar acc_lane=0;acc_lane<LANES;acc_lane=acc_lane+1) begin: lane_registers
            always @(posedge register_clk or negedge rst_n) begin
                if(!rst_n) begin accumulator[acc_group*LANES+acc_lane]<=0;shifts[acc_group*LANES+acc_lane]<=0;end
                else begin
                    if(bias_update&&int'(bias_chunk)==acc_lane/2) begin
                        accumulator[acc_group*LANES+acc_lane]<=36'($signed(bias_rdata[@BIAS_OFFSET@+(acc_lane%2)*64+:64]));
                        shifts[acc_group*LANES+acc_lane]<=$signed(shift_rdata[(acc_lane%2)*8+:8]);
                    end
                    if(mac_update) accumulator[acc_group*LANES+acc_lane]<=
                        accumulator[acc_group*LANES+acc_lane]+36'(mac_a*$signed(pm_rdata[acc_lane*16+:16]));
                end
            end
        end
    end endgenerate
    wire fifo_clk;
    generate if(@FINE_REG@) begin: row_fifo_gate
        kwt_ffn_clock_gate gate(.clk(clk),.enable(fifo_push),
            .test_enable(clock_test_enable||!rst_n),.gated_clk(fifo_clk));
    end else assign fifo_clk=datapath_clk;
    endgenerate
    always @(posedge fifo_clk) if(fifo_push) fifo[fifo_write]<=fifo_word;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            state<=CLEAR;clear_index<=0;input_count<=0;parameter_count<=0;shift_count<=0;
            row<=0;tile<=0;inner<=0;lane<=0;chunk<=0;item<=0;stash_pointer<=0;
            done<=0;error<=0;layer_done<=0;fifo_write<=0;fifo_read<=0;fifo_count<=0;
        end else begin
            done<=0;layer_done<=0;
            if(fifo_push) fifo_write<=fifo_write+1'b1;
            if(pop_count!=0) begin
                fifo_read<=fifo_read+@PTR_BITS@'(pop_count);
                if(item+int'(pop_count)==25344) begin
                    done<=1;input_count<=0;parameter_count<=0;shift_count<=0;clear_index<=0;state<=CLEAR;
                end else item<=item+int'(pop_count);
            end
            fifo_count<=fifo_count+@COUNT_BITS@'(fifo_push)-@COUNT_BITS@'(pop_count);
            if(loading) case(load_kind)
                0: if(load_addr==16'(input_count)&&input_count<6336) input_count<=input_count+13'(load_count);else error<=1;
                1: if(load_addr==16'(parameter_count)&&parameter_count<17408) parameter_count<=parameter_count+15'(load_count);else error<=1;
                5: if(load_addr==16'(shift_count)&&shift_count<128) shift_count<=shift_count+1'b1;else error<=1;
            endcase
            case(state)
                CLEAR: if(clear_index==@CLEAR_LAST@) begin clear_index<=0;state<=IDLE;end else clear_index<=clear_index+1'b1;
                IDLE: if(start_valid) begin
                    error<=0;
                    if(input_count!=6336||!linear_mode) begin error<=1;done<=1;end
                    else begin parameter_count<=0;shift_count<=0;state<=WAIT_LAYER;end
                end
                WAIT_LAYER: if(layer_start_valid&&layer_start_ready) begin
                    row<=0;tile<=0;item<=0;lane<=0;inner<=0;state<=MAC_INIT;
                end
                MAC_INIT: begin chunk<=0;state<=BIAS_REQ;end
                BIAS_REQ: state<=BIAS_CAP;
                BIAS_CAP: if(chunk==LANES/2-1) begin inner<=0;state<=A_REQ;end
                          else begin chunk<=chunk+1;state<=BIAS_REQ;end
                A_REQ: if(row_cache_ready) state<=B_MAC;
                B_MAC: if(row<98) state<=ROW1_MAC;
                       else if(inner==63) begin lane<=0;state<=EMIT;end
                       else inner<=inner+1;
                ROW1_MAC: if(inner==63) begin lane<=0;state<=EMIT;end
                          else begin inner<=inner+1;state<=B_MAC;end
                EMIT: if(fifo_push) begin
                    if(lane<LANES-1) lane<=lane+1;
                    else if(row<98) begin lane<=0;state<=EMIT_STASH;end
                    else if(tile<TILES-1) begin tile<=tile+1;state<=MAC_INIT;end
                    else begin layer_done<=1;state<=DRAIN;end
                end
                EMIT_STASH: if(lane<LANES-1) lane<=lane+1;
                            else if(tile<TILES-1) begin tile<=tile+1;state<=MAC_INIT;end
                            else begin stash_pointer<=0;state<=STASH_REQ;end
                STASH_REQ: state<=STASH_OUT;
                STASH_OUT: if(fifo_push) begin
                    if(stash_pointer<255) stash_pointer<=stash_pointer+1'b1;
                    else begin row<=row+2;tile<=0;lane<=0;state<=MAC_INIT;end
                end
                DRAIN: begin end
                default: begin error<=1;done<=1;state<=CLEAR;end
            endcase
        end
    end
endmodule
