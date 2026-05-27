`timescale 1ns/1ps

module xs_bugcase_tb (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        en,
    input  logic [1:0]  req,
    input  logic        flag,
    input  logic [26:0] a,
    input  logic [26:0] b,
    input  logic [26:0] c,
    input  logic [26:0] fallback,
    input  logic [1:0]  idx,
    input  logic [26:0] dummy,
    output logic [26:0] q,
    output logic [26:0] early_use
);
    ActivityScheduleCycleCase008 dut (
        .clock(clk),
        .reset(!rst_n),
        .en(en),
        .req(req),
        .flag(flag),
        .a(a),
        .b(b),
        .c(c),
        .fallback(fallback),
        .idx(idx),
        .dummy(dummy),
        .q(q),
        .early_use(early_use)
    );
endmodule
