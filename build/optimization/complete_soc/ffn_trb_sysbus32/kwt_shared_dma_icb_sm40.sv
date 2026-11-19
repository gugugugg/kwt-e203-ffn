module kwt_shared_icb_sm40 (
    input wire clk, rst_n,
    input wire cpu_cmd_valid,
    output wire cpu_cmd_ready,
    input wire [31:0] cpu_cmd_addr,
    input wire cpu_cmd_read,
    input wire [31:0] cpu_cmd_wdata,
    input wire [3:0] cpu_cmd_wmask,
    output wire cpu_rsp_valid,
    input wire cpu_rsp_ready,
    output wire [31:0] cpu_rsp_rdata,
    output wire cpu_rsp_err
);
    reg response_valid, response_read, response_error;
    reg [16:0] held_addr;
    reg [31:0] held_data;
    reg [3:0] held_mask;
    reg held_write;
    wire valid_address=cpu_cmd_addr[31:19]==13'h1400;
    wire [31:0] memory_rdata;
    assign cpu_cmd_ready=!response_valid||cpu_rsp_ready;
    wire accept=cpu_cmd_valid&&cpu_cmd_ready;
    wire access=accept&&valid_address;
    wire write_access=access&&!cpu_cmd_read;
    assign cpu_rsp_valid=response_valid;
    assign cpu_rsp_rdata=response_read&&!response_error?memory_rdata:32'b0;
    assign cpu_rsp_err=response_error;

    kwt_shared_sram_sm40 memory(
        .clk(clk),.en(access),.we(access?!cpu_cmd_read:held_write),
        .addr(access?cpu_cmd_addr[18:2]:held_addr),
        .wdata(write_access?cpu_cmd_wdata:held_data),
        .wmask(write_access?cpu_cmd_wmask:held_mask),.rdata(memory_rdata)
    );

    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            response_valid<=0;response_read<=0;response_error<=0;
            held_addr<=0;held_data<=0;held_mask<=0;held_write<=0;
        end else begin
            if(accept) begin
                response_valid<=1;response_read<=cpu_cmd_read;response_error<=!valid_address;
            end else if(cpu_rsp_ready) response_valid<=0;
            if(access) begin held_addr<=cpu_cmd_addr[18:2];held_write<=!cpu_cmd_read;end
            if(write_access) begin held_data<=cpu_cmd_wdata;held_mask<=cpu_cmd_wmask;end
        end
    end
endmodule
