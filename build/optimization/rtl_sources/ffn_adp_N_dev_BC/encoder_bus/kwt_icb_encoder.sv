// Single-outstanding ICB slave for linear-only and complete encoder tasks.
// EVENT/OUT may wait for hardware progress; blocked DATA writes return errors.
module kwt_icb_encoder(
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
    output wire trace_valid,
    output wire [3:0] trace_layer,trace_stage,
    output wire [14:0] trace_index,
    output wire signed [63:0] trace_data
);
    reg [2:0] load_kind;
    reg [15:0] load_address;
    reg soft_reset,done_sticky,bus_error;
    reg linear_mode,pack_pending;
    reg [15:0] packed_high;
    wire core_load_ready,core_start_ready,core_layer_request,core_layer_ready;
    wire core_pair_valid;
    wire signed [15:0] core_out_high;
    wire core_busy,core_done,core_error,unused_layer_done,core_out_valid;
    wire [3:0] core_layer;
    wire [14:0] core_out_index;
    wire signed [15:0] core_out_data;
    wire [31:0] status={24'b0,(core_error||bus_error),done_sticky,core_layer_ready,
                       core_layer_request,core_start_ready,core_load_ready,core_out_valid,core_busy};
    wire aligned=icb_cmd_addr[1:0]==0;
    wire event_ready=core_layer_request||core_out_valid||core_error||bus_error||done_sticky;
    wire read_event=icb_cmd_read&&aligned&&(icb_cmd_addr==8'h24);
    wire read_output=icb_cmd_read&&aligned&&(icb_cmd_addr==8'h20);
    reg output_pair_pending;
    reg [15:0] output_low;
    wire read_pair=icb_cmd_read&&aligned&&(icb_cmd_addr==8'h34);
    wire pair_second=output_pair_pending&&core_out_valid;
    wire pair_wait=output_pair_pending;
    wire slot_available=!icb_rsp_valid||icb_rsp_ready;
    assign icb_cmd_ready=slot_available&&!pack_pending&&!pair_wait&&(!read_event||event_ready)&&
                         (!(read_output||read_pair)||core_out_valid||core_error||bus_error||done_sticky);
    wire fire=icb_cmd_valid&&icb_cmd_ready;
    wire full_write=!icb_cmd_read&&aligned&&(icb_cmd_wmask==4'hf);
    wire [15:0] load_limit=(load_kind==0)?16'd6336:
        (load_kind==1)?(linear_mode?16'd17408:16'd51712):
        (load_kind==2)?16'd32:((load_kind==3)||(load_kind==4))?16'd8194:
        ((load_kind==5)&&linear_mode)?16'd128:16'd0;
    wire load_range=load_address<load_limit;
    wire direct_load=fire&&full_write&&(icb_cmd_addr==8'h10)&&core_load_ready&&load_range;
    wire packed_load=fire&&full_write&&(icb_cmd_addr==8'h30)&&core_load_ready&&
        ({1'b0,load_address}+17'd1<{1'b0,load_limit});
    wire flush_high=pack_pending&&core_load_ready;
    wire do_load=direct_load||packed_load||flush_high;
    wire [15:0] core_load_data=flush_high?packed_high:icb_cmd_wdata[15:0];
    wire do_start=fire&&full_write&&(icb_cmd_addr==0)&&(icb_cmd_wdata==1)&&core_start_ready;
    wire do_layer=fire&&full_write&&(icb_cmd_addr==8'h18)&&(icb_cmd_wdata==1)&&core_layer_ready;
    wire pop_output=(fire&&(read_output||read_pair)&&core_out_valid)
                    ||pair_second
                    ;
    kwt_encoder core(.clk(clk),.rst_n(rst_n&&!soft_reset),.linear_mode(linear_mode),.clock_test_enable(1'b0),
        .load_valid(do_load),.load_ready(core_load_ready),.load_kind(load_kind),
        .load_addr(load_address),.load_data(core_load_data),.load_pair(1'b0),.load_high(16'b0),
        .start_valid(do_start),.start_ready(core_start_ready),
        .layer_request(core_layer_request),.layer_index(core_layer),
        .layer_start_valid(do_layer),.layer_start_ready(core_layer_ready),
        .busy(core_busy),.done(core_done),.error(core_error),.layer_done(unused_layer_done),
        .out_valid(core_out_valid),.out_ready(pop_output),
        .out_pair_valid(core_pair_valid),.out_high(core_out_high),
        .out_pair_ready(1'b0),.out_index(core_out_index),.out_data(core_out_data),
        .trace_valid(trace_valid),.trace_layer(trace_layer),.trace_stage(trace_stage),
        .trace_index(trace_index),.trace_data(trace_data));
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            load_kind<=0; load_address<=0; soft_reset<=0; done_sticky<=0; bus_error<=0;
            linear_mode<=0; pack_pending<=0; packed_high<=0;
            icb_rsp_valid<=0; icb_rsp_err<=0; icb_rsp_rdata<=0;
            output_pair_pending<=0;output_low<=0;
        end else begin
            soft_reset<=0;
            if(do_load) load_address<=load_address+1'b1;
            if(flush_high) pack_pending<=0;
            if(core_done) done_sticky<=1;
            if(icb_rsp_valid&&icb_rsp_ready) icb_rsp_valid<=0;
            if(pair_second) begin
                output_pair_pending<=0;
                icb_rsp_valid<=1;icb_rsp_err<=0;
                icb_rsp_rdata<={core_out_data,output_low};
            end
            if(fire) begin
                icb_rsp_valid<=1; icb_rsp_err<=0; icb_rsp_rdata<=0;
                if(!aligned || (!icb_cmd_read&&icb_cmd_wmask!=4'hf)) begin
                    icb_rsp_err<=1;
                end else if(icb_cmd_read) begin
                    case(icb_cmd_addr)
                        8'h00: icb_rsp_rdata<={29'b0,(core_error||bus_error),done_sticky,core_busy};
                        8'h04,8'h24: icb_rsp_rdata<=status;
                        8'h08: icb_rsp_rdata<={29'b0,load_kind};
                        8'h0c: icb_rsp_rdata<={16'b0,load_address};
                        8'h14: icb_rsp_rdata<={28'b0,core_layer};
                        8'h1c: if(core_out_valid) icb_rsp_rdata<={17'b0,core_out_index}; else icb_rsp_err<=1;
                        8'h20: if(core_out_valid) icb_rsp_rdata<={{16{core_out_data[15]}},core_out_data}; else icb_rsp_err<=1;
                        8'h34: if(core_out_valid) begin
                            output_low<=core_out_data;output_pair_pending<=1;icb_rsp_valid<=0;
                        end else icb_rsp_err<=1;
                        8'h28: icb_rsp_rdata<=32'h4b574531; // "KWE1"
                        8'h2c: icb_rsp_rdata<={31'b0,linear_mode};
                        default: icb_rsp_err<=1;
                    endcase
                end else begin
                    case(icb_cmd_addr)
                        8'h00: begin
                            if(icb_cmd_wdata==2) begin
                                soft_reset<=1; done_sticky<=0; bus_error<=0; load_kind<=0; load_address<=0; linear_mode<=0; pack_pending<=0;
                            end else if(do_start) begin done_sticky<=0; bus_error<=0; end
                            else icb_rsp_err<=1;
                        end
                        8'h08: if((core_start_ready||core_layer_request)&&(icb_cmd_wdata<5||(linear_mode&&icb_cmd_wdata==5))) load_kind<=icb_cmd_wdata[2:0]; else icb_rsp_err<=1;
                        8'h0c: if((core_start_ready||core_layer_request)&&icb_cmd_wdata<65536) load_address<=icb_cmd_wdata[15:0]; else icb_rsp_err<=1;
                        8'h10: if(!direct_load) icb_rsp_err<=1;
                        8'h18: if(!do_layer) icb_rsp_err<=1;
                        8'h2c: if(core_start_ready&&icb_cmd_wdata<2) linear_mode<=icb_cmd_wdata[0]; else icb_rsp_err<=1;
                        8'h30: if(packed_load) begin packed_high<=icb_cmd_wdata[31:16]; pack_pending<=1; end else icb_rsp_err<=1;
                        default: icb_rsp_err<=1;
                    endcase
                end
                // Bus access errors are reported in the response. Core errors persist
                // in STATE; a soft reset clears core state and all task SRAM caches.
            end
        end
    end
endmodule
