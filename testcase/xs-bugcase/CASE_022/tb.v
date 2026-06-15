`timescale 1ns/1ps

module xs_bugcase_tb (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       write_valid,
    input  logic [5:0] write_idx,
    input  logic [1:0] write_ctr,
    input  logic       write2_valid,
    input  logic [5:0] write2_idx,
    input  logic [1:0] write2_ctr,
    input  logic [5:0] read_idx,
    output logic [1:0] read_ctr
);
    TageUsefulCtrIndexedWriteCase022 dut (
        .clock(clk),
        .reset(!rst_n),
        .write_valid(write_valid),
        .write_idx(write_idx),
        .write_ctr(write_ctr),
        .write2_valid(write2_valid),
        .write2_idx(write2_idx),
        .write2_ctr(write2_ctr),
        .read_idx(read_idx),
        .read_ctr(read_ctr)
    );
endmodule
