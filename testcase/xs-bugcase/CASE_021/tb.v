`timescale 1ns/1ps

module xs_bugcase_tb (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       t0_fire,
    input  logic [8:0] start_idx,
    input  logic [3:0] payload_in,
    output logic [8:0] child0_set_idx,
    output logic [8:0] child1_set_idx,
    output logic [3:0] child0_payload,
    output logic [3:0] child1_payload,
    output logic       ok
);
    TageSetIdxAggregateCase021 dut (
        .clock(clk),
        .reset(!rst_n),
        .t0_fire(t0_fire),
        .start_idx(start_idx),
        .payload_in(payload_in),
        .child0_set_idx(child0_set_idx),
        .child1_set_idx(child1_set_idx),
        .child0_payload(child0_payload),
        .child1_payload(child1_payload)
    );

    assign ok = rst_n ? (child1_set_idx == child0_set_idx + 9'h1
                         && child0_payload == child1_payload) : 1'b1;
endmodule
