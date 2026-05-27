`timescale 1ns/1ps

module ActivityScheduleCycleCase008 (
    input  logic        clock,
    input  logic        reset,
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
    wire        only_s2 = req == 2'h2;
    wire [26:0] gvpn = only_s2 ? a : b;
    wire [1:0][26:0] packed_vec = {c, gvpn};
    wire [26:0] selected = packed_vec[idx[0]];
    wire        write_cond = only_s2 | flag;
    wire [26:0] rhs = write_cond ? selected : fallback;

    assign early_use = gvpn ^ dummy;

    always_ff @(posedge clock) begin
        if (reset) begin
            q <= '0;
        end else if (en) begin
            q <= rhs;
        end
    end
endmodule
