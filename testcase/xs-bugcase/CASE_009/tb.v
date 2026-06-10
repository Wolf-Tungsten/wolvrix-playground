`timescale 1ns/1ps

module xs_bugcase_tb (
    input  logic       clk,
    input  logic       rst_n,
    input  logic [2:0] in_valid,
    input  logic [1:0] older0,
    input  logic [1:0] older1,
    input  logic [1:0] older2,
    output logic [1:0] valid2,
    output logic [3:0] priority2,
    output logic       ok2,
    output logic [2:0] valid3,
    output logic [8:0] priority3,
    output logic       ok3
);
    OldestArbiterReset2Case009 dut2 (
        .clock(clk),
        .reset(!rst_n),
        .in_valid(in_valid[1:0]),
        .older({older1[0], older0[0]}),
        .valid(valid2),
        .priority_flat(priority2),
        .priority_ok(ok2)
    );

    OldestArbiterReset3Case009 dut3 (
        .clock(clk),
        .reset(!rst_n),
        .in_valid(in_valid),
        .older0(older0),
        .older1(older1),
        .older2(older2),
        .valid(valid3),
        .priority_flat(priority3),
        .priority_ok(ok3)
    );
endmodule
