`timescale 1ns/1ps

module TageSetIdxTableCase021(
    input  logic       clock,
    input  logic       reset,
    input  logic       write_valid,
    input  logic [8:0] write_set_idx,
    input  logic [3:0] write_payload,
    output logic [8:0] observed_set_idx,
    output logic [3:0] observed_payload
);
    always @(posedge clock or posedge reset) begin
        if (reset) begin
            observed_set_idx <= 9'h0;
            observed_payload <= 4'h0;
        end
        else if (write_valid) begin
            observed_set_idx <= write_set_idx;
            observed_payload <= write_payload;
        end
    end
endmodule

// Minimal repro for XiangShan Tage t2_setIdx preserve-aggregate lowering.
module TageSetIdxAggregateCase021(
    input  logic       clock,
    input  logic       reset,
    input  logic       t0_fire,
    input  logic [8:0] start_idx,
    input  logic [3:0] payload_in,
    output logic [8:0] child0_set_idx,
    output logic [8:0] child1_set_idx,
    output logic [3:0] child0_payload,
    output logic [3:0] child1_payload
);
    wire [7:0][8:0] t0_setIdx;
    reg [7:0][8:0] t1_setIdx;
    reg [7:0][8:0] t2_setIdx;
    reg [3:0] t1_payload;
    reg [3:0] t2_payload;
    reg       t1_fire;
    reg       t2_fire;

    assign t0_setIdx = {
        start_idx + 9'h7,
        start_idx + 9'h6,
        start_idx + 9'h5,
        start_idx + 9'h4,
        start_idx + 9'h3,
        start_idx + 9'h2,
        start_idx + 9'h1,
        start_idx
    };

    always @(posedge clock or posedge reset) begin
        if (reset) begin
            t1_setIdx <= '0;
            t2_setIdx <= '0;
            t1_payload <= 4'h0;
            t2_payload <= 4'h0;
            t1_fire <= 1'b0;
            t2_fire <= 1'b0;
        end
        else begin
            t1_setIdx <= t0_setIdx;
            t2_setIdx <= t1_setIdx;
            t1_payload <= payload_in;
            t2_payload <= t1_payload;
            t1_fire <= t0_fire;
            t2_fire <= t1_fire;
        end
    end

    TageSetIdxTableCase021 table0 (
        .clock(clock),
        .reset(reset),
        .write_valid(t2_fire),
        .write_set_idx(t2_setIdx[3'h0]),
        .write_payload(t2_payload),
        .observed_set_idx(child0_set_idx),
        .observed_payload(child0_payload)
    );

    TageSetIdxTableCase021 table1 (
        .clock(clock),
        .reset(reset),
        .write_valid(t2_fire),
        .write_set_idx(t2_setIdx[3'h1]),
        .write_payload(t2_payload),
        .observed_set_idx(child1_set_idx),
        .observed_payload(child1_payload)
    );

endmodule
