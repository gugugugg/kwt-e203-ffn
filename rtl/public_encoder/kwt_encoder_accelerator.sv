module kwt_encoder_accelerator(
    input wire clk,rst_n,
    input wire icb_cmd_valid,
    output wire icb_cmd_ready,
    input wire [7:0] icb_cmd_addr,
    input wire icb_cmd_read,
    input wire [31:0] icb_cmd_wdata,
    input wire [3:0] icb_cmd_wmask,
    output wire icb_rsp_valid,
    input wire icb_rsp_ready,
    output wire [31:0] icb_rsp_rdata,
    output wire icb_rsp_err
);
    wire trace_valid;
    wire [3:0] trace_layer,trace_stage;
    wire [14:0] trace_index;
    wire signed [63:0] trace_data;
    kwt_icb_encoder controller(.*);
endmodule
