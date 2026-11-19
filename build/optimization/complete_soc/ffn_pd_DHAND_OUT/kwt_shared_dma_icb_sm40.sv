module kwt_shared_icb_sm40(
    input wire clk,rst_n,
    input wire cpu_cmd_valid,
    output wire cpu_cmd_ready,
    input wire [31:0] cpu_cmd_addr,
    input wire cpu_cmd_read,
    input wire [31:0] cpu_cmd_wdata,
    input wire [3:0] cpu_cmd_wmask,
    output wire cpu_rsp_valid,
    input wire cpu_rsp_ready,
    output wire [31:0] cpu_rsp_rdata,
    output wire cpu_rsp_err,
    input wire host_cmd_valid,
    output wire host_cmd_ready,
    input wire host_cmd_read,
    input wire [16:0] host_cmd_addr,
    input wire [31:0] host_cmd_wdata,
    input wire [3:0] host_cmd_wmask,
    output reg host_rsp_valid,
    input wire host_rsp_ready,
    output reg [31:0] host_rsp_rdata
,
    input wire ld_cmd_valid,
    output wire ld_cmd_ready,
    input wire [31:0] ld_cmd_addr,
    input wire ld_cmd_read,
    input wire [31:0] ld_cmd_wdata,
    input wire [3:0] ld_cmd_wmask,
    output wire ld_rsp_valid,
    input wire ld_rsp_ready,
    output wire [31:0] ld_rsp_rdata,
    output wire ld_rsp_err
);
wire joined_cmd_valid;
wire joined_cmd_ready;
wire [31:0] joined_cmd_addr;
wire joined_cmd_read;
wire [31:0] joined_cmd_wdata;
wire [3:0] joined_cmd_wmask;
reg joined_rsp_valid;
wire joined_rsp_ready;
reg [31:0] joined_rsp_rdata;
reg joined_rsp_err;
kwt_ld_icb_arbiter #(.HANDOFF(1)) memory_arbiter(
.clk(clk),.rst_n(rst_n),
        .a_cmd_valid(cpu_cmd_valid),
        .a_cmd_ready(cpu_cmd_ready),
        .a_cmd_addr(cpu_cmd_addr),
        .a_cmd_read(cpu_cmd_read),
        .a_cmd_wdata(cpu_cmd_wdata),
        .a_cmd_wmask(cpu_cmd_wmask),
        .a_rsp_valid(cpu_rsp_valid),
        .a_rsp_ready(cpu_rsp_ready),
        .a_rsp_rdata(cpu_rsp_rdata),
        .a_rsp_err(cpu_rsp_err),
        .b_cmd_valid(ld_cmd_valid),
        .b_cmd_ready(ld_cmd_ready),
        .b_cmd_addr(ld_cmd_addr),
        .b_cmd_read(ld_cmd_read),
        .b_cmd_wdata(ld_cmd_wdata),
        .b_cmd_wmask(ld_cmd_wmask),
        .b_rsp_valid(ld_rsp_valid),
        .b_rsp_ready(ld_rsp_ready),
        .b_rsp_rdata(ld_rsp_rdata),
        .b_rsp_err(ld_rsp_err),
        .s_cmd_valid(joined_cmd_valid),
        .s_cmd_ready(joined_cmd_ready),
        .s_cmd_addr(joined_cmd_addr),
        .s_cmd_read(joined_cmd_read),
        .s_cmd_wdata(joined_cmd_wdata),
        .s_cmd_wmask(joined_cmd_wmask),
        .s_rsp_valid(joined_rsp_valid),
        .s_rsp_ready(joined_rsp_ready),
        .s_rsp_rdata(joined_rsp_rdata),
        .s_rsp_err(joined_rsp_err));

    reg pending,read_pending,error_pending,to_host;
    wire idle=!pending&&(!joined_rsp_valid||joined_rsp_ready)&&(!host_rsp_valid||host_rsp_ready);
    assign host_cmd_ready=idle;
    assign joined_cmd_ready=idle&&!host_cmd_valid;
    wire joined_fire=joined_cmd_valid&&joined_cmd_ready;
    wire host_fire=host_cmd_valid&&host_cmd_ready;
    wire joined_address_valid=joined_cmd_addr[31:19]==13'h1400;
    wire [31:0] memory_rdata;
    kwt_shared_sram_sm40 memory(
        .clk(clk),.en(host_fire||(joined_fire&&joined_address_valid)),
        .we(host_fire?!host_cmd_read:!joined_cmd_read),
        .addr(host_fire?host_cmd_addr:joined_cmd_addr[18:2]),
        .wdata(host_fire?host_cmd_wdata:joined_cmd_wdata),
        .wmask(host_fire?host_cmd_wmask:joined_cmd_wmask),.rdata(memory_rdata)
    );
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            pending<=0;read_pending<=0;error_pending<=0;
            joined_rsp_valid<=0;joined_rsp_rdata<=0;joined_rsp_err<=0;
            host_rsp_valid<=0;host_rsp_rdata<=0;to_host<=0;
        end else begin
            if(joined_rsp_valid&&joined_rsp_ready) joined_rsp_valid<=0;
            if(host_rsp_valid&&host_rsp_ready) host_rsp_valid<=0;
            if(joined_fire) begin
                pending<=1;read_pending<=joined_cmd_read;error_pending<=!joined_address_valid;to_host<=0;
            end
            if(host_fire&&host_cmd_read) begin
                pending<=1;read_pending<=1;error_pending<=0;to_host<=1;
            end
            if(pending) begin
                pending<=0;
                if(to_host) begin host_rsp_valid<=1;host_rsp_rdata<=memory_rdata;end
                else begin
                    joined_rsp_valid<=1;joined_rsp_err<=error_pending;
                    joined_rsp_rdata<=(read_pending&&!error_pending)?memory_rdata:32'b0;
                end
            end
        end
    end
endmodule
