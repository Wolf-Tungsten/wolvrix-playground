`timescale 1ns/1ps

// Minimal repro for XiangShan OldestArbiter packed aggregate row/bit reads.
module PackedAggregateBitSelectCase011(
    input  logic       clock,
    input  logic       reset,
    input  logic       load,
    input  logic [1:0] next_row0,
    input  logic [1:0] next_row1,
    output logic [3:0] priority_flat,
    output logic [1:0] row0,
    output logic [1:0] row1,
    output logic       bit00,
    output logic       bit01,
    output logic       bit10,
    output logic       bit11,
    output logic       onehot0,
    output logic       onehot1,
    output logic       ok
);
    reg [1:0][1:0] priorityVecReg;

    always @(posedge clock or posedge reset) begin
        if (reset) begin
            priorityVecReg <= '{2'h2, 2'h1};
        end
        else if (load) begin
            priorityVecReg[1'h0] <= next_row0;
            priorityVecReg[1'h1] <= next_row1;
        end
    end

    assign priority_flat = priorityVecReg;
    assign row0 = priorityVecReg[1'h0];
    assign row1 = priorityVecReg[1'h1];
    assign bit00 = priorityVecReg[1'h0][0];
    assign bit01 = priorityVecReg[1'h0][1];
    assign bit10 = priorityVecReg[1'h1][0];
    assign bit11 = priorityVecReg[1'h1][1];
    assign onehot0 =
        2'({1'h0, priorityVecReg[1'h0][0]}
           + {1'h0, priorityVecReg[1'h0][1]}) == 2'h1;
    assign onehot1 =
        2'({1'h0, priorityVecReg[1'h1][0]}
           + {1'h0, priorityVecReg[1'h1][1]}) == 2'h1;
    assign ok =
        priority_flat == {row1, row0}
        && row0 == {bit01, bit00}
        && row1 == {bit11, bit10}
        && onehot0
        && onehot1
        && row0 != row1;
endmodule
