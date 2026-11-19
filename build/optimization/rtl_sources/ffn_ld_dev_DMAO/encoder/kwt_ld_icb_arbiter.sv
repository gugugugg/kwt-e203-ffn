module kwt_ld_icb_arbiter #(
    parameter integer AW=32
)(
    input wire clk,rst_n,
    input wire a_cmd_valid,output wire a_cmd_ready,input wire [AW-1:0] a_cmd_addr,
    input wire a_cmd_read,input wire [31:0] a_cmd_wdata,input wire [3:0] a_cmd_wmask,
    output wire a_rsp_valid,input wire a_rsp_ready,output wire [31:0] a_rsp_rdata,output wire a_rsp_err,
    input wire b_cmd_valid,output wire b_cmd_ready,input wire [AW-1:0] b_cmd_addr,
    input wire b_cmd_read,input wire [31:0] b_cmd_wdata,input wire [3:0] b_cmd_wmask,
    output wire b_rsp_valid,input wire b_rsp_ready,output wire [31:0] b_rsp_rdata,output wire b_rsp_err,
    output wire s_cmd_valid,input wire s_cmd_ready,output wire [AW-1:0] s_cmd_addr,
    output wire s_cmd_read,output wire [31:0] s_cmd_wdata,output wire [3:0] s_cmd_wmask,
    input wire s_rsp_valid,output wire s_rsp_ready,input wire [31:0] s_rsp_rdata,input wire s_rsp_err
);
    reg active,owner,prefer_b,held_valid,held_owner;
    wire grant=held_valid?held_owner:(b_cmd_valid&&(!a_cmd_valid||prefer_b));
    assign s_cmd_valid=!active&&(grant?b_cmd_valid:a_cmd_valid);
    assign s_cmd_addr=grant?b_cmd_addr:a_cmd_addr;
    assign s_cmd_read=grant?b_cmd_read:a_cmd_read;
    assign s_cmd_wdata=grant?b_cmd_wdata:a_cmd_wdata;
    assign s_cmd_wmask=grant?b_cmd_wmask:a_cmd_wmask;
    assign a_cmd_ready=!active&&!grant&&s_cmd_ready;
    assign b_cmd_ready=!active&&grant&&s_cmd_ready;
    wire fire=s_cmd_valid&&s_cmd_ready;
    wire recipient=active?owner:grant;
    assign s_rsp_ready=recipient?b_rsp_ready:a_rsp_ready;
    assign a_rsp_valid=s_rsp_valid&&(active||fire)&&!recipient;
    assign b_rsp_valid=s_rsp_valid&&(active||fire)&&recipient;
    assign a_rsp_rdata=s_rsp_rdata;assign b_rsp_rdata=s_rsp_rdata;
    assign a_rsp_err=s_rsp_err;assign b_rsp_err=s_rsp_err;
    always @(posedge clk or negedge rst_n)begin
        if(!rst_n)begin active<=0;owner<=0;prefer_b<=0;held_valid<=0;held_owner<=0;end
        else begin
            if(!active&&s_cmd_valid&&!s_cmd_ready&&!held_valid)begin held_valid<=1;held_owner<=grant;end
            if(fire)begin
                held_valid<=0;owner<=grant;prefer_b<=!grant;
                active<=!(s_rsp_valid&&s_rsp_ready);
            end else if(active&&s_rsp_valid&&s_rsp_ready)active<=0;
        end
    end
endmodule
