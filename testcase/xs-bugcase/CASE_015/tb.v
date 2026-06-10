module xs_bugcase_tb (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       touch0_valid,
    input  logic [7:0] touch0_vset,
    input  logic [1:0] touch0_way,
    input  logic       touch1_valid,
    input  logic [7:0] touch1_vset,
    input  logic [1:0] touch1_way,
    input  logic       victim_valid,
    input  logic [7:0] victim_vset,
    output logic [1:0] victim_way
);
    ICacheReplacer dut (
        .clock(clk),
        .reset(!rst_n),
        .io_touch_req_0_valid(touch0_valid),
        .io_touch_req_0_bits_vSetIdx(touch0_vset),
        .io_touch_req_0_bits_way(touch0_way),
        .io_touch_req_1_valid(touch1_valid),
        .io_touch_req_1_bits_vSetIdx(touch1_vset),
        .io_touch_req_1_bits_way(touch1_way),
        .io_victim_req_valid(victim_valid),
        .io_victim_req_bits_vSetIdx(victim_vset),
        .io_victim_resp_way(victim_way)
    );
endmodule
