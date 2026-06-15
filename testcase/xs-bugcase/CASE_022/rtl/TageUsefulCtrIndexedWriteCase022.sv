`timescale 1ns/1ps

// Minimal repro for the XiangShan FTQ `metaQueueResolve...tage.entries.*` commit
// blowup (NO0196): a register ARRAY written by a runtime index.
//
// In gsim (reads FIRRTL) this stays a `[64][2]` indexed array -> O(1) indexed
// store. The question this case isolates: when the array is present as a PACKED
// ARRAY in the SV that grhsim reads, does grhsim keep an indexed store, or does
// it flatten into 64 per-element masked read-modify-write commits?
//
// Two write ports + an indexed read, mirroring the multi-write FTQ structure.
module TageUsefulCtrIndexedWriteCase022(
    input  logic        clock,
    input  logic        reset,
    input  logic        write_valid,
    input  logic [5:0]  write_idx,
    input  logic [1:0]  write_ctr,
    input  logic        write2_valid,
    input  logic [5:0]  write2_idx,
    input  logic [1:0]  write2_ctr,
    input  logic [5:0]  read_idx,
    output logic [1:0]  read_ctr
);
    // packed array: 64 entries x 2-bit counter (the preserve-aggregate target form)
    reg [63:0][1:0] entries_usefulCtr;

    always @(posedge clock or posedge reset) begin
        if (reset) begin
            entries_usefulCtr <= '0;
        end
        else begin
            if (write_valid)  entries_usefulCtr[write_idx]  <= write_ctr;
            if (write2_valid) entries_usefulCtr[write2_idx] <= write2_ctr;
        end
    end

    assign read_ctr = entries_usefulCtr[read_idx];
endmodule
