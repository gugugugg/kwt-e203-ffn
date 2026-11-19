// Undergraduate first FFN linear: [99,64] x [64,256] + bias, 8 output lanes.
// Load words while idle: kind=0 input (6336 words), 1 kernel (16384 words),
// 2 bias (1024 little-endian 16-bit words). No reference answers in hardware.
module kwt_ffn (
    input wire clk, rst_n,
    input wire load_valid,
    output wire load_ready,
    input wire [1:0] load_kind,
    input wire [14:0] load_addr,
    input wire [15:0] load_data,
    input wire start_valid,
    output wire start_ready,
    input wire signed [7:0] shift,
    output wire busy,
    output reg done,
    output reg error,
    output wire out_valid,
    input wire out_ready,
    output wire [14:0] out_index,
    output wire signed [15:0] out_data
);
    localparam [3:0] IDLE=0, BIAS_REQ=1, BIAS_CAPTURE=2, DOT_START=3,
                      DOT_READ=4, DOT_WAIT=5, EMIT=6;
    reg [3:0] state;
    reg [6:0] row;
    reg [4:0] tile;
    reg [2:0] bias_lane, emit_lane;
    reg [5:0] read_k;
    reg memory_valid;
    reg signed [7:0] shift_q;
    reg signed [63:0] lane_bias [0:7];
    reg signed [15:0] output_buffer [0:7];
    wire loading = load_valid && load_ready;
    wire reading = state == DOT_READ;
    wire bias_reading = state == BIAS_REQ;
    wire [15:0] input_data, kernel_data [0:7], bias_data [0:3];
    wire [7:0] mac_ready, mac_start_ready, mac_valid, mac_error;
    wire signed [15:0] mac_data [0:7];
    wire [12:0] input_addr = reading ? (13'(row)*13'd64 + {7'd0,read_k}) : load_addr[12:0];
    wire [10:0] kernel_addr = reading ? {read_k,tile} : load_addr[13:3];
    wire [9:0] bias_addr = bias_reading ? {2'b0,tile,bias_lane} : {2'b0,load_addr[9:2]};
    wire input_write = loading && (load_kind == 0) && (load_addr < 6336);
    wire kernel_write = loading && (load_kind == 1) && (load_addr < 16384);
    wire bias_write = loading && (load_kind == 2) && (load_addr < 1024);
    assign busy = state != IDLE;
    assign start_ready = state == IDLE;
    assign load_ready = (state == IDLE) && !start_valid;
    assign out_valid = state == EMIT;
    assign out_index = 15'(row)*15'd256 + {7'd0,tile,emit_lane};
    assign out_data = output_buffer[emit_lane];
    kwt_spmem16 input_memory(.clk(clk), .en(reading || input_write), .we(input_write),
                             .addr(input_addr), .wdata(load_data), .rdata(input_data));
    generate
        for (genvar lane=0; lane<8; lane=lane+1) begin: lanes
            wire lane_write = kernel_write && (load_addr[2:0] == 3'(lane));
            kwt_spmem16 #(.ADDR_WIDTH(11),.BANKS(2)) weight_memory(
                .clk(clk), .en(reading || lane_write), .we(lane_write),
                .addr(kernel_addr), .wdata(load_data), .rdata(kernel_data[lane]));
            kwt_dot64 mac(.clk(clk), .rst_n(rst_n), .start_valid(state == DOT_START),
                .start_ready(mac_start_ready[lane]), .bias(lane_bias[lane]), .shift(shift_q),
                .in_valid(memory_valid), .in_ready(mac_ready[lane]),
                .a(input_data), .b(kernel_data[lane]), .out_valid(mac_valid[lane]),
                .out_ready(state == DOT_WAIT), .out_data(mac_data[lane]), .out_error(mac_error[lane]));
        end
        for (genvar word_index=0; word_index<4; word_index=word_index+1) begin: bias_words
            wire word_write = bias_write && (load_addr[1:0] == 2'(word_index));
            kwt_spmem16 #(.ADDR_WIDTH(10),.BANKS(1)) bias_memory(
                .clk(clk), .en(bias_reading || word_write), .we(word_write),
                .addr(bias_addr), .wdata(load_data), .rdata(bias_data[word_index]));
        end
    endgenerate
    integer lane_index;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; row <= 0; tile <= 0; bias_lane <= 0; emit_lane <= 0;
            read_k <= 0; memory_valid <= 0; shift_q <= 0; done <= 0; error <= 0;
            for (lane_index=0; lane_index<8; lane_index=lane_index+1) begin
                lane_bias[lane_index] <= 0; output_buffer[lane_index] <= 0;
            end
        end else begin
            done <= 0;
            memory_valid <= reading;
            if (loading && !(input_write || kernel_write || bias_write)) error <= 1;
            case (state)
                IDLE: if (start_valid) begin
                    error <= (shift < -30) || (shift > 62);
                    if ((shift < -30) || (shift > 62)) done <= 1;
                    else begin
                        shift_q <= shift; row <= 0; tile <= 0; bias_lane <= 0; state <= BIAS_REQ;
                    end
                end
                BIAS_REQ: state <= BIAS_CAPTURE;
                BIAS_CAPTURE: begin
                    lane_bias[bias_lane] <= {bias_data[3],bias_data[2],bias_data[1],bias_data[0]};
                    if (bias_lane == 7) state <= DOT_START;
                    else begin bias_lane <= bias_lane+1'b1; state <= BIAS_REQ; end
                end
                DOT_START: begin
                    if (!(&mac_start_ready)) error <= 1;
                    read_k <= 0; state <= DOT_READ;
                end
                DOT_READ: begin
                    if (read_k == 63) state <= DOT_WAIT;
                    else read_k <= read_k + 1'b1;
                end
                DOT_WAIT: if (&mac_valid) begin
                    for (lane_index=0; lane_index<8; lane_index=lane_index+1)
                        output_buffer[lane_index] <= mac_data[lane_index];
                    if (|mac_error) error <= 1;
                    emit_lane <= 0; state <= EMIT;
                end
                EMIT: if (out_ready) begin
                    if (emit_lane != 7) emit_lane <= emit_lane+1'b1;
                    else if ((tile == 31) && (row == 98)) begin state <= IDLE; done <= 1; end
                    else begin
                        if (tile == 31) begin tile <= 0; row <= row+1'b1; end
                        else tile <= tile+1'b1;
                        bias_lane <= 0; state <= BIAS_REQ;
                    end
                end
                default: state <= IDLE;
            endcase
            if (memory_valid && !(&mac_ready)) error <= 1;
        end
    end
endmodule
