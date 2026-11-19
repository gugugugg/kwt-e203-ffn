// Merge source and result commands before the platform's only DMA input.
module kwt_sysbus_issue (
    input wire clk, rst_n, start,
    input wire source_valid,
    output wire source_ready,
    input wire [31:0] source_addr,
    output wire source_rsp_valid,
    input wire source_rsp_ready,
    input wire result_valid,
    output wire result_ready,
    input wire [16:0] result_addr,
    input wire [31:0] result_data,
    output wire result_ack,
    input wire result_ack_ready,
    input wire output_priority,
    output wire ld_cmd_valid, ld_cmd_read,
    input wire ld_cmd_ready,
    output wire [31:0] ld_cmd_addr, ld_cmd_wdata,
    output wire [3:0] ld_cmd_wmask,
    input wire ld_rsp_valid,
    output wire ld_rsp_ready
);
    reg [3:0] owners;
    reg [1:0] head, tail;
    reg [2:0] used;
    reg held, held_read;
    wire choose_read = held ? held_read : source_valid && (!output_priority || !result_valid);
    wire room = used < 4;
    assign ld_cmd_valid = room && (choose_read ? source_valid : result_valid);
    assign ld_cmd_read = choose_read;
    assign ld_cmd_addr = choose_read ? source_addr : {13'h1400, result_addr, 2'b0};
    assign ld_cmd_wdata = choose_read ? 32'b0 : result_data;
    assign ld_cmd_wmask = choose_read ? 4'b0 : 4'hf;
    assign source_ready = room && choose_read && ld_cmd_ready;
    assign result_ready = room && !choose_read && ld_cmd_ready;
    assign source_rsp_valid = ld_rsp_valid && used != 0 && owners[head];
    assign result_ack = ld_rsp_valid && used != 0 && !owners[head];
    assign ld_rsp_ready = used != 0 && (owners[head] ? source_rsp_ready : result_ack_ready);
    wire enqueue = ld_cmd_valid && ld_cmd_ready;
    wire dequeue = ld_rsp_valid && ld_rsp_ready;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            head <= 0; tail <= 0; used <= 0; held <= 0; held_read <= 0;
        end else if (start) begin
            head <= 0; tail <= 0; used <= 0; held <= 0;
        end else begin
            if (enqueue) begin
                owners[tail] <= choose_read;
                tail <= tail + 2'd1;
                held <= 0;
            end else if (ld_cmd_valid) begin
                held <= 1;
                held_read <= choose_read;
            end
            if (dequeue) head <= head + 2'd1;
            case ({enqueue, dequeue})
                2'b10: used <= used + 3'd1;
                2'b01: used <= used - 3'd1;
                default: ;
            endcase
        end
    end
endmodule
