`timescale 1ns/1ps

module PackedWideMemoryFillCase010(
    input  logic         clock,
    input  logic         reset,
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
    reg [3:0][31:0] regs;

    always @(posedge clock or posedge reset) begin
        if (reset) begin
            regs <= '{32'h44332211, 32'h88776655, 32'hCCBBAA99, 32'h00FFEEDD};
        end
        else if (load) begin
            regs <= {packed_in3, packed_in2, packed_in1, packed_in0};
        end
    end

    assign row0 = regs[0];
    assign row1 = regs[1];
    assign row2 = regs[2];
    assign row3 = regs[3];
    assign checksum = regs[0] ^ regs[1] ^ regs[2] ^ regs[3];
endmodule
