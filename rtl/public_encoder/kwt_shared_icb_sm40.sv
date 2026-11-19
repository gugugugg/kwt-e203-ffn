module kwt_shared_icb_sm40(
    input wire clk,rst_n,
    input wire cpu_cmd_valid,
    output wire cpu_cmd_ready,
    input wire [31:0] cpu_cmd_addr,
    input wire cpu_cmd_read,
    input wire [31:0] cpu_cmd_wdata,
    input wire [3:0] cpu_cmd_wmask,
    output reg cpu_rsp_valid,
    input wire cpu_rsp_ready,
    output reg [31:0] cpu_rsp_rdata,
    output reg cpu_rsp_err,
    input wire host_cmd_valid,
    output wire host_cmd_ready,
    input wire host_cmd_read,
    input wire [16:0] host_cmd_addr,
    input wire [31:0] host_cmd_wdata,
    input wire [3:0] host_cmd_wmask,
    output reg host_rsp_valid,
    input wire host_rsp_ready,
    output reg [31:0] host_rsp_rdata
);
    reg pending,read_pending,error_pending,to_host;
    wire idle=!pending&&!cpu_rsp_valid&&!host_rsp_valid;
    assign host_cmd_ready=idle;
    assign cpu_cmd_ready=idle&&!host_cmd_valid;
    wire cpu_fire=cpu_cmd_valid&&cpu_cmd_ready;
    wire host_fire=host_cmd_valid&&host_cmd_ready;
    wire cpu_address_valid=cpu_cmd_addr[31:19]==13'h1400;
    wire [31:0] memory_rdata;
    kwt_shared_sram_sm40 memory(
        .clk(clk),.en(host_fire||(cpu_fire&&cpu_address_valid)),
        .we(host_fire?!host_cmd_read:!cpu_cmd_read),
        .addr(host_fire?host_cmd_addr:cpu_cmd_addr[18:2]),
        .wdata(host_fire?host_cmd_wdata:cpu_cmd_wdata),
        .wmask(host_fire?host_cmd_wmask:cpu_cmd_wmask),.rdata(memory_rdata)
    );
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            pending<=0;read_pending<=0;error_pending<=0;
            cpu_rsp_valid<=0;cpu_rsp_rdata<=0;cpu_rsp_err<=0;
            host_rsp_valid<=0;host_rsp_rdata<=0;to_host<=0;
        end else begin
            if(cpu_rsp_valid&&cpu_rsp_ready) cpu_rsp_valid<=0;
            if(host_rsp_valid&&host_rsp_ready) host_rsp_valid<=0;
            if(cpu_fire) begin
                pending<=1;read_pending<=cpu_cmd_read;error_pending<=!cpu_address_valid;to_host<=0;
            end
            if(host_fire&&host_cmd_read) begin
                pending<=1;read_pending<=1;error_pending<=0;to_host<=1;
            end
            if(pending) begin
                pending<=0;
                if(to_host) begin host_rsp_valid<=1;host_rsp_rdata<=memory_rdata;end
                else begin
                    cpu_rsp_valid<=1;cpu_rsp_err<=error_pending;
                    cpu_rsp_rdata<=(read_pending&&!error_pending)?memory_rdata:32'b0;
                end
            end
        end
    end
endmodule
