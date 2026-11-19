// One signed 16x16 product per accepted input cycle, exactly 64 inputs/task.
// Multiplier register and 64-bit accumulator are separate pipeline stages.
module kwt_dot64 (
    input  wire clk, rst_n,
    input  wire start_valid,
    output wire start_ready,
    input  wire signed [63:0] bias,
    input  wire signed [7:0] shift,
    input  wire in_valid,
    output wire in_ready,
    input  wire signed [15:0] a, b,
    output wire out_valid,
    input  wire out_ready,
    output reg signed [15:0] out_data,
    output reg out_error
);
    localparam [1:0] IDLE=0, RUN=1, QUANT=2, OUTPUT=3;
    reg [1:0] state;
    reg [6:0] input_count, product_count;
    reg product_valid;
    reg signed [31:0] product;
    reg signed [63:0] accumulator;
    reg signed [7:0] shift_q;
    wire signed [63:0] product_extended = {{32{product[31]}}, product};
    wire signed [63:0] sum = accumulator + product_extended;
    wire signed [15:0] quantized;
    // Isolate the large rescale/saturation network while the MAC is running.
    wire signed [63:0] quant_input = (state == QUANT) ? accumulator : 64'sd0;
    kwt_requantize quant(.value(quant_input), .shift(shift_q), .result(quantized));
    assign start_ready = state == IDLE;
    assign in_ready = (state == RUN) && (input_count < 64);
    assign out_valid = state == OUTPUT;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= IDLE; input_count <= 0; product_count <= 0;
            product_valid <= 0; product <= 0; accumulator <= 0;
            shift_q <= 0; out_data <= 0; out_error <= 0;
        end else begin
            product_valid <= in_valid && in_ready;
            if (in_valid && in_ready) begin
                product <= a * b;
                input_count <= input_count + 1'b1;
            end
            if (product_valid) begin
                accumulator <= sum;
                product_count <= product_count + 1'b1;
                if ((accumulator[63] == product_extended[63]) && (sum[63] != accumulator[63]))
                    out_error <= 1'b1;
                if (product_count == 63) state <= QUANT;
            end
            case (state)
                IDLE: if (start_valid) begin
                    accumulator <= bias; shift_q <= shift;
                    input_count <= 0; product_count <= 0; product_valid <= 0;
                    out_error <= (shift < -30) || (shift > 62);
                    state <= RUN;
                end
                RUN: begin end
                QUANT: begin out_data <= quantized; state <= OUTPUT; end
                OUTPUT: if (out_ready) state <= IDLE;
                default: state <= IDLE;
            endcase
        end
    end
endmodule
