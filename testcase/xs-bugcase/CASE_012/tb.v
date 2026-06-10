`timescale 1ns/1ps

module xs_bugcase_tb (
    input  logic       clk,
    input  logic       rst_n,
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
    PackedAggregateMixedSelectCase012 dut (
        .clock(clk),
        .reset(!rst_n),
        .load(load),
        .next_row0(next_row0),
        .next_row1(next_row1),
        .priority_flat(priority_flat),
        .row0(row0),
        .row1(row1),
        .onehot1_comb(onehot1_comb),
        .sampled_fail(sampled_fail),
        .different_ok(different_ok),
        .ok(ok)
    );
endmodule
