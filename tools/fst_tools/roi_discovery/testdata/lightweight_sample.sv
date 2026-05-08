module HelperStage (
    input logic clk,
    input logic req_valid,
    output logic resp_ready
);
    logic [63:0] helper_data;
    assign resp_ready = req_valid;
endmodule

module ExecUnit (
    input logic clk,
    input logic req_valid,
    output logic resp_ready
);
    logic writeback_data_valid;
    logic [63:0] writeback_data;

    HelperStage helper_stage (
        .clk(clk),
        .req_valid(req_valid),
        .resp_ready(resp_ready)
    );

    always_ff @(posedge clk) begin
        if (req_valid) begin
            writeback_data_valid <= 1'b1;
            writeback_data <= 64'h0;
        end
    end
endmodule