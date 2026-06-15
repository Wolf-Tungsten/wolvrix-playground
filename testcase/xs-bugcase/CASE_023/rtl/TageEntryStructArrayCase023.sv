`timescale 1ns/1ps

// Companion to CASE_022. The XiangShan FTQ `entries` is a Vec-of-BUNDLE.
// firtool currently SCALARIZES that into `entries_0_usefulCtr, entries_1_...`
// (4096 scalar regs on the real core -> per-field per-index scalar commits).
//
// This case models the VIABLE FIX TARGET: split the bundle into one PACKED ARRAY
// per field (bundle fields become parallel vecs, indexed by the same write idx).
// If grhsim lowers each field-array to an indexed memory store, the fix is just
// "firtool must preserve the vec dimension per bundle field" — no per-slot blowup.
//
// (Packed `struct` member-select is NOT an option: wolvrix's SV frontend rejects
//  `entries[i].field` — see CASE_023 history. So per-field packed arrays it is.)
module TageEntryStructArrayCase023(
    input  logic        clock,
    input  logic        reset,
    input  logic        write_valid,
    input  logic [5:0]  write_idx,
    input  logic [1:0]  write_usefulCtr,
    input  logic        write_useProvider,
    input  logic [2:0]  write_providerTableIdx,
    input  logic [5:0]  read_idx,
    output logic [1:0]  read_usefulCtr,
    output logic        read_useProvider,
    output logic [2:0]  read_providerTableIdx
);
    reg [63:0][1:0] entries_usefulCtr;
    reg [63:0]      entries_useProvider;
    reg [63:0][2:0] entries_providerTableIdx;

    always @(posedge clock or posedge reset) begin
        if (reset) begin
            entries_usefulCtr        <= '0;
            entries_useProvider      <= '0;
            entries_providerTableIdx <= '0;
        end
        else if (write_valid) begin
            entries_usefulCtr[write_idx]        <= write_usefulCtr;
            entries_useProvider[write_idx]      <= write_useProvider;
            entries_providerTableIdx[write_idx] <= write_providerTableIdx;
        end
    end

    assign read_usefulCtr        = entries_usefulCtr[read_idx];
    assign read_useProvider      = entries_useProvider[read_idx];
    assign read_providerTableIdx = entries_providerTableIdx[read_idx];
endmodule
