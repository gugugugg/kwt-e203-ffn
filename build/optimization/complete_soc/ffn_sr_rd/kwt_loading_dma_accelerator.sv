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
,
    output wire ld_cmd_valid,
    input wire ld_cmd_ready,
    output wire [31:0] ld_cmd_addr,
    output wire ld_cmd_read,
    output wire [31:0] ld_cmd_wdata,
    output wire [3:0] ld_cmd_wmask,
    input wire ld_rsp_valid,
    output wire ld_rsp_ready,
    input wire [31:0] ld_rsp_rdata,
    input wire ld_rsp_err
);
    wire trace_valid;
    wire [3:0] trace_layer,trace_stage;
    wire [14:0] trace_index;
    wire signed [63:0] trace_data,trace_high;
    wire trace_pair_valid;
    kwt_icb_encoder controller(.*);
endmodule
