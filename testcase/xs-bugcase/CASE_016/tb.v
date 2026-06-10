module xs_bugcase_tb (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        flush,
    input  logic        bpu_valid,
    input  logic        bpu_flag,
    input  logic [5:0]  bpu_value,
    input  logic        read_ready,
    input  logic        write_valid,
    input  logic [15:0] write_vset,
    input  logic [7:0]  write_waymask,
    input  logic [63:0] write_maybe_rvc,
    input  logic [1:0]  write_meta_codes,
    input  logic [35:0] write_ptag,
    input  logic [1:0]  write_itlb_pbmt,
    input  logic [2:0]  write_excp_value,
    input  logic [54:0] write_gpaddr,
    input  logic        write_is_vs_nonleaf,
    input  logic        write_ftq_flag,
    input  logic [5:0]  write_ftq_value,
    input  logic        update_valid,
    input  logic [41:0] update_blk_paddr,
    input  logic [7:0]  update_vset,
    input  logic [3:0]  update_waymask,
    input  logic [31:0] update_maybe_rvc,
    input  logic        update_corrupt,
    output logic        read_valid,
    output logic [15:0] read_vset,
    output logic [7:0]  read_waymask,
    output logic [63:0] read_maybe_rvc,
    output logic [1:0]  read_meta_codes,
    output logic [35:0] read_ptag,
    output logic [1:0]  read_itlb_pbmt,
    output logic [2:0]  read_excp_value,
    output logic [54:0] read_gpaddr,
    output logic        read_is_vs_nonleaf,
    output logic        write_ready,
    output logic        perf_empty
);
    logic [1:0][7:0]  write_vset_vec;
    logic [1:0][3:0]  write_waymask_vec;
    logic [1:0][31:0] write_maybe_rvc_vec;
    logic [1:0][7:0]  read_vset_vec;
    logic [1:0][3:0]  read_waymask_vec;
    logic [1:0][31:0] read_maybe_rvc_vec;

    assign write_vset_vec = {write_vset[15:8], write_vset[7:0]};
    assign write_waymask_vec = {write_waymask[7:4], write_waymask[3:0]};
    assign write_maybe_rvc_vec = {write_maybe_rvc[63:32], write_maybe_rvc[31:0]};

    assign read_vset = {read_vset_vec[1], read_vset_vec[0]};
    assign read_waymask = {read_waymask_vec[1], read_waymask_vec[0]};
    assign read_maybe_rvc = {read_maybe_rvc_vec[1], read_maybe_rvc_vec[0]};

    ICacheWayLookup dut (
        .clock(clk),
        .reset(!rst_n),
        .io_flush(flush),
        .io_flushFromBpu_s3_valid(bpu_valid),
        .io_flushFromBpu_s3_bits_flag(bpu_flag),
        .io_flushFromBpu_s3_bits_value(bpu_value),
        .io_read_ready(read_ready),
        .io_read_valid(read_valid),
        .io_read_bits_entry_vSetIdx(read_vset_vec),
        .io_read_bits_entry_waymask(read_waymask_vec),
        .io_read_bits_entry_maybeRvcMap(read_maybe_rvc_vec),
        .io_read_bits_entry_metaCodes(read_meta_codes),
        .io_read_bits_entry_pTag(read_ptag),
        .io_read_bits_entry_itlbPbmt(read_itlb_pbmt),
        .io_read_bits_exceptionEntry_itlbException_value(read_excp_value),
        .io_read_bits_exceptionEntry_gpAddr_addr(read_gpaddr),
        .io_read_bits_exceptionEntry_isForVSnonLeafPTE(read_is_vs_nonleaf),
        .io_write_ready(write_ready),
        .io_write_valid(write_valid),
        .io_write_bits_entry_vSetIdx(write_vset_vec),
        .io_write_bits_entry_waymask(write_waymask_vec),
        .io_write_bits_entry_maybeRvcMap(write_maybe_rvc_vec),
        .io_write_bits_entry_metaCodes(write_meta_codes),
        .io_write_bits_entry_pTag(write_ptag),
        .io_write_bits_entry_itlbPbmt(write_itlb_pbmt),
        .io_write_bits_exceptionEntry_itlbException_value(write_excp_value),
        .io_write_bits_exceptionEntry_gpAddr_addr(write_gpaddr),
        .io_write_bits_exceptionEntry_isForVSnonLeafPTE(write_is_vs_nonleaf),
        .io_write_bits_ftqIdx_flag(write_ftq_flag),
        .io_write_bits_ftqIdx_value(write_ftq_value),
        .io_update_valid(update_valid),
        .io_update_bits_blkPAddr(update_blk_paddr),
        .io_update_bits_vSetIdx(update_vset),
        .io_update_bits_waymask(update_waymask),
        .io_update_bits_maybeRvcMap(update_maybe_rvc),
        .io_update_bits_corrupt(update_corrupt),
        .io_perf_empty(perf_empty)
    );
endmodule
