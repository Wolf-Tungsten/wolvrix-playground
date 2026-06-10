`timescale 1ns/1ps

// Repro for XiangShan OldestArbiter packed aggregate mixed read path.
module PackedAggregateMixedSelectCase012(
    input  logic       clock,
    input  logic       reset,
    input  logic       load,
    input  logic [1:0] next_row0,
    input  logic [1:0] next_row1,
    output logic [3:0] priority_flat,
    output logic [1:0] row0,
    output logic [1:0] row1,
    output logic       onehot1_comb,
    output logic       sampled_fail,
    output logic       different_ok,
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

    wire different_fail =
        ~reset & 2'({1'h0, priorityVecReg[1'h1] == priorityVecReg[1'h0]} + 2'h1) != 2'h1;
    wire onehot1_fail =
        ~reset & 2'({1'h0, priorityVecReg[1'h1][0]}
                    + {1'h0, priorityVecReg[1'h1][1]}) != 2'h1;

    always @(posedge clock) begin
        if (reset)
            sampled_fail <= 1'b0;
        else
            sampled_fail <= onehot1_fail;
    end

    always @(posedge clock) begin
        if (onehot1_fail)
            $fatal(1, "priorityVecReg[1] must be one hot");
    end

    assign priority_flat = priorityVecReg;
    assign row0 = priorityVecReg[1'h0];
    assign row1 = priorityVecReg[1'h1];
    assign onehot1_comb = ~onehot1_fail;
    assign different_ok = ~different_fail;
    assign ok =
        priority_flat == {row1, row0}
        && row0 != row1
        && (row0 == 2'h1 || row0 == 2'h2)
        && (row1 == 2'h1 || row1 == 2'h2)
        && onehot1_comb
        && !sampled_fail
        && different_ok;
endmodule
