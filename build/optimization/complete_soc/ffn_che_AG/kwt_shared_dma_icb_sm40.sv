module kwt_shared_icb_sm40 (
    input wire clk, rst_n,
    input wire cpu_cmd_valid, cpu_cmd_read,
    input wire [31:0] cpu_cmd_addr, cpu_cmd_wdata,
    input wire [3:0] cpu_cmd_wmask,
    output wire cpu_cmd_ready,
    input wire cpu_rsp_ready,
    output wire cpu_rsp_valid, cpu_rsp_err,
    output wire [31:0] cpu_rsp_rdata
);
    reg read_pending, read_error;
    reg [16:0] held_addr;
    reg [31:0] held_data;
    reg [3:0] held_mask;
    reg held_write;
    wire valid_address = cpu_cmd_addr[31:19] == 13'h1400;
    wire write_rsp = rst_n && !read_pending && cpu_cmd_valid && !cpu_cmd_read;

    assign cpu_cmd_ready = rst_n && !read_pending && (cpu_cmd_read || cpu_rsp_ready);
    assign cpu_rsp_valid = read_pending || write_rsp;
    assign cpu_rsp_err = read_pending ? read_error : write_rsp && !valid_address;

    wire access = cpu_cmd_valid && cpu_cmd_ready && valid_address;
    wire write_access = access && !cpu_cmd_read;
    wire [31:0] memory_rdata;
    assign cpu_rsp_rdata = read_pending && !read_error ? memory_rdata : 32'b0;

    kwt_shared_sram_sm40 memory (
        .clk(clk), .en(access), .we(access ? !cpu_cmd_read : held_write),
        .addr(access ? cpu_cmd_addr[18:2] : held_addr),
        .wdata(write_access ? cpu_cmd_wdata : held_data),
        .wmask(write_access ? cpu_cmd_wmask : held_mask), .rdata(memory_rdata)
    );

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            read_pending <= 0;
            read_error <= 0;
            held_addr <= 0;
            held_data <= 0;
            held_mask <= 0;
            held_write <= 0;
        end else begin
            if (cpu_cmd_valid && cpu_cmd_ready && cpu_cmd_read) begin
                read_pending <= 1;
                read_error <= !valid_address;
            end else if (cpu_rsp_ready) begin
                read_pending <= 0;
            end
            if (access) begin
                held_addr <= cpu_cmd_addr[18:2];
                held_write <= !cpu_cmd_read;
            end
            if (write_access) begin
                held_data <= cpu_cmd_wdata;
                held_mask <= cpu_cmd_wmask;
            end
        end
    end
endmodule
