`timescale 1ns/1ps
module row_reuse_tb;
    reg clk=0;always #3.333333 clk=~clk;
    reg rst_n=0,icb_cmd_valid=0,icb_cmd_read=0,icb_rsp_ready=0;
    reg [7:0] icb_cmd_addr=0;
    reg [31:0] icb_cmd_wdata=0;
    reg [3:0] icb_cmd_wmask=15;
    wire icb_cmd_ready,icb_rsp_valid,icb_rsp_err,trace_valid;
    wire [31:0] icb_rsp_rdata;
    wire [3:0] trace_layer,trace_stage;
    wire [14:0] trace_index;
    wire signed [63:0] trace_data,trace_high;
    wire trace_pair_valid;
    reg [15:0] inputs[0:6335],parameters[0:17407],shifts[0:127],expected[0:25343];
    reg active=0,mixed_access=0,single_access=0;
    integer layer,index,address,trace_count=0;
    integer row_group=1,block_row,receive_limit;
    reg stream_input=0,double_input=0;
    reg [31:0] value,ignored;
    string filename,vector_dir;

    wire LD_DMA=!mixed_access&&!single_access;
    localparam LD_OUTPUT=1;
    wire ld_cmd_valid,ld_cmd_read,ld_rsp_ready;
    wire [31:0] ld_cmd_addr,ld_cmd_wdata;
    wire [3:0] ld_cmd_wmask;
    reg ld_rsp_valid=0,ld_rsp_err=0,ld_pending=0;
    reg [31:0] ld_rsp_rdata=0;
    reg [31:0] ld_shared[0:131071];
    wire ld_cmd_ready=!ld_pending&&!ld_rsp_valid;
    always @(posedge clk)begin
        if(!rst_n)begin ld_pending<=0;ld_rsp_valid<=0;ld_rsp_err<=0;end
        else begin
            if(ld_rsp_valid&&ld_rsp_ready)ld_rsp_valid<=0;
            if(ld_pending)begin ld_pending<=0;ld_rsp_valid<=1;end
            if(ld_cmd_valid&&ld_cmd_ready)begin
                ld_pending<=1;ld_rsp_err<=0;
                if(ld_cmd_addr<32'ha0000000||ld_cmd_addr>=32'ha0080000||ld_cmd_addr[1:0]!=0)ld_rsp_err<=1;
                else if(ld_cmd_read)ld_rsp_rdata<=ld_shared[(ld_cmd_addr-32'ha0000000)/4];
                else for(integer byte_id=0;byte_id<4;byte_id=byte_id+1)
                    if(ld_cmd_wmask[byte_id])ld_shared[(ld_cmd_addr-32'ha0000000)/4][byte_id*8+:8]<=ld_cmd_wdata[byte_id*8+:8];
            end
        end
    end
    task dma_transfer(input [31:0] location,input integer words,input integer direction);
        begin
            write_word(8'h40,location);write_word(8'h44,words);write_word(8'h48,direction);
            read_word(8'h50,value);if(value&4)$fatal(1,"NATIVE_DMA_TRANSFER_ERROR");
        end
    endtask
    kwt_icb_encoder dut(.*);
    always @(posedge clk) if(active&&trace_valid) begin
        if(trace_layer!=0||trace_stage!=9||trace_index!=trace_count||
           trace_data!=={{48{expected[trace_count][15]}},expected[trace_count]})
            $fatal(1,"NEXT_TRACE_ORDER_OR_VALUE layer=%0d index=%0d expected_index=%0d",layer,trace_index,trace_count);
        trace_count=trace_count+1;
        if(trace_pair_valid)begin
            if(trace_index+1!=trace_count||trace_high!=={{48{expected[trace_count][15]}},expected[trace_count]})
                $fatal(1,"NEXT_TRACE_HIGH_ORDER_OR_VALUE layer=%0d index=%0d",layer,trace_count);
            trace_count=trace_count+1;
        end
    end
    task access(input bit reading,input [7:0] offset,input [31:0] data,output [31:0] result);
        reg [31:0] held;
        integer delay_cycles;
        begin
            @(negedge clk);icb_cmd_valid=1;icb_cmd_read=reading;icb_cmd_addr=offset;icb_cmd_wdata=data;
            @(posedge clk);while(!icb_cmd_ready) @(posedge clk);
            @(negedge clk);icb_cmd_valid=0;
            while(!icb_rsp_valid) @(negedge clk);
            held=icb_rsp_rdata;
            if(icb_rsp_err) $fatal(1,"NEXT_ICB_ERROR address=%h",offset);
            if(mixed_access&&reading&&(offset==32||offset==52))
                for(delay_cycles=0;delay_cycles<4;delay_cycles=delay_cycles+1) begin
                    @(negedge clk);
                    if(!icb_rsp_valid||icb_rsp_rdata!==held||icb_rsp_err)
                        $fatal(1,"NEXT_RESPONSE_CHANGED_WHILE_BLOCKED");
                end
            result=held;icb_rsp_ready=1;
            @(negedge clk);icb_rsp_ready=0;
        end
    endtask
    task write_word(input [7:0] offset,input [31:0] data);
        access(0,offset,data,ignored);
    endtask
    task read_word(input [7:0] offset,output [31:0] result);
        access(1,offset,0,result);
    endtask
    task load_words(input integer kind,input integer count);
        reg [15:0] low,high;reg [31:0] location;
        begin
            write_word(8,kind);write_word(12,0);address=0;
            location=kind==0?32'ha0000000:(kind==1?32'ha0020000:32'ha003a000);
            while(address<count)begin
                case(kind)
                    0:begin low=inputs[address];high=(address+1<count)?inputs[address+1]:0;end
                    1:begin low=parameters[address];high=(address+1<count)?parameters[address+1]:0;end
                    default:begin low=shifts[address];high=(address+1<count)?shifts[address+1]:0;end
                endcase
                if(LD_DMA)begin ld_shared[(location-32'ha0000000)/4+address/2]={high,low};address=address+2;end
                else if(single_access||(mixed_access&&(address%17==0||address+1==count)))begin write_word(16,{16'd0,low});address=address+1;end
                else begin write_word(48,{high,low});address=address+2;end
            end
            if(LD_DMA)dma_transfer(location,count/2,1);
        end
    endtask
    task input_block(input integer first_row,input integer rows);
        integer at,last;
        begin
            at=first_row*64;last=(first_row+rows)*64;
            while(at<last)begin
                if(LD_DMA)begin ld_shared[at/2]={inputs[at+1],inputs[at]};at=at+2;end
                else if(single_access||(mixed_access&&(at%17==0||at+1==last)))begin write_word(16,{16'd0,inputs[at]});at=at+1;end
                else begin write_word(48,{inputs[at+1],inputs[at]});at=at+2;end
            end
            if(LD_DMA)dma_transfer(32'ha0000000+first_row*128,rows*32,1);
        end
    endtask

`ifndef KWT_UNIFIED_GATE
    integer ap_initial_bias_pairs=0,jp_seed_consumes=0,ap_next_bias_requests=0;
    integer ap_first_requests=0,ap_follow_requests=0,ap_reseed_pairs=0,ap_shadow_captures=0;
    integer ap_push_cycles=0,ap_push_words=0,ap_pair_pushes=0;
    always @(posedge clk or negedge dut.core.rst_n)begin
        if(!dut.core.rst_n)begin ap_initial_bias_pairs=0;jp_seed_consumes=0;ap_next_bias_requests=0;
            ap_first_requests=0;ap_follow_requests=0;ap_reseed_pairs=0;ap_shadow_captures=0;
            ap_push_cycles=0;ap_push_words=0;ap_pair_pushes=0; end
        else begin
            if(active)begin
                if(dut.core.bias_capture)ap_initial_bias_pairs=ap_initial_bias_pairs+1;
                if(dut.core.ap_er_seed_wait)jp_seed_consumes=jp_seed_consumes+1;
                if(dut.core.ap_er_request)ap_next_bias_requests=ap_next_bias_requests+1;
                if(dut.core.ap_er_first_request)ap_first_requests=ap_first_requests+1;
                if(dut.core.ap_er_next_request)ap_follow_requests=ap_follow_requests+1;
                if(dut.core.ap_er_reseed)ap_reseed_pairs=ap_reseed_pairs+1;
                if(1'b0)ap_shadow_captures=ap_shadow_captures+1;
                if(dut.core.jp_quant_commit)begin
                    ap_push_cycles=ap_push_cycles+1;
                    ap_push_words=ap_push_words+2;
                    if(1'b1)ap_pair_pushes=ap_pair_pushes+1;
                end
            end
        end
    end
`endif
    initial begin
        if($value$plusargs("ROW_GROUP=%d",row_group)) begin end
        stream_input=$test$plusargs("STREAM");double_input=$test$plusargs("DOUBLE");
        mixed_access=$test$plusargs("MIXED");single_access=$test$plusargs("SINGLE");
        if(!$value$plusargs("VECTOR_DIR=%s",vector_dir)) vector_dir="build/optimization/ffn_adaptive_next/native_vectors";
        repeat(4) @(negedge clk);rst_n=1;
        for(layer=0;layer<12;layer=layer+1) begin
            active=0;trace_count=0;
            filename=$sformatf("%s/linear_%02d_input.hex",vector_dir,layer);$readmemh(filename,inputs);
            filename=$sformatf("%s/linear_%02d_expected.hex",vector_dir,layer);$readmemh(filename,expected);
            filename=$sformatf("%s/layer_%02d_parameters.hex",vector_dir,layer);$readmemh(filename,parameters);
            filename=$sformatf("%s/layer_%02d_shifts.hex",vector_dir,layer);$readmemh(filename,shifts);
            write_word(0,2);read_word(4,value);while(!(value&8)) read_word(4,value);
            write_word(44,stream_input?3:1);if(!stream_input)load_words(0,6336);write_word(0,1);
            read_word(36,value);if(!(value&16)) $fatal(1,"NEXT_MISSING_LAYER_REQUEST");
            load_words(1,17408);load_words(5,128);read_word(4,value);
            if(!(value&32)) $fatal(1,"NEXT_PARAMETERS_NOT_READY");
            if(stream_input)begin write_word(8,0);write_word(12,0);end
            active=1;write_word(24,1);

            index=0;
            if(stream_input&&double_input)input_block(0,row_group);
            for(block_row=0;block_row<(stream_input?99:1);block_row=block_row+(stream_input?row_group:1)) begin
            if(stream_input)begin
                if(!double_input)input_block(block_row,(99-block_row<row_group)?99-block_row:row_group);
                else if(block_row+row_group<99)input_block(block_row+row_group,(99-block_row-row_group<row_group)?99-block_row-row_group:row_group);
            end
            receive_limit=stream_input?(((block_row+row_group<99)?block_row+row_group:99)*256):25344;
            if(mixed_access&&layer==0&&block_row==0)repeat(4096)@(negedge clk);
            if(LD_OUTPUT&&!mixed_access&&!single_access)begin
                dma_transfer(32'ha0010000+index*2,(receive_limit-index)/2,2);
                while(index<receive_limit)begin
                    if(ld_shared[(65536+index*2)/4]!=={expected[index+1],expected[index]})$fatal(1,"NATIVE_DMA_WRITEBACK_VALUE");
                    index=index+2;
                end
            end
            while(index<receive_limit) begin
                read_word(36,value);if(!(value&2)) $fatal(1,"NEXT_OUTPUT_NOT_READY");
                read_word(28,value);if(value!=index) $fatal(1,"NEXT_OUTPUT_ORDER");
                if(single_access||(mixed_access&&index%17==0)||index+1==receive_limit) begin
                    read_word(32,value);if(value[15:0]!==expected[index]) $fatal(1,"NEXT_SCALAR_VALUE");
                    index=index+1;
                end else begin
                    read_word(52,value);
                    if(value!=={expected[index+1],expected[index]}) $fatal(1,"NEXT_PAIR_VALUE");
                    index=index+2;
                end
            end
            end
            read_word(4,value);while(!(value&64)) read_word(4,value);
            if(trace_count!=25344) $fatal(1,"NEXT_TRACE_COUNT");
`ifndef KWT_UNIFIED_GATE
        $display("LOGIC_POWER_COMPUTE_COUNTS case=%0d initial_bias_pairs=%0d seed_consumes=%0d next_bias_requests=%0d first_requests=%0d follow_requests=%0d reseed_pairs=%0d shadow_captures=%0d push_cycles=%0d push_words=%0d pair_pushes=%0d",layer,ap_initial_bias_pairs,jp_seed_consumes,ap_next_bias_requests,ap_first_requests,ap_follow_requests,ap_reseed_pairs,ap_shadow_captures,ap_push_cycles,ap_push_words,ap_pair_pushes);
`endif
                    active=0;$display("FFN_NEXT_RTL_PASS layer=%0d outputs=25344 trace=%0d",layer,trace_count);
        end
        $display("FFN_NEXT_RTL_ALL_PASS");$finish;
    end

`ifndef KWT_UNIFIED_GATE
    generate for(genvar jp_lane=0;jp_lane<16;jp_lane=jp_lane+1)begin: jp_commit_observer
        integer products=0,seeds=0,outputs=0;
        always @(posedge dut.core.clk or negedge dut.core.rst_n)begin
            if(!dut.core.rst_n)begin products=0;seeds=0;outputs=0;end
            else if(active)begin
                if(dut.core.jp_quant_mask[jp_lane])begin
                    if(products!=64||seeds!=1)$fatal(1,"LOGIC_POWER_COMMIT_ORDER lane=%0d products=%0d seeds=%0d",jp_lane,products,seeds);
                    products=0;seeds=0;outputs=outputs+1;
                end
                if(dut.core.jp_seed_mask[jp_lane])seeds=seeds+1;
                if(dut.core.jp_mac_mask[jp_lane])products=products+1;
            end
        end
    end endgenerate
`endif

`ifndef KWT_UNIFIED_GATE
    integer jp_return_tile=0,jp_return_pair=0;
    reg jp_return_valid=0;
    always @(posedge dut.core.clk or negedge dut.core.rst_n)begin
        if(!dut.core.rst_n)jp_return_valid=0;
        else if(active)begin
            if(dut.core.layer_start_valid&&dut.core.layer_start_ready)jp_return_valid=0;
            if(dut.core.ap_er_reseed)begin
                if(!jp_return_valid||jp_return_tile!=dut.core.ap_er_target_tile||jp_return_pair!=dut.core.lane[2:1])
                    $fatal(1,"LOGIC_POWER_BIAS_IDENTITY tile=%0d pair=%0d returned_tile=%0d returned_pair=%0d",dut.core.tile,dut.core.lane[2:1],jp_return_tile,jp_return_pair);
                if(dut.core.jp_last_emit_row)jp_return_valid=0;
            end
            if(dut.core.ap_er_request)begin
                if(jp_return_valid)$fatal(1,"LOGIC_POWER_BIAS_RETURN_OVERWRITTEN");
                jp_return_tile=dut.core.ap_er_target_tile;
                jp_return_pair=dut.core.ap_er_request_pair;
                jp_return_valid=1;
            end
        end
    end
`endif

`ifndef KWT_UNIFIED_GATE

    generate for(genvar lp_bank=0;lp_bank<2;lp_bank=lp_bank+1)begin: lp_return_observer
        reg issued=0;
        always @(posedge dut.core.clk)issued<=dut.core.rst_n&&dut.core.ap_input_rows[lp_bank].read_enable;
        always @(negedge dut.core.clk)if(dut.core.rst_n&&active&&issued)
            if(dut.core.jp_input_return[lp_bank*16+:16]!==dut.core.ap_input_rdata[lp_bank*16+:16])
                $fatal(1,"LOGIC_POWER_IR_RETURN bank=%0d",lp_bank);
    end endgenerate

`endif

 wire [575:0] ref_acc,share_acc;
 wire signed [15:0] ref_low,ref_high,share_low,share_high;
 wire [1:0] slice_read={dut.core.ap_input_rows[1].read_enable,dut.core.ap_input_rows[0].read_enable};
 mac_slice_REF ref_slice(.clk(clk),.rst_n(dut.core.rst_n),.clock_test_enable(dut.core.clock_test_enable),
 .input_rdata(dut.core.ap_input_rdata),.input_read(slice_read),.weight_rdata(dut.core.pm_rdata),.tile_half(dut.core.tile[0]),
 .bias_pair(dut.core.bias_pair),.shift_return(dut.core.jp_shift_return),.seed_mask(dut.core.jp_seed_mask),
 .mac_mask(dut.core.jp_mac_mask),.quant_lane(dut.core.jp_quant_lane),.result_low(ref_low),.result_high(ref_high),.accumulators(ref_acc));
 mac_slice_SHARE4 share_slice(.clk(clk),.rst_n(dut.core.rst_n),.clock_test_enable(dut.core.clock_test_enable),
 .input_rdata(dut.core.ap_input_rdata),.input_read(slice_read),.weight_rdata(dut.core.pm_rdata),.tile_half(dut.core.tile[0]),
 .bias_pair(dut.core.bias_pair),.shift_return(dut.core.jp_shift_return),.seed_mask(dut.core.jp_seed_mask),
 .mac_mask(dut.core.jp_mac_mask),.quant_lane(dut.core.jp_quant_lane),.result_low(share_low),.result_high(share_high),.accumulators(share_acc));
 generate for(genvar sl=0;sl<16;sl=sl+1)begin: slice_check
 always @(negedge clk)if(dut.core.rst_n)begin
  if(ref_acc[sl*36+:36]!==dut.core.accumulator[sl]||share_acc[sl*36+:36]!==dut.core.accumulator[sl])
   $fatal(1,"SLICE_ACC_MISMATCH layer=%0d lane=%0d",layer,sl);
 end end endgenerate
 always @(posedge clk)if(active&&dut.core.jp_quant_commit)begin
  if(ref_low!==dut.core.result_word||ref_high!==dut.core.tp_result_high||share_low!==ref_low||share_high!==ref_high)
   $fatal(1,"SLICE_QUANT_MISMATCH layer=%0d",layer);
 end

endmodule
