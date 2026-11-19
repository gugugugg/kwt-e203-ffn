module kwt_icb_ffn (
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
    wire load_valid,load_ready,start_valid,start_ready,busy,done,error,out_valid,out_ready;
    wire [1:0] load_kind;
    wire [14:0] load_addr,out_index;
    wire [15:0] load_data;
    wire signed [15:0] out_data;
    wire signed [7:0] shift;
    kwt_icb_control control(.*);
    kwt_ffn engine(.*);
endmodule
