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
    output wire icb_rsp_valid,
    input wire icb_rsp_ready,
    output wire [31:0] icb_rsp_rdata,
    output wire icb_rsp_err,
    output wire trace_valid,
    output wire [3:0] trace_layer,trace_stage,
    output wire [14:0] trace_index,
    output wire signed [63:0] trace_data,
    output wire trace_pair_valid,
    output wire signed [63:0] trace_high
,
    output wire ld_cmd_valid,
    input wire ld_cmd_ready,
    output wire [31:0] ld_cmd_addr,
    output wire ld_cmd_read,
    output wire [31:0] ld_cmd_wdata,
    output wire [3:0] ld_cmd_wmask,
    input wire ld_rsp_valid,
    output wire ld_rsp_ready,
    input wire [31:0] ld_rsp_rdata,
    input wire ld_rsp_err
);
wire pio_cmd_valid;
wire pio_cmd_ready;
wire [7:0] pio_cmd_addr;
wire pio_cmd_read;
wire [31:0] pio_cmd_wdata;
wire [3:0] pio_cmd_wmask;
wire pio_rsp_valid;
wire pio_rsp_ready;
wire [31:0] pio_rsp_rdata;
wire pio_rsp_err;
wire ld_error_sticky,dma_core_load_capacity_ready;

    reg stored_rsp_valid,stored_rsp_err;
    reg [31:0] stored_rsp_rdata;
    reg [31:0] immediate_data;
    reg immediate_error;
    wire immediate_reply=!stored_rsp_valid&&pio_cmd_valid&&pio_cmd_ready;
    assign pio_rsp_valid=stored_rsp_valid||immediate_reply;
    assign pio_rsp_rdata=stored_rsp_valid?stored_rsp_rdata:immediate_data;
    assign pio_rsp_err=stored_rsp_valid?stored_rsp_err:immediate_error;
    reg [2:0] load_kind;
    reg [15:0] load_address;
    reg soft_reset,done_sticky,bus_error;
    reg linear_mode,pack_pending;
    reg stream_mode;
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
    wire aligned=pio_cmd_addr[1:0]==0;
    wire event_ready=core_layer_request||core_out_valid||core_error||bus_error||done_sticky;
    wire read_event=pio_cmd_read&&aligned&&(pio_cmd_addr==8'h24);
    wire read_output=pio_cmd_read&&aligned&&(pio_cmd_addr==8'h20);
    reg output_pair_pending;
    reg [15:0] output_low;
    wire read_pair=pio_cmd_read&&aligned&&(pio_cmd_addr==8'h34);
    wire pair_second=1'b0;
    wire pair_wait=1'b0;
    wire slot_available=!stored_rsp_valid||pio_rsp_ready;
    assign pio_cmd_ready=slot_available&&!pack_pending&&!pair_wait&&(!read_event||event_ready)&&
                         (!read_output||core_out_valid||core_error||bus_error||done_sticky)&&
                         (!read_pair||core_pair_valid||core_error||bus_error||done_sticky);
    wire fire=pio_cmd_valid&&pio_cmd_ready;
    wire full_write=!pio_cmd_read&&aligned&&(pio_cmd_wmask==4'hf);
    wire [15:0] load_limit=(load_kind==0)?16'd6336:
        (load_kind==1)?(linear_mode?16'd17408:16'd51712):
        (load_kind==2)?16'd32:((load_kind==3)||(load_kind==4))?16'd8194:
        ((load_kind==5)&&linear_mode)?16'd128:16'd0;
    wire load_range=load_address<load_limit;
    wire direct_load=fire&&full_write&&(pio_cmd_addr==8'h10)&&core_load_ready&&load_range;
    wire packed_load=fire&&full_write&&(pio_cmd_addr==8'h30)&&core_load_ready&&
        ({1'b0,load_address}+17'd1<{1'b0,load_limit});
    wire flush_high=pack_pending&&core_load_ready;
    wire do_load=direct_load||packed_load||flush_high;
    wire [15:0] core_load_data=flush_high?packed_high:pio_cmd_wdata[15:0];
    wire do_start=fire&&full_write&&(pio_cmd_addr==0)&&(pio_cmd_wdata==1)&&core_start_ready;
    wire do_layer=fire&&full_write&&(pio_cmd_addr==8'h18)&&(pio_cmd_wdata==1)&&core_layer_ready;
    wire pop_output=(fire&&read_output&&core_out_valid)
                    ||pair_second
                    ;
kwt_ld_frontend dma_frontend(
    .clk(clk),.rst_n(rst_n),.soft_reset(soft_reset),.input_ready(dma_core_load_capacity_ready),.output_ready(core_pair_valid),
        .cpu_cmd_valid(icb_cmd_valid),
        .cpu_cmd_ready(icb_cmd_ready),
        .cpu_cmd_addr(icb_cmd_addr),
        .cpu_cmd_read(icb_cmd_read),
        .cpu_cmd_wdata(icb_cmd_wdata),
        .cpu_cmd_wmask(icb_cmd_wmask),
        .cpu_rsp_valid(icb_rsp_valid),
        .cpu_rsp_ready(icb_rsp_ready),
        .cpu_rsp_rdata(icb_rsp_rdata),
        .cpu_rsp_err(icb_rsp_err),
        .pio_cmd_valid(pio_cmd_valid),
        .pio_cmd_ready(pio_cmd_ready),
        .pio_cmd_addr(pio_cmd_addr),
        .pio_cmd_read(pio_cmd_read),
        .pio_cmd_wdata(pio_cmd_wdata),
        .pio_cmd_wmask(pio_cmd_wmask),
        .pio_rsp_valid(pio_rsp_valid),
        .pio_rsp_ready(pio_rsp_ready),
        .pio_rsp_rdata(pio_rsp_rdata),
        .pio_rsp_err(pio_rsp_err),
        .ld_cmd_valid(ld_cmd_valid),
        .ld_cmd_ready(ld_cmd_ready),
        .ld_cmd_addr(ld_cmd_addr),
        .ld_cmd_read(ld_cmd_read),
        .ld_cmd_wdata(ld_cmd_wdata),
        .ld_cmd_wmask(ld_cmd_wmask),
        .ld_rsp_valid(ld_rsp_valid),
        .ld_rsp_ready(ld_rsp_ready),
        .ld_rsp_rdata(ld_rsp_rdata),
        .ld_rsp_err(ld_rsp_err),
    .error_sticky(ld_error_sticky));
    kwt_encoder core(.clk(clk),.rst_n(rst_n&&!soft_reset),.linear_mode(linear_mode),.clock_test_enable(1'b0),
        .load_valid(do_load),.load_ready(core_load_ready),.load_capacity_ready(dma_core_load_capacity_ready),.load_kind(load_kind),
        .load_addr(load_address),.load_data(core_load_data),
        .load_pair(packed_load&&load_kind!=5),.load_high(pio_cmd_wdata[31:16]),
        .start_valid(do_start),.start_ready(core_start_ready),
        .layer_request(core_layer_request),.layer_index(core_layer),
        .layer_start_valid(do_layer),.layer_start_ready(core_layer_ready),
        .busy(core_busy),.done(core_done),.error(core_error),.layer_done(unused_layer_done),
        .out_valid(core_out_valid),.out_ready(pop_output),
        .out_pair_valid(core_pair_valid),.out_high(core_out_high),
        .out_pair_ready(fire&&read_pair&&core_pair_valid),.out_index(core_out_index),.out_data(core_out_data),
        .trace_valid(trace_valid),.trace_layer(trace_layer),.trace_stage(trace_stage),
        .trace_index(trace_index),.trace_data(trace_data),
        .trace_pair_valid(trace_pair_valid),.trace_high(trace_high));
    always @* begin
        immediate_data=0;immediate_error=0;
        if(!aligned||(!pio_cmd_read&&pio_cmd_wmask!=4'hf))immediate_error=1;
        else if(pio_cmd_read)case(pio_cmd_addr)
            8'h00:immediate_data={29'b0,(core_error||bus_error),done_sticky,core_busy};
            8'h04,8'h24:immediate_data=status;
            8'h08:immediate_data={29'b0,load_kind};
            8'h0c:immediate_data={16'b0,load_address};
            8'h14:immediate_data={28'b0,core_layer};
            8'h1c:if(core_out_valid)immediate_data={17'b0,core_out_index};else immediate_error=1;
            8'h20:if(core_out_valid)immediate_data={{16{core_out_data[15]}},core_out_data};else immediate_error=1;
            8'h34:if(core_pair_valid)immediate_data={core_out_high,core_out_data};else immediate_error=1;
            8'h28:immediate_data=32'h4b574531;
            8'h2c:immediate_data={30'b0,stream_mode,linear_mode};
            default:immediate_error=1;
        endcase
        else case(pio_cmd_addr)
            8'h00:if(pio_cmd_wdata!=2&&!do_start)immediate_error=1;
            8'h08:if(!((core_start_ready||core_layer_request)&&(pio_cmd_wdata<5||(linear_mode&&pio_cmd_wdata==5))))immediate_error=1;
            8'h0c:if(!((core_start_ready||core_layer_request)&&pio_cmd_wdata<65536))immediate_error=1;
            8'h10:if(!direct_load)immediate_error=1;
            8'h18:if(!do_layer)immediate_error=1;
            8'h2c:if(!(core_start_ready&&pio_cmd_wdata==3))immediate_error=1;
            8'h30:if(!packed_load)immediate_error=1;
            default:immediate_error=1;
        endcase
    end
    always @(posedge clk or negedge rst_n) begin
        if(!rst_n) begin
            load_kind<=0; load_address<=0; soft_reset<=0; done_sticky<=0; bus_error<=0;
            linear_mode<=0;stream_mode<=0; pack_pending<=0; packed_high<=0;
            stored_rsp_valid<=0; stored_rsp_err<=0; stored_rsp_rdata<=0;
            output_pair_pending<=0;output_low<=0;
        end else begin
            soft_reset<=0;
            if(ld_error_sticky)bus_error<=1;
            if(do_load) load_address<=load_address+((packed_load&&load_kind!=5)?16'd2:16'd1);
            if(flush_high) pack_pending<=0;
            if(core_done) done_sticky<=1;
            if(stored_rsp_valid&&pio_rsp_ready) stored_rsp_valid<=0;
            if(pair_second) begin
                output_pair_pending<=0;
                stored_rsp_valid<=1;stored_rsp_err<=0;
                stored_rsp_rdata<={core_out_data,output_low};
            end
            if(fire) begin
                stored_rsp_valid<=1; stored_rsp_err<=0; stored_rsp_rdata<=0;
                if(!aligned || (!pio_cmd_read&&pio_cmd_wmask!=4'hf)) begin
                    stored_rsp_err<=1;
                end else if(pio_cmd_read) begin
                    case(pio_cmd_addr)
                        8'h00: stored_rsp_rdata<={29'b0,(core_error||bus_error),done_sticky,core_busy};
                        8'h04,8'h24: stored_rsp_rdata<=status;
                        8'h08: stored_rsp_rdata<={29'b0,load_kind};
                        8'h0c: stored_rsp_rdata<={16'b0,load_address};
                        8'h14: stored_rsp_rdata<={28'b0,core_layer};
                        8'h1c: if(core_out_valid) stored_rsp_rdata<={17'b0,core_out_index}; else stored_rsp_err<=1;
                        8'h20: if(core_out_valid) stored_rsp_rdata<={{16{core_out_data[15]}},core_out_data}; else stored_rsp_err<=1;
                        8'h34: if(core_out_valid) begin
                            stored_rsp_rdata<={core_out_high,core_out_data};
                        end else stored_rsp_err<=1;
                        8'h28: stored_rsp_rdata<=32'h4b574531; // "KWE1"
                        8'h2c: stored_rsp_rdata<={30'b0,stream_mode,linear_mode};
                        default: stored_rsp_err<=1;
                    endcase
                end else begin
                    case(pio_cmd_addr)
                        8'h00: begin
                            if(pio_cmd_wdata==2) begin
                                soft_reset<=1; done_sticky<=0; bus_error<=0; load_kind<=0; load_address<=0; linear_mode<=0;stream_mode<=0; pack_pending<=0;
                            end else if(do_start) begin done_sticky<=0; bus_error<=0; end
                            else stored_rsp_err<=1;
                        end
                        8'h08: if((core_start_ready||core_layer_request)&&(pio_cmd_wdata<5||(linear_mode&&pio_cmd_wdata==5))) load_kind<=pio_cmd_wdata[2:0]; else stored_rsp_err<=1;
                        8'h0c: if((core_start_ready||core_layer_request)&&pio_cmd_wdata<65536) load_address<=pio_cmd_wdata[15:0]; else stored_rsp_err<=1;
                        8'h10: if(!direct_load) stored_rsp_err<=1;
                        8'h18: if(!do_layer) stored_rsp_err<=1;
                        8'h2c: if(core_start_ready&&pio_cmd_wdata==3) begin linear_mode<=1;stream_mode<=1;end else stored_rsp_err<=1;
                        8'h30: if(packed_load) begin packed_high<=pio_cmd_wdata[31:16]; pack_pending<=load_kind==5; end else stored_rsp_err<=1;
                        default: stored_rsp_err<=1;
                    endcase
                end
                // Bus access errors are reported in the response. Core errors persist
                // in STATE; a soft reset clears core state and all task SRAM caches.
            end
            if(immediate_reply&&pio_rsp_ready)stored_rsp_valid<=0;
        end
    end
endmodule
