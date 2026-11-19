module kwt_lossless_source (
    input wire clk, rst_n, start, busy,
    input wire [11:0] input_committed,
    input wire [13:0] parameter_committed,
    input wire raw_valid,
    output wire raw_ready,
    input wire [31:0] raw_addr,
    output reg raw_rsp_valid,
    input wire raw_rsp_ready,
    output reg [31:0] raw_data,
    output wire source_valid,
    input wire source_ready,
    output wire [31:0] source_addr,
    input wire source_rsp_valid,
    output wire source_rsp_ready,
    input wire [31:0] source_data
);
    localparam [2:0] PARAM0=0, EARLY=1, PARAM1=2, LATE=3, OTHER=4, FINISHED=5;
    reg [2:0] phase;
    reg [11:0] input_index, input_limit, split;
    reg [13:0] parameter_index;
    reg [9:0] packet_index, packet_limit;
    reg [4:0] tile;
    reg [13:0] raw_parameter_start;
    reg [1:0] used;
    reg [1:0] owner_parameter, owner_header;
    reg head, tail;
    reg parameter_restarted;
    wire parameter_phase = phase == PARAM0 || phase == PARAM1 || phase == OTHER;
    wire header = parameter_phase ? packet_index == 0 : input_index == 0;
    wire parameter_done, input_word_ready, parameter_word_ready;
    wire can_start_tile = raw_valid && raw_addr == {16'ha002,raw_parameter_start,2'b0};
    wire read_gate = parameter_phase ?
        (header ? can_start_tile && (tile == 0 || parameter_restarted) : packet_limit != 0) :
        (header || input_limit != 0);
    assign source_addr = parameter_phase ? {16'ha002,parameter_index,2'b0} : {18'h28000,input_index,2'b0};
    assign source_valid = busy && phase != FINISHED && used < 2 && read_gate &&
                         (parameter_phase ? parameter_index < parameter_committed : input_index < input_committed);
    wire request = source_valid && source_ready;
    assign source_rsp_ready = used != 0 && (owner_parameter[head] ? parameter_word_ready : input_word_ready);
    wire response = source_rsp_valid && source_rsp_ready;
    wire parameter_refill = response && owner_parameter[head];
    wire input_refill = response && !owner_parameter[head];
    wire reset_parameter = parameter_done && parameter_phase && packet_index == 0 && used == 0;

    wire raw_parameter = raw_addr[31:16] == 16'ha002;
    wire input_valid, parameter_valid;
    wire [31:0] input_word, parameter_word;
    assign raw_ready = (!raw_rsp_valid || raw_rsp_ready) && (raw_parameter ? parameter_valid : input_valid);
    wire raw_fire = raw_valid && raw_ready;

    kwt_lossless_decode #(.INPUT_PACKET(1)) input_codec (
        .clk(clk), .rst_n(rst_n), .restart(start), .input_valid(input_refill),
        .input_ready(input_word_ready), .input_word(source_data),
        .output_valid(input_valid), .output_ready(raw_fire&&!raw_parameter), .output_word(input_word), .packet_done()
    );
    kwt_lossless_decode parameter_codec (
        .clk(clk), .rst_n(rst_n), .restart(start || reset_parameter), .input_valid(parameter_refill),
        .input_ready(parameter_word_ready), .input_word(source_data),
        .output_valid(parameter_valid), .output_ready(raw_fire&&raw_parameter), .output_word(parameter_word),
        .packet_done(parameter_done)
    );

    wire [5:0] bias_width = {1'b0,source_data[14:10]} + 6'd1;
    wire [9:0] parameter_size = source_data[9:0] + 10'd1 +
        (10'(bias_width) + 10'd1) / 2 + (10'(source_data[26:23]) + 10'd1) / 2;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            phase<=PARAM0; input_index<=0; input_limit<=0; split<=0;
            parameter_index<=0; packet_index<=0; packet_limit<=0; tile<=0; raw_parameter_start<=0;
            used<=0; head<=0; tail<=0; raw_rsp_valid<=0; parameter_restarted<=0;
        end else if (start) begin
            phase<=PARAM0; input_index<=0; input_limit<=0; split<=0;
            parameter_index<=0; packet_index<=0; packet_limit<=0; tile<=0; raw_parameter_start<=0;
            used<=0; head<=0; tail<=0; raw_rsp_valid<=0; parameter_restarted<=0;
        end else begin
            if (raw_fire) begin
                raw_rsp_valid<=1;
                raw_data<=raw_parameter ? parameter_word : input_word;
            end else if (raw_rsp_ready) raw_rsp_valid<=0;
            if (response) begin
                head<=!head;
                if (owner_header[head]) begin
                    if (owner_parameter[head]) packet_limit<=parameter_size;
                    else begin
                        input_limit<=source_data[15:4]+12'd1;
                        split<=source_data[28:17];
                    end
                end
            end
            if (reset_parameter) parameter_restarted<=1;
            if (request) begin
                tail<=!tail;
                owner_parameter[tail]<=parameter_phase;
                owner_header[tail]<=header;
                if (parameter_phase) begin
                    parameter_index<=parameter_index+14'd1;
                    packet_index<=packet_index+10'd1;
                    if (!header && packet_index+10'd1==packet_limit) begin
                        packet_limit<=0; packet_index<=0; tile<=tile+5'd1;
                        raw_parameter_start<=raw_parameter_start+14'd532;
                        parameter_restarted<=0;
                        if (tile==0) phase<=EARLY;
                        else if (tile==1) phase<=LATE;
                        else if (tile==15) phase<=FINISHED;
                    end
                end else begin
                    input_index<=input_index+12'd1;
                    if (phase==EARLY && input_index+12'd1==split) phase<=PARAM1;
                    else if (phase==LATE && input_index+12'd1==input_limit) phase<=OTHER;
                end
            end
            case ({request,response})
                2'b10: used<=used+2'd1;
                2'b01: used<=used-2'd1;
                default: ;
            endcase
        end
    end
endmodule
