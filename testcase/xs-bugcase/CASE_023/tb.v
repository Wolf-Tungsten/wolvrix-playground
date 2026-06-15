`timescale 1ns/1ps
module xs_bugcase_tb (
    input  logic       clk, rst_n,
    input  logic       write_valid,
    input  logic [5:0] write_idx,
    input  logic [1:0] write_usefulCtr,
    input  logic       write_useProvider,
    input  logic [2:0] write_providerTableIdx,
    input  logic [5:0] read_idx,
    output logic [1:0] read_usefulCtr,
    output logic       read_useProvider,
    output logic [2:0] read_providerTableIdx
);
    TageEntryStructArrayCase023 dut (
        .clock(clk), .reset(!rst_n),
        .write_valid(write_valid), .write_idx(write_idx),
        .write_usefulCtr(write_usefulCtr), .write_useProvider(write_useProvider),
        .write_providerTableIdx(write_providerTableIdx),
        .read_idx(read_idx),
        .read_usefulCtr(read_usefulCtr), .read_useProvider(read_useProvider),
        .read_providerTableIdx(read_providerTableIdx)
    );
endmodule
