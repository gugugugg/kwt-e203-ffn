`timescale 1ns/1ps
module row_reuse_tb;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,icb_cmd_valid=0,icb_cmd_read=0,icb_rsp_ready=0;
    reg [7:0] icb_cmd_addr=0;
    reg [31:0] icb_cmd_wdata=0;
    reg [3:0] icb_cmd_wmask=15;
    wire icb_cmd_ready,icb_rsp_valid,icb_rsp_err,trace_valid;
    wire [31:0] icb_rsp_rdata;
    wire [3:0] trace_layer,trace_stage;
    wire [14:0] trace_index;
    wire signed [63:0] trace_data;
    reg [15:0] inputs[0:6335],parameters[0:17407],shifts[0:127],expected[0:25343];
    reg active=0,mixed_access=0,single_access=0;
    integer layer,index,address,trace_count=0;
    reg [31:0] value,ignored;
    string filename,vector_dir;
    kwt_icb_encoder dut(.*);
    always @(posedge clk) if(active&&trace_valid) begin
        if(trace_layer!=0||trace_stage!=9||trace_index!=trace_count||
           trace_data!=={{48{expected[trace_count][15]}},expected[trace_count]})
            $fatal(1,"NEXT_TRACE_ORDER_OR_VALUE layer=%0d index=%0d expected_index=%0d",layer,trace_index,trace_count);
        trace_count=trace_count+1;
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
        reg [15:0] low,high;
        begin
            write_word(8,kind);write_word(12,0);address=0;
            while(address<count) begin
                case(kind)
                    0:begin low=inputs[address];high=(address+1<count)?inputs[address+1]:0;end
                    1:begin low=parameters[address];high=(address+1<count)?parameters[address+1]:0;end
                    default:begin low=shifts[address];high=(address+1<count)?shifts[address+1]:0;end
                endcase
                if(mixed_access&&(address%17==0||address+1==count)) begin
                    write_word(16,{16'd0,low});address=address+1;
                end else begin
                    write_word(48,{high,low});address=address+2;
                end
            end
        end
    endtask
    initial begin
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
            write_word(44,1);load_words(0,6336);write_word(0,1);
            read_word(36,value);if(!(value&16)) $fatal(1,"NEXT_MISSING_LAYER_REQUEST");
            load_words(1,17408);load_words(5,128);read_word(4,value);
            if(!(value&32)) $fatal(1,"NEXT_PARAMETERS_NOT_READY");
            active=1;write_word(24,1);
            if(mixed_access&&layer==0) repeat(4096) @(negedge clk);
            index=0;
            while(index<25344) begin
                read_word(36,value);if(!(value&2)) $fatal(1,"NEXT_OUTPUT_NOT_READY");
                read_word(28,value);if(value!=index) $fatal(1,"NEXT_OUTPUT_ORDER");
                if(single_access||(mixed_access&&index%17==0)||index+1==25344) begin
                    read_word(32,value);if(value[15:0]!==expected[index]) $fatal(1,"NEXT_SCALAR_VALUE");
                    index=index+1;
                end else begin
                    read_word(52,value);
                    if(value!=={expected[index+1],expected[index]}) $fatal(1,"NEXT_PAIR_VALUE");
                    index=index+2;
                end
            end
            read_word(4,value);while(!(value&64)) read_word(4,value);
            if(trace_count!=25344) $fatal(1,"NEXT_TRACE_COUNT");
            active=0;$display("FFN_NEXT_RTL_PASS layer=%0d outputs=25344 trace=%0d",layer,trace_count);
        end
        $display("FFN_NEXT_RTL_ALL_PASS");$finish;
    end
endmodule
