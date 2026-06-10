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
    output logic       bit00,
    output logic       bit01,
    output logic       bit10,
    output logic       bit11,
    output logic       onehot0,
    output logic       onehot1,
    output logic       ok
);
    PackedAggregateBitSelectCase011 dut (
        .clock(clk),
        .reset(!rst_n),
        .load(load),
        .next_row0(next_row0),
        .next_row1(next_row1),
        .priority_flat(priority_flat),
        .row0(row0),
        .row1(row1),
        .bit00(bit00),
        .bit01(bit01),
        .bit10(bit10),
        .bit11(bit11),
        .onehot0(onehot0),
        .onehot1(onehot1),
        .ok(ok)
    );
endmodule
