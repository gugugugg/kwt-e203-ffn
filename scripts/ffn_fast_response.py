"""Same-cycle ICB response with a holding register when the receiver is blocked."""
import re


def apply(text):
    for name in ['valid','rdata','err']:text=text.replace('icb_rsp_'+name,'stored_rsp_'+name)
    text=text.replace('output reg stored_rsp_valid,','output wire icb_rsp_valid,').replace('output reg [31:0] stored_rsp_rdata,','output wire [31:0] icb_rsp_rdata,').replace('output reg stored_rsp_err,','output wire icb_rsp_err,')
    at=text.index('    reg [2:0] load_kind;')
    declarations='''    reg stored_rsp_valid,stored_rsp_err;
    reg [31:0] stored_rsp_rdata;
    reg [31:0] immediate_data;
    reg immediate_error;
    wire immediate_reply=!stored_rsp_valid&&icb_cmd_valid&&icb_cmd_ready;
    assign icb_rsp_valid=stored_rsp_valid||immediate_reply;
    assign icb_rsp_rdata=stored_rsp_valid?stored_rsp_rdata:immediate_data;
    assign icb_rsp_err=stored_rsp_valid?stored_rsp_err:immediate_error;
    always @* begin
        immediate_data=0;immediate_error=0;
        if(!aligned||(!icb_cmd_read&&icb_cmd_wmask!=4'hf))immediate_error=1;
        else if(icb_cmd_read)case(icb_cmd_addr)
            8'h00:immediate_data={29'b0,(core_error||bus_error),done_sticky,core_busy};
            8'h04,8'h24:immediate_data=status;
            8'h08:immediate_data={29'b0,load_kind};
            8'h0c:immediate_data={16'b0,load_address};
            8'h14:immediate_data={28'b0,core_layer};
            8'h1c:if(core_out_valid)immediate_data={17'b0,core_out_index};else immediate_error=1;
            8'h20:if(core_out_valid)immediate_data={{16{core_out_data[15]}},core_out_data};else immediate_error=1;
            8'h34:if(core_pair_valid)immediate_data={core_out_high,core_out_data};else immediate_error=1;
            8'h28:immediate_data=32'h4b574531;
            8'h2c:immediate_data={31'b0,linear_mode};
            default:immediate_error=1;
        endcase
        else case(icb_cmd_addr)
            8'h00:if(icb_cmd_wdata!=2&&!do_start)immediate_error=1;
            8'h08:if(!((core_start_ready||core_layer_request)&&(icb_cmd_wdata<5||(linear_mode&&icb_cmd_wdata==5))))immediate_error=1;
            8'h0c:if(!((core_start_ready||core_layer_request)&&icb_cmd_wdata<65536))immediate_error=1;
            8'h10:if(!direct_load)immediate_error=1;
            8'h18:if(!do_layer)immediate_error=1;
            8'h2c:if(!(core_start_ready&&icb_cmd_wdata<2))immediate_error=1;
            8'h30:if(!packed_load)immediate_error=1;
            default:immediate_error=1;
        endcase
    end
'''
    comb_at=declarations.index('    always @* begin')
    registers=declarations[:comb_at];combinational=declarations[comb_at:]
    text=text[:at]+registers+text[at:]
    at=text.index('    always @(posedge clk or negedge rst_n)')
    text=text[:at]+combinational+text[at:]
    at=text.rfind('        end\n    end\nendmodule')
    if at<0:raise RuntimeError('ICB sequential response end not found')
    text=text[:at]+'            if(immediate_reply&&icb_rsp_ready)stored_rsp_valid<=0;\n'+text[at:]
    return text
