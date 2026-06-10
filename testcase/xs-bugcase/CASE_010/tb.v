`timescale 1ns/1ps

module xs_bugcase_tb (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         load,
    input  logic [31:0]  packed_in0,
    input  logic [31:0]  packed_in1,
    input  logic [31:0]  packed_in2,
    input  logic [31:0]  packed_in3,
    output logic [31:0]  row0,
    output logic [31:0]  row1,
    output logic [31:0]  row2,
    output logic [31:0]  row3,
    output logic [31:0]  checksum
);
    PackedWideMemoryFillCase010 dut (
        .clock(clk),
        .reset(!rst_n),
        .load(load),
        .packed_in0(packed_in0),
        .packed_in1(packed_in1),
        .packed_in2(packed_in2),
        .packed_in3(packed_in3),
        .row0(row0),
        .row1(row1),
        .row2(row2),
        .row3(row3),
        .checksum(checksum)
    );
endmodule
