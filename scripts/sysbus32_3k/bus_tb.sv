`timescale 1ns/1ps

module bus_tb;
    parameter COMMIT_ACK = 0;
    localparam WORDS = 256;
    localparam BASE = 32'ha0043e00;
    reg clk = 0;
    always #3.333 clk = !clk;
    reg rst_n = 0;
    reg competing = 0;
    reg [2:0] valid = 0, read = 0, response_ready = 3'b111;
    reg [31:0] addr [0:2], data [0:2];
    reg [3:0] mask [0:2];
    wire [2:0] ready, response_valid, response_err;
    wire [31:0] response_data [0:2];
    wire av, ar, ard, arv, arr, are;
    wire [31:0] aa, aw, aq;
    wire [3:0] am;
    wire br, bv, be, brd, brr, brv;
    wire [31:0] ba, bw, bq;
    wire [3:0] bm;
    wire mv = competing ? av : valid[0];
    wire mrd = competing ? ard : read[0];
    wire [31:0] ma = competing ? aa : addr[0];
    wire [31:0] mw = competing ? aw : data[0];
    wire [3:0] mm = competing ? am : mask[0];
    wire mrr = competing ? arr : response_ready[0];
    wire mr, mrv, me;
    wire [31:0] mq;

    wire [2:0] arb_ready, arb_rsp_valid, arb_rsp_err;
    wire [31:0] arb_rsp_data [0:2];
    assign ready = competing ? arb_ready : {2'b00, mr};
    assign response_valid = competing ? arb_rsp_valid : {2'b00, mrv};
    assign response_err = competing ? arb_rsp_err : {2'b00, me};
    assign response_data[0] = competing ? arb_rsp_data[0] : mq;
    assign response_data[1] = arb_rsp_data[1];
    assign response_data[2] = arb_rsp_data[2];

    kwt_sysbus_masters masters (
        .clk(clk), .rst_n(rst_n),
        .cpu_cmd_valid(competing && valid[0]), .cpu_cmd_read(read[0]), .cpu_rsp_ready(response_ready[0]),
        .cpu_cmd_addr(addr[0]), .cpu_cmd_wdata(data[0]), .cpu_cmd_wmask(mask[0]),
        .cpu_cmd_ready(arb_ready[0]), .cpu_rsp_valid(arb_rsp_valid[0]),
        .cpu_rsp_err(arb_rsp_err[0]), .cpu_rsp_rdata(arb_rsp_data[0]),
        .ld_cmd_valid(competing && valid[1]), .ld_cmd_read(read[1]), .ld_rsp_ready(response_ready[1]),
        .ld_cmd_addr(addr[1]), .ld_cmd_wdata(data[1]), .ld_cmd_wmask(mask[1]),
        .ld_cmd_ready(arb_ready[1]), .ld_rsp_valid(arb_rsp_valid[1]),
        .ld_rsp_err(arb_rsp_err[1]), .ld_rsp_rdata(arb_rsp_data[1]),
        .host_cmd_valid(competing && valid[2]), .host_cmd_read(read[2]), .host_rsp_ready(response_ready[2]),
        .host_cmd_addr(addr[2][18:2]), .host_cmd_wdata(data[2]), .host_cmd_wmask(mask[2]),
        .host_cmd_ready(arb_ready[2]), .host_rsp_valid(arb_rsp_valid[2]),
        .host_rsp_err(arb_rsp_err[2]), .host_rsp_rdata(arb_rsp_data[2]),
        .mem_cmd_valid(av), .mem_cmd_read(ard), .mem_cmd_addr(aa), .mem_cmd_wdata(aw), .mem_cmd_wmask(am),
        .mem_cmd_ready(ar), .mem_rsp_valid(arv), .mem_rsp_err(are), .mem_rsp_rdata(aq), .mem_rsp_ready(arr),
        .sram_cmd_valid(bv), .sram_cmd_ready(br), .sram_cmd_read(brd), .sram_cmd_addr(ba),
        .sram_cmd_wdata(bw), .sram_cmd_wmask(bm)
    );
    assign ar = competing && mr;
    assign arv = competing && mrv;
    assign are = me;
    assign aq = mq;

    e203_subsys_mems original (
        .clk(clk), .bus_rst_n(rst_n), .rst_n(rst_n),
        .mem_icb_cmd_valid(mv), .mem_icb_cmd_ready(mr), .mem_icb_cmd_addr(ma),
        .mem_icb_cmd_read(mrd), .mem_icb_cmd_wdata(mw), .mem_icb_cmd_wmask(mm),
        .mem_icb_rsp_valid(mrv), .mem_icb_rsp_ready(mrr), .mem_icb_rsp_err(me), .mem_icb_rsp_rdata(mq),
        .sysmem_icb_cmd_valid(bv), .sysmem_icb_cmd_ready(br), .sysmem_icb_cmd_addr(ba),
        .sysmem_icb_cmd_read(brd), .sysmem_icb_cmd_wdata(bw), .sysmem_icb_cmd_wmask(bm),
        .sysmem_icb_rsp_valid(brv), .sysmem_icb_rsp_ready(brr), .sysmem_icb_rsp_err(be), .sysmem_icb_rsp_rdata(bq),
        .qspi0_ro_icb_cmd_ready(1'b0), .qspi0_ro_icb_rsp_valid(1'b0), .qspi0_ro_icb_rsp_err(1'b0),
        .qspi0_ro_icb_rsp_rdata(32'b0), .dm_icb_cmd_ready(1'b0), .dm_icb_rsp_valid(1'b0), .dm_icb_rsp_rdata(32'b0)
    );

    wire physical_en, physical_we;
    wire [16:0] physical_addr;
    wire [31:0] physical_data;
    wire [3:0] physical_mask;
    if (COMMIT_ACK) begin : new_target
        kwt_sysbus_commit_ack target (
            .clk(clk), .rst_n(rst_n), .cmd_valid(bv), .cmd_ready(br), .cmd_addr(ba),
            .cmd_read(brd), .cmd_wdata(bw), .cmd_wmask(bm),
            .rsp_valid(brv), .rsp_ready(brr), .rsp_rdata(bq), .rsp_err(be)
        );
        assign physical_en = target.memory.en;
        assign physical_we = target.memory.we;
        assign physical_addr = target.memory.addr;
        assign physical_data = target.memory.wdata;
        assign physical_mask = target.memory.wmask;
    end else begin : old_target
        kwt_shared_icb_sm40 target (
            .clk(clk), .rst_n(rst_n), .cpu_cmd_valid(bv), .cpu_cmd_ready(br), .cpu_cmd_addr(ba),
            .cpu_cmd_read(brd), .cpu_cmd_wdata(bw), .cpu_cmd_wmask(bm),
            .cpu_rsp_valid(brv), .cpu_rsp_ready(brr), .cpu_rsp_rdata(bq), .cpu_rsp_err(be)
        );
        assign physical_en = target.memory.en;
        assign physical_we = target.memory.we;
        assign physical_addr = target.memory.addr;
        assign physical_data = target.memory.wdata;
        assign physical_mask = target.memory.wmask;
    end

    integer cycle = 0, accepted = 0, committed = 0, retired = 0, target_retired = 0;
    integer first = -1, last = -1, gaps = 0, fastest = 9999, slowest = 0;
    integer by_owner [0:2];
    integer competition = 0, upstream_stalls = 0, target_stalls = 0;
    integer owners [0:2047];
    reg reads [0:2047];
    reg [31:0] addresses [0:2047], payload [0:2047], result [0:2047];
    reg [3:0] masks [0:2047];
    reg [31:0] contents [0:WORDS-1];
    integer offset, owner, delta;
    always @(posedge clk) if (rst_n) begin
        cycle = cycle + 1;
        if (valid[0] && valid[1] && valid[2]) competition = competition + 1;
        if (|(response_valid & ~response_ready)) upstream_stalls = upstream_stalls + 1;
        if (brv && !brr) target_stalls = target_stalls + 1;
        if (mv && mr) begin
            owner = -1;
            for (integer i = 0; i < 3; i = i + 1) if (valid[i] && ready[i]) begin
                if (owner != -1) $fatal(1, "multiple accepted owners");
                owner = i;
            end
            if (owner == -1 || ma !== addr[owner] || mw !== data[owner] ||
                mm !== mask[owner] || mrd !== read[owner]) $fatal(1, "master mux identity");
            owners[accepted] = owner;
            reads[accepted] = mrd;
            addresses[accepted] = ma;
            payload[accepted] = mw;
            masks[accepted] = mm;
            accepted = accepted + 1;
            by_owner[owner] = by_owner[owner] + 1;
        end
        if (physical_en !== (bv && br)) $fatal(1, "physical enable mismatch");
        if (physical_en) begin
            if (committed >= accepted || ba !== addresses[committed] || brd !== reads[committed] ||
                physical_addr !== ba[18:2] || physical_we !== !brd)
                $fatal(1, "physical order index=%0d accepted=%0d addr=%h exp=%h read=%b exp_read=%b phys_addr=%h phys_we=%b",
                       committed, accepted, ba, addresses[committed], brd, reads[committed], physical_addr, physical_we);
            offset = (ba - BASE) / 4;
            if (offset < 0 || offset >= WORDS) $fatal(1, "address outside exercised range");
            result[committed] = brd ? contents[offset] : 32'b0;
            if (!brd) begin
                if (physical_data !== payload[committed] || physical_mask !== masks[committed])
                    $fatal(1, "physical write data or mask mismatch");
                for (integer i = 0; i < 4; i = i + 1)
                    if (physical_mask[i]) contents[offset][8*i+:8] = physical_data[8*i+:8];
                if (COMMIT_ACK && !(brv && brr && !be)) $fatal(1, "missing commit-edge write ACK");
            end
            if (first < 0) first = cycle;
            else begin
                delta = cycle - last;
                if (delta > 1) gaps = gaps + 1;
                if (delta < fastest) fastest = delta;
                if (delta > slowest) slowest = delta;
            end
            last = cycle;
            committed = committed + 1;
        end
        if (brv && brr) begin
            if (target_retired >= committed || be || bq !== result[target_retired])
                $fatal(1, "target response %0d got %h expected %h", target_retired, bq, result[target_retired]);
            target_retired = target_retired + 1;
        end
        for (integer i = 0; i < 3; i = i + 1) if (response_valid[i] && response_ready[i]) begin
            if (retired >= target_retired || i != owners[retired] || response_err[i] ||
                response_data[i] !== result[retired]) $fatal(1, "response owner/order/data %0d", retired);
            retired = retired + 1;
        end
    end

    task automatic send(input integer id, index, input bit reading, input [31:0] value, input [3:0] lanes);
        @(negedge clk);
        valid[id] = 1;
        read[id] = reading;
        addr[id] = BASE + 4 * index;
        data[id] = value;
        mask[id] = lanes;
        @(posedge clk);
        while (!ready[id]) @(posedge clk);
    endtask

    task automatic idle(input integer id);
        @(negedge clk);
        valid[id] = 0;
    endtask

    task report_phase(input string name, input integer count);
        wait (retired == count);
        @(negedge clk);
        if (accepted != count || committed != count || target_retired != count)
            $fatal(1, "command, physical access and response counts differ");
        $display("BUS_PHASE mode=%0d phase=%s total=%0d first=%0d last=%0d span=%0d min_gap=%0d max_gap=%0d gaps=%0d",
                 COMMIT_ACK, name, count, first, last, last-first+1, fastest, slowest, gaps);
        first = -1;
        last = -1;
        gaps = 0;
        fastest = 9999;
        slowest = 0;
    endtask

    initial begin
        for (integer i = 0; i < 3; i = i + 1) begin
            by_owner[i] = 0;
            addr[i] = BASE;
            data[i] = 0;
            mask[i] = 0;
        end
        repeat (5) @(negedge clk);
        rst_n = 1;
        for (integer i = 0; i < WORDS; i = i + 1) send(0, i, 0, 32'ha5810000 + i, 4'hf);
        idle(0);
        report_phase("writes", WORDS);
        for (integer i = 0; i < WORDS; i = i + 1) send(0, i, 1, 0, 0);
        idle(0);
        report_phase("reads", 2*WORDS);
        fork
            begin
                for (integer i = 0; i < 64; i = i + 1) begin
                    send(0, i, 0, 32'h12345678 + i, 4'b0101);
                    send(0, i, 1, 0, 0);
                end
                idle(0);
            end
            begin
                repeat (8) @(negedge clk);
                response_ready[0] = 0;
                repeat (19) @(negedge clk);
                response_ready[0] = 1;
            end
        join
        report_phase("turnover_mask_stall", 2*WORDS+128);
        competing = 1;
        fork
            begin
                for (integer i = 0; i < 16; i = i + 1) send(0, 128+i, 1, 0, 0);
                idle(0);
            end
            begin
                for (integer i = 0; i < 32; i = i + 1) send(1, 160+i, i[0], 32'hcde00000+i, 4'hf);
                idle(1);
            end
            begin
                for (integer i = 0; i < 64; i = i + 1) send(2, 192+i, 0, 32'hfada0000+i, 4'hf);
                idle(2);
            end
        join
        report_phase("cpu_dma_loader", 2*WORDS+240);
        if (by_owner[1] != 32 || by_owner[2] != 64 || !competition || !upstream_stalls || !target_stalls)
            $fatal(1, "competition and backpressure coverage missing");
        $display("BUS_PASS mode=%0d committed=%0d retired=%0d competing_cycles=%0d upstream_stall=%0d target_stall=%0d",
                 COMMIT_ACK, committed, retired, competition, upstream_stalls, target_stalls);
        $finish;
    end

    initial #30000 $fatal(1, "timeout accepted=%0d physical=%0d target_rsp=%0d retired=%0d mode=%0d addr=%h ready=%b pending=%b err=%b",
                          accepted, committed, target_retired, retired, competing, ma, mr, brv, be);
endmodule
