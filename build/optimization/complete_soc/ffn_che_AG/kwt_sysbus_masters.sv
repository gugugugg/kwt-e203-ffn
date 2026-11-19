module kwt_sysbus_masters (
    input wire clk, rst_n,
    input wire cpu_cmd_valid, cpu_cmd_read, cpu_rsp_ready,
    input wire [31:0] cpu_cmd_addr, cpu_cmd_wdata,
    input wire [3:0] cpu_cmd_wmask,
    output wire cpu_cmd_ready, cpu_rsp_valid, cpu_rsp_err,
    output wire [31:0] cpu_rsp_rdata,
    input wire ld_cmd_valid, ld_cmd_read, ld_rsp_ready,
    input wire [31:0] ld_cmd_addr, ld_cmd_wdata,
    input wire [3:0] ld_cmd_wmask,
    output wire ld_cmd_ready, ld_rsp_valid, ld_rsp_err,
    output wire [31:0] ld_rsp_rdata,
    input wire host_cmd_valid, host_cmd_read, host_rsp_ready,
    input wire [16:0] host_cmd_addr,
    input wire [31:0] host_cmd_wdata,
    input wire [3:0] host_cmd_wmask,
    output wire host_cmd_ready, host_rsp_valid, host_rsp_err,
    output wire [31:0] host_rsp_rdata,
    output wire mem_cmd_valid, mem_cmd_read, mem_rsp_ready,
    output wire [31:0] mem_cmd_addr, mem_cmd_wdata,
    output wire [3:0] mem_cmd_wmask,
    input wire mem_cmd_ready, mem_rsp_valid, mem_rsp_err,
    input wire [31:0] mem_rsp_rdata,
    input wire sram_cmd_valid, sram_cmd_ready, sram_cmd_read,
    input wire [31:0] sram_cmd_addr, sram_cmd_wdata,
    input wire [3:0] sram_cmd_wmask,
    output reg [11:0] input_committed,
    output reg [13:0] parameter_committed
);
    // A single 32-bit stream feeds the existing platform decoder.
    sirv_gnrl_icb_arbt #(
        .AW(32),.DW(32),.USR_W(1),.ARBT_NUM(3),.ARBT_PTR_W(2),.ARBT_SCHEME(0),
        .FIFO_OUTS_NUM(4),.FIFO_CUT_READY(0),.ALLOW_0CYCL_RSP(0)
    ) arbiter(
        .clk(clk),.rst_n(rst_n),
        .i_bus_icb_cmd_valid({host_cmd_valid,ld_cmd_valid,cpu_cmd_valid}),
        .i_bus_icb_cmd_ready({host_cmd_ready,ld_cmd_ready,cpu_cmd_ready}),
        .i_bus_icb_cmd_addr({13'h1400,host_cmd_addr,2'b00,ld_cmd_addr,cpu_cmd_addr}),
        .i_bus_icb_cmd_read({host_cmd_read,ld_cmd_read,cpu_cmd_read}),
        .i_bus_icb_cmd_wdata({host_cmd_wdata,ld_cmd_wdata,cpu_cmd_wdata}),
        .i_bus_icb_cmd_wmask({host_cmd_wmask,ld_cmd_wmask,cpu_cmd_wmask}),
        .i_bus_icb_cmd_burst(6'b0),.i_bus_icb_cmd_beat(6'b0),.i_bus_icb_cmd_lock(3'b0),
        .i_bus_icb_cmd_excl(3'b0),.i_bus_icb_cmd_size(6'b0),.i_bus_icb_cmd_usr(3'b0),
        .i_bus_icb_rsp_valid({host_rsp_valid,ld_rsp_valid,cpu_rsp_valid}),
        .i_bus_icb_rsp_ready({host_rsp_ready,ld_rsp_ready,cpu_rsp_ready}),
        .i_bus_icb_rsp_err({host_rsp_err,ld_rsp_err,cpu_rsp_err}),
        .i_bus_icb_rsp_rdata({host_rsp_rdata,ld_rsp_rdata,cpu_rsp_rdata}),
        .i_bus_icb_rsp_excl_ok(),.i_bus_icb_rsp_usr(),
        .o_icb_cmd_valid(mem_cmd_valid),.o_icb_cmd_ready(mem_cmd_ready),
        .o_icb_cmd_addr(mem_cmd_addr),.o_icb_cmd_read(mem_cmd_read),
        .o_icb_cmd_wdata(mem_cmd_wdata),.o_icb_cmd_wmask(mem_cmd_wmask),
        .o_icb_cmd_burst(),.o_icb_cmd_beat(),.o_icb_cmd_lock(),
        .o_icb_cmd_excl(),.o_icb_cmd_size(),.o_icb_cmd_usr(),
        .o_icb_rsp_valid(mem_rsp_valid),.o_icb_rsp_ready(mem_rsp_ready),
        .o_icb_rsp_err(mem_rsp_err),.o_icb_rsp_rdata(mem_rsp_rdata),
        .o_icb_rsp_excl_ok(1'b0),.o_icb_rsp_usr(1'b0)
    );

    // Update prefixes at physical writes, downstream of the bus command buffer.
    wire [16:0] commit_word=sram_cmd_addr[18:2];
    wire full_write=sram_cmd_valid&&sram_cmd_ready&&!sram_cmd_read&&
        sram_cmd_addr[31:19]==13'h1400&&sram_cmd_wmask==4'hf;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            input_committed<=0;
            parameter_committed<=0;
        end else if (full_write) begin
            if (commit_word==0) begin
                input_committed<=1;
                parameter_committed<=0;
            end else if (input_committed<3168&&commit_word==17'(input_committed))
                input_committed<=input_committed+12'd1;
            else if (parameter_committed<8512&&commit_word==17'd32768+17'(parameter_committed))
                parameter_committed<=parameter_committed+14'd1;
        end
    end
endmodule
