module rewrite_fixture (
    input logic clock,
    input logic reset,
    input logic [7:0] a,
    output wire [7:0] y,
    output logic [7:0] q
);
    assign y = a[7:0];
    always_ff @(posedge clock) begin
        if (reset) q <= '0;
        else q <= y ^ q;
    end
endmodule
