wire kwt_cmd_valid,kwt_cmd_ready,kwt_cmd_read;
wire [31:0] kwt_cmd_addr,kwt_cmd_wdata,kwt_rsp_rdata;
wire [3:0] kwt_cmd_wmask;
wire kwt_rsp_valid,kwt_rsp_ready,kwt_rsp_err;
kwt_icb_ffn_channel accelerator (
    .clk(clk),.rst_n(bus_rst_n),
    .icb_cmd_valid(kwt_cmd_valid),.icb_cmd_ready(kwt_cmd_ready),
    .icb_cmd_addr(kwt_cmd_addr[7:0]),.icb_cmd_read(kwt_cmd_read),
    .icb_cmd_wdata(kwt_cmd_wdata),.icb_cmd_wmask(kwt_cmd_wmask),
    .icb_rsp_valid(kwt_rsp_valid),.icb_rsp_ready(kwt_rsp_ready),
    .icb_rsp_rdata(kwt_rsp_rdata),.icb_rsp_err(kwt_rsp_err)
);
