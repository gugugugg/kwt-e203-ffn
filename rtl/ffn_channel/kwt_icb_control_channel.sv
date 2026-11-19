// One outstanding 32-bit ICB slave. Local offsets only: no assumed SoC base.
// CTRL=00 SHIFT=04 KIND=08 ADDR=0c DATA=10 OUT_INDEX=14 OUT_DATA=18 STATE=1c.
module kwt_icb_control_channel (
    input wire clk,rst_n,
    input wire icb_cmd_valid,
    output wire icb_cmd_ready,
    input wire [7:0] icb_cmd_addr,
    input wire icb_cmd_read,
    input wire [31:0] icb_cmd_wdata,
    input wire [3:0] icb_cmd_wmask,
    output reg icb_rsp_valid,
    input wire icb_rsp_ready,
    output reg [31:0] icb_rsp_rdata,
    output reg icb_rsp_err,
    output wire load_valid,
    input wire load_ready,
    output reg [1:0] load_kind,
    output reg [14:0] load_addr,
    output wire [15:0] load_data,
    output wire start_valid,
    input wire start_ready,
    output reg signed [7:0] shift,
    input wire busy,done,error,
    input wire out_valid,
    output wire out_ready,
    input wire [14:0] out_index,
    input wire signed [15:0] out_data
);
    reg done_sticky;
    wire slot_available = !icb_rsp_valid || icb_rsp_ready;
    wire full_write = icb_cmd_wmask == 4'hf;
    wire aligned = icb_cmd_addr[1:0] == 0;
    wire load_access = !icb_cmd_read && (icb_cmd_addr == 8'h10) && aligned && full_write;
    wire output_access = icb_cmd_read && (icb_cmd_addr == 8'h18) && aligned;
    // A held request cannot load twice; side effects occur only on command fire.
    // Reject a busy DATA write instead of stalling the CPU forever while it
    // needs to drain output. Empty OUT_DATA reads may wait for computation.
    assign icb_cmd_ready = slot_available && (!output_access || out_valid);
    wire fire = icb_cmd_valid && icb_cmd_ready;
    assign load_valid = fire && load_access && load_ready;
    assign load_data = icb_cmd_wdata[15:0];
    assign out_ready = fire && output_access;
    assign start_valid = icb_cmd_valid && slot_available && !icb_cmd_read && full_write && (icb_cmd_addr == 0) &&
                         icb_cmd_wdata[0] && start_ready;
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            icb_rsp_valid<=0; icb_rsp_rdata<=0; icb_rsp_err<=0;
            load_kind<=0; load_addr<=0; shift<=16; done_sticky<=0;
        end else begin
            if(done) done_sticky<=1;
            if(start_valid) done_sticky<=0;
            if(icb_rsp_valid && icb_rsp_ready) icb_rsp_valid<=0;
            if(fire) begin
                icb_rsp_valid<=1; icb_rsp_rdata<=0; icb_rsp_err<=0;
                if(!aligned || (!icb_cmd_read && !full_write)) icb_rsp_err<=1;
                else if(icb_cmd_read) begin
                    case(icb_cmd_addr)
                        8'h00: icb_rsp_rdata<={29'd0,error,done_sticky,busy};
                        8'h04: icb_rsp_rdata<={{24{shift[7]}},shift};
                        8'h08: icb_rsp_rdata<={30'd0,load_kind};
                        8'h0c: icb_rsp_rdata<={17'd0,load_addr};
                        8'h14: icb_rsp_rdata<={17'd0,out_index};
                        8'h18: icb_rsp_rdata<={{16{out_data[15]}},out_data};
                        8'h1c: icb_rsp_rdata<={28'd0,start_ready,load_ready,out_valid,busy};
                        default: icb_rsp_err<=1;
                    endcase
                end else begin
                    case(icb_cmd_addr)
                        8'h00: if(icb_cmd_wdata[0] && !start_ready) icb_rsp_err<=1;
                        8'h04: if(busy) icb_rsp_err<=1; else shift<=icb_cmd_wdata[7:0];
                        8'h08: if(busy || icb_cmd_wdata>3) icb_rsp_err<=1;
                               else load_kind<=icb_cmd_wdata[1:0];
                        8'h0c: if(busy || icb_cmd_wdata>32767) icb_rsp_err<=1;
                               else load_addr<=icb_cmd_wdata[14:0];
                        8'h10: if(!load_ready) icb_rsp_err<=1;
                               else load_addr<=load_addr+1'b1;
                        default: icb_rsp_err<=1;
                    endcase
                end
            end
        end
    end
endmodule
