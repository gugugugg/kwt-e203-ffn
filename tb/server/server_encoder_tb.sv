`timescale 1ns/1ps
module server_encoder_tb;
    reg clk = 0;
    reg rst_n = 0;
    wire [31:0] inspect_pc;
    wire sim_done, sim_pass;
    wire [3:0] trace_task, trace_layer, trace_stage;
    wire trace_valid;
    wire [14:0] trace_index;
    wire signed [63:0] trace_data;
    reg signed [63:0] expected[0:1603799];
    bit seen[0:1603799];
    integer stage_counts[0:13] = '{6336,6336,6336,9801,9801,6336,6336,6336,6336,25344,25344,6336,6336,6336};
    integer offsets[0:13];
    integer per_layer = 0, task_id = -1, received = 0;
    integer i, position;
    string filename;
    longint unsigned cycles = 0;
    kwt_encoder_cpu_soc dut(.*);
    always #3.333 clk = ~clk;
    initial begin
        for (i = 0; i < 14; i = i + 1) begin
            offsets[i] = per_layer;
            per_layer = per_layer + stage_counts[i];
        end
        repeat (32) @(negedge clk);
        rst_n = 1;
    end
    task finish_trace;
        if (task_id >= 0) begin
            if (received != 1603800) $fatal(1, "Incomplete encoder trace task=%0d count=%0d", task_id, received);
            $display("CPU_ENCODER_TRACE_PASS task=%0d count=%0d", task_id, received);
            $fflush();
        end
    endtask
    always @(negedge clk) begin
        if (rst_n) begin
            cycles = cycles + 1;
            if (trace_valid) begin
                if (task_id != trace_task) begin
                    finish_trace();
                    task_id = trace_task;
                    filename = $sformatf("build/encoder/vectors/task_%02d_trace.hex", task_id);
                    $readmemh(filename, expected);
                    foreach (seen[i]) seen[i] = 0;
                    received = 0;
                end
                position = trace_layer * per_layer + offsets[trace_stage] + trace_index;
                if (seen[position] || trace_data !== expected[position])
                    $fatal(1, "CPU_ENCODER_TRACE_FAIL task=%0d layer=%0d stage=%0d index=%0d got=%0d expected=%0d", task_id, trace_layer, trace_stage, trace_index, trace_data, expected[position]);
                seen[position] = 1;
                received = received + 1;
            end
            if (cycles % 10000000 == 0) begin
                $display("SERVER_ENCODER_PROGRESS cycles=%0d pc=%h task=%0d layer=%0d trace_values=%0d", cycles, inspect_pc, trace_task, trace_layer, received);
                $fflush();
            end
        end
        if (sim_done) begin
            if (!sim_pass) $fatal(1, "Real E203 encoder firmware failed pc=%h", inspect_pc);
            finish_trace();
            $display("SERVER_ENCODER_PASS cycles=%0d", cycles);
            $finish;
        end
    end
endmodule
