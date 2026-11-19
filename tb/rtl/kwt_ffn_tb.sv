`timescale 1ns/1ps
`include "counts.svh"
module kwt_ffn_tb;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0,load_valid=0,start_valid=0,out_ready=0;
    reg [1:0] load_kind=0;
    reg [14:0] load_addr=0;
    reg [15:0] load_data=0;
    reg signed [7:0] shift=16;
    wire load_ready,start_ready,busy,done,error,out_valid;
    wire [14:0] out_index;
    wire signed [15:0] out_data;
    reg [15:0] inputs[0:6335],kernel[0:16383],bias[0:1023],expected[0:25343];
    reg stalled=0;
    reg [14:0] stalled_index;
    reg [15:0] stalled_data;
    integer task_index,address,received,cycles,total_outputs=0;
    string filename;
    kwt_ffn dut(.*);
`ifdef DEBUG_TICK
    initial forever begin #100000; $display("DEBUG time=%0t state=%0d row=%0d tile=%0d",$time,dut.state,dut.row,dut.tile); $fflush(); end
`endif
    task load_word(input [1:0] kind, input integer addr, input [15:0] data);
        begin
            @(negedge clk); load_valid=1; load_kind=kind; load_addr=15'(addr); load_data=data;
            if(!load_ready) $fatal(1,"Loader unexpectedly stalled while idle");
            @(posedge clk);
        end
    endtask
    initial begin
        repeat(3) @(negedge clk); rst_n=1;
        // An unsupported start shift returns an error without starting computation.
        @(negedge clk); shift=63; start_valid=1;
        @(negedge clk); start_valid=0;
        if(busy || !done || !error) $fatal(1,"Invalid-shift command was not rejected");
        shift=16;
        for(task_index=0;task_index<`FFN_CASES;task_index=task_index+1) begin
            filename=$sformatf("build/rtl/vectors/task_%02d_input.hex",task_index); $readmemh(filename,inputs);
            filename=$sformatf("build/rtl/vectors/task_%02d_kernel.hex",task_index); $readmemh(filename,kernel);
            filename=$sformatf("build/rtl/vectors/task_%02d_bias.hex",task_index); $readmemh(filename,bias);
            filename=$sformatf("build/rtl/vectors/task_%02d_expected.hex",task_index); $readmemh(filename,expected);
            // Full input/weight/bias reload between tasks, including task after reset.
            for(address=0;address<6336;address=address+1) load_word(0,address,inputs[address]);
            for(address=0;address<16384;address=address+1) load_word(1,address,kernel[address]);
            for(address=0;address<1024;address=address+1) load_word(2,address,bias[address]);
            @(negedge clk); load_valid=0; start_valid=1;
            @(negedge clk); start_valid=0;
            if(task_index==0) begin
                repeat(30) @(negedge clk);
                rst_n=0;
                repeat(2) @(negedge clk); rst_n=1;
                if(busy || out_valid) $fatal(1,"FFN reset did not abort");
                // Explicit cold reload after abort, not a cache-hit restart.
                for(address=0;address<6336;address=address+1) load_word(0,address,inputs[address]);
                for(address=0;address<16384;address=address+1) load_word(1,address,kernel[address]);
                for(address=0;address<1024;address=address+1) load_word(2,address,bias[address]);
                @(negedge clk); load_valid=0; start_valid=1;
                @(negedge clk); start_valid=0;
            end
            received=0; cycles=0; stalled=0;
            while(received<25344 && cycles<500000) begin
                out_ready=(cycles%13>=4);
                @(posedge clk);
                if(stalled && (!out_valid || out_index!==stalled_index || out_data!==stalled_data))
                    $fatal(1,"FFN output changed while stalled");
                stalled=out_valid && !out_ready; stalled_index=out_index; stalled_data=out_data;
                if(load_ready) $fatal(1,"Load port accepted data while busy");
                if(out_valid && out_ready) begin
                    if(out_index!==15'(received) || out_data!==expected[received])
                        $fatal(1,"FFN mismatch task=%0d index=%0d got=%h expected=%h addr=%0d",task_index,received,out_data,expected[received],out_index);
                    received=received+1;
                end
                cycles=cycles+1;
                @(negedge clk);
            end
            out_ready=0;
            if(received!=25344 || busy || !done || error) $fatal(1,"FFN completion/error failed task=%0d",task_index);
            total_outputs=total_outputs+received;
            $display("PASS FFN task=%0d outputs=%0d compute_stream_cycles=%0d",task_index,received,cycles);
            $fflush();
        end
        $display("PASS FFN: %0d complete tasks, %0d output words bit exact",`FFN_CASES,total_outputs);
        $finish;
    end
    initial begin #100000000; $fatal(1,"FFN timeout"); end
endmodule
