`timescale 1ns/1ps

// Minimal repro for XiangShan OldestArbiter preserve-aggregate reset handling.
module OldestArbiterReset2Case009(
    input  logic       clock,
    input  logic       reset,
    input  logic [1:0] in_valid,
    input  logic [1:0] older,
    output logic [1:0] valid,
    output logic [3:0] priority_flat,
    output logic       priority_ok
);
    reg [1:0] validVecReg;
    reg [1:0][1:0] priorityVecReg;

    always @(posedge clock or posedge reset) begin
        if (reset) begin
            validVecReg <= '{1'h0, 1'h0};
            priorityVecReg <= '{2'h2, 2'h1};
        end
        else begin
            validVecReg[1'h1] <= in_valid[1];
            validVecReg[1'h0] <= in_valid[0];
            priorityVecReg[1'h1] <= (&validVecReg) ? (2'h2 >> older[1]) : 2'h2;
            priorityVecReg[1'h0] <= (&validVecReg) ? (2'h2 >> older[0]) : 2'h1;
        end
    end

    assign valid = validVecReg;
    assign priority_flat = priorityVecReg;
    assign priority_ok =
        (priorityVecReg[1'h0] == 2'h1 || priorityVecReg[1'h0] == 2'h2)
        && (priorityVecReg[1'h1] == 2'h1 || priorityVecReg[1'h1] == 2'h2)
        && (priorityVecReg[1'h0] != priorityVecReg[1'h1]);
endmodule

module OldestArbiterReset3Case009(
    input  logic       clock,
    input  logic       reset,
    input  logic [2:0] in_valid,
    input  logic [1:0] older0,
    input  logic [1:0] older1,
    input  logic [1:0] older2,
    output logic [2:0] valid,
    output logic [8:0] priority_flat,
    output logic       priority_ok
);
    reg [2:0] validVecReg;
    reg [2:0][2:0] priorityVecReg;

    wire [1:0] otherValidNum0 = {1'h0, validVecReg[2'h1]} + {1'h0, validVecReg[2'h2]};
    wire [1:0] otherValidNum1 = {1'h0, validVecReg[2'h0]} + {1'h0, validVecReg[2'h2]};
    wire [1:0] otherValidNum2 = {1'h0, validVecReg[2'h0]} + {1'h0, validVecReg[2'h1]};
    wire [3:0] fallback2 = 4'h1 << (otherValidNum2[1] ? otherValidNum2 : 2'h2);
    wire [3:0] fallback1 = 4'h1 << (otherValidNum1[1] ? otherValidNum1 : 2'h1);
    wire [3:0] fallback0 = 4'h1 << (otherValidNum0[1] ? otherValidNum0 : 2'h0);

    always @(posedge clock or posedge reset) begin
        if (reset) begin
            validVecReg <= '{1'h0, 1'h0, 1'h0};
            priorityVecReg <= '{3'h4, 3'h2, 3'h1};
        end
        else begin
            validVecReg[2'h2] <= in_valid[2];
            validVecReg[2'h1] <= in_valid[1];
            validVecReg[2'h0] <= in_valid[0];
            priorityVecReg[2'h2] <=
                validVecReg[2'h2] & (|otherValidNum2)
                    ? 3'h4 >> older2
                    : fallback2[2:0];
            priorityVecReg[2'h1] <=
                validVecReg[2'h1] & (|otherValidNum1)
                    ? 3'h4 >> older1
                    : fallback1[2:0];
            priorityVecReg[2'h0] <=
                validVecReg[2'h0] & (|otherValidNum0)
                    ? 3'h4 >> older0
                    : fallback0[2:0];
        end
    end

    assign valid = validVecReg;
    assign priority_flat = priorityVecReg;
    assign priority_ok =
        (priorityVecReg[2'h0] == 3'h1 || priorityVecReg[2'h0] == 3'h2 || priorityVecReg[2'h0] == 3'h4)
        && (priorityVecReg[2'h1] == 3'h1 || priorityVecReg[2'h1] == 3'h2 || priorityVecReg[2'h1] == 3'h4)
        && (priorityVecReg[2'h2] == 3'h1 || priorityVecReg[2'h2] == 3'h2 || priorityVecReg[2'h2] == 3'h4)
        && (priorityVecReg[2'h0] != priorityVecReg[2'h1])
        && (priorityVecReg[2'h0] != priorityVecReg[2'h2])
        && (priorityVecReg[2'h1] != priorityVecReg[2'h2]);
endmodule

module OldestArbiterInitialReset2Case009(
    input  logic       reset,
    output logic [3:0] priority_flat,
    output logic       priority_ok
);
    reg [1:0][1:0] priorityVecReg;

    initial begin
        if (reset) begin
            priorityVecReg = '{2'h2, 2'h1};
        end
    end

    assign priority_flat = priorityVecReg;
    assign priority_ok =
        priorityVecReg[1'h0] == 2'h1
        && priorityVecReg[1'h1] == 2'h2;
endmodule

module OldestArbiterInitialReset3Case009(
    input  logic       reset,
    output logic [8:0] priority_flat,
    output logic       priority_ok
);
    reg [2:0][2:0] priorityVecReg;

    initial begin
        if (reset) begin
            priorityVecReg = '{3'h4, 3'h2, 3'h1};
        end
    end

    assign priority_flat = priorityVecReg;
    assign priority_ok =
        priorityVecReg[2'h0] == 3'h1
        && priorityVecReg[2'h1] == 3'h2
        && priorityVecReg[2'h2] == 3'h4;
endmodule
