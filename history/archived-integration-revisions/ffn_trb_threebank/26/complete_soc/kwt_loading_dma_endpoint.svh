wire kwt_cmd_valid,kwt_cmd_ready,kwt_cmd_read;
wire [31:0] kwt_cmd_addr,kwt_cmd_wdata,kwt_rsp_rdata;
wire [3:0] kwt_cmd_wmask;
wire kwt_rsp_valid,kwt_rsp_ready,kwt_rsp_err;
kwt_encoder_accelerator accelerator(
        .ld_cmd_valid(ld_cmd_valid),
        .ld_cmd_ready(ld_cmd_ready),
        .ld_cmd_addr(ld_cmd_addr),
        .ld_cmd_read(ld_cmd_read),
        .ld_cmd_wdata(ld_cmd_wdata),
        .ld_cmd_wmask(ld_cmd_wmask),
        .ld_rsp_valid(ld_rsp_valid),
        .ld_rsp_ready(ld_rsp_ready),
        .ld_rsp_rdata(ld_rsp_rdata),
        .ld_rsp_err(ld_rsp_err),
        .wb_valid(wb_valid),
        .wb_ready(wb_ready),
        .wb_addr(wb_addr),
        .wb_data(wb_data),
        .wb_ack_valid(wb_ack_valid),
        .wb_ack_ready(wb_ack_ready),

    .clk(clk),.rst_n(bus_rst_n),
    .icb_cmd_valid(kwt_cmd_valid),.icb_cmd_ready(kwt_cmd_ready),
    .icb_cmd_addr(kwt_cmd_addr[7:0]),.icb_cmd_read(kwt_cmd_read),
    .icb_cmd_wdata(kwt_cmd_wdata),.icb_cmd_wmask(kwt_cmd_wmask),
    .icb_rsp_valid(kwt_rsp_valid),.icb_rsp_ready(kwt_rsp_ready),
    .icb_rsp_rdata(kwt_rsp_rdata),.icb_rsp_err(kwt_rsp_err)
);
