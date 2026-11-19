// Prefix-count invariant for the two SR read pointers and the RD addresses.
module rd_address_induction(
    input [14:0] item,
    input [1:0] held, pending, pop, issue,
    input pending_row1, read_row1,
    input [6:0] old0,
    input [7:0] old1,
    output ok
);
    function automatic [15:0] prefix1(input [15:0] end_item);
        prefix1 = {1'b0,end_item[15:9],8'b0}
                  + (end_item[8] ? {8'b0,end_item[7:0]} : 16'd0);
    endfunction
    wire [15:0] captured = {1'b0,item} + {14'b0,held};
    wire [15:0] next_item = captured + {14'b0,pending};
    wire [15:0] row1_captured = prefix1(captured);
    wire [15:0] row1_next = prefix1(next_item);
    wire [15:0] row0_captured = captured - row1_captured;
    wire [15:0] row0_next = next_item - row1_next;
    wire [1:0] capture0 = pending_row1 ? 2'd0 : pending;
    wire [1:0] capture1 = pending_row1 ? pending : 2'd0;
    wire [6:0] advanced0 = old0 + {5'b0,capture0};
    wire [7:0] advanced1 = old1 + {6'b0,capture1};
    wire [15:0] item_after = {1'b0,item} + {14'b0,pop};
    wire [2:0] held_after = {1'b0,held} - {1'b0,pop} + {1'b0,pending};
    wire [15:0] captured_after = item_after + {13'b0,held_after};
    wire [15:0] issued_end = next_item + {14'b0,issue};
    wire pending_legal = pending == 0 || (captured[8] == pending_row1 &&
                         (pending != 2 || (pending_row1 && captured[7:0] != 8'hff)));
    wire issue_legal = issue == 0 || (next_item[8] == read_row1 &&
                       (issue != 2 || (read_row1 && next_item[7:0] != 8'hff)));
    wire legal = held <= 2 && pending <= 2 &&
                 ({1'b0,held}+{1'b0,pending}) <= 2 && pop <= held && pending_legal &&
                 issue <= 2 && issue_legal && held_after + {1'b0,issue} <= 2 && issued_end <= 25344 &&
                 old0 == row0_captured[6:0] && old1 == row1_captured[7:0];
    assign ok = !legal || (
        // Old pending returns extend the captured prefix before the new read.
        advanced0 == row0_next[6:0] && advanced1 == row1_next[7:0] &&
        captured_after == next_item &&
        (issue == 0 || (read_row1 ? advanced1 == next_item[7:0] : advanced0 == next_item[6:0])));
endmodule

