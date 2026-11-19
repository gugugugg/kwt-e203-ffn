module kwt_sysbus_commit_ack (
    input wire clk, rst_n,
    input wire cmd_valid, cmd_read,
    input wire [31:0] cmd_addr, cmd_wdata,
    input wire [3:0] cmd_wmask,
    output wire cmd_ready,
    input wire rsp_ready,
    output wire rsp_valid, rsp_err,
    output wire [31:0] rsp_rdata
);
    reg read_pending, read_error;
    reg [16:0] held_addr;
    reg [31:0] held_data;
    reg [3:0] held_mask;
    reg held_write;
    wire valid_address = cmd_addr[31:19] == 13'h1400;
    wire write_rsp = rst_n && !read_pending && cmd_valid && !cmd_read;

    assign cmd_ready = rst_n && !read_pending && (cmd_read || rsp_ready);
    assign rsp_valid = read_pending || write_rsp;
    assign rsp_err = read_pending ? read_error : write_rsp && !valid_address;

    wire access = cmd_valid && cmd_ready && valid_address;
    wire write_access = access && !cmd_read;
    wire [31:0] memory_rdata;
    assign rsp_rdata = read_pending && !read_error ? memory_rdata : 32'b0;

    kwt_shared_sram_sm40 memory (
        .clk(clk), .en(access), .we(access ? !cmd_read : held_write),
        .addr(access ? cmd_addr[18:2] : held_addr),
        .wdata(write_access ? cmd_wdata : held_data),
        .wmask(write_access ? cmd_wmask : held_mask), .rdata(memory_rdata)
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
            if (cmd_valid && cmd_ready && cmd_read) begin
                read_pending <= 1;
                read_error <= !valid_address;
            end else if (rsp_ready) begin
                read_pending <= 0;
            end
            if (access) begin
                held_addr <= cmd_addr[18:2];
                held_write <= !cmd_read;
            end
            if (write_access) begin
                held_data <= cmd_wdata;
                held_mask <= cmd_wmask;
            end
        end
    end
endmodule
