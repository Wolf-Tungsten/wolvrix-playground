// CASE_025: minimal reproducer for the merged-supernode clock-gate activation
// deadlock (M5d-8 first failure, XiangShan DCache.sv:2015).
//
// Shape under test (mirrors SRAMTemplate/array_256x86 + MbistClockGateCell):
//   - a latch-based ICG: EN latches the enable while CK is low, Q = CK & EN;
//   - the enable E is a combinational OR of the request valids;
//   - macro registers (raddr_d/ren_d/rmode_d/Memory) are clocked by Q;
//   - ren_d's next value *is* E, so the combinational E producer and the
//     Q-gated ren_d write merge into one event-gated supernode. That
//     supernode then deadlocks: it fires only when Q's posedge event fires,
//     but Q never rises because E is never published.
//
// Pre-fix grhsim-ir (merged supernodes): resp_data stays 0 forever (the macro
// registers never update). Verilator reference and 1-op-supernode builds work.
module GatedSram (
  input  wire        clock,
  input  wire        reset,
  input  wire        io_req_read,
  input  wire        io_req_write,
  input  wire [7:0]  io_req_addr,
  input  wire [15:0] io_req_wdata,
  output wire [15:0] io_resp_data
);
  wire en = io_req_read | io_req_write;
  wire gclk;
  ClockGate cg (
    .TE (1'b0),
    .E  (en),
    .CK (clock),
    .Q  (gclk)
  );

  reg [15:0] Memory [0:255];
  reg [7:0]  raddr_d;
  reg        ren_d;
  reg        rmode_d;
  always @(posedge gclk) begin
    raddr_d <= io_req_addr;
    ren_d   <= io_req_read | io_req_write;
    rmode_d <= io_req_write;
    if (io_req_write)
      Memory[io_req_addr] <= io_req_wdata;
  end

  assign io_resp_data = ren_d & ~rmode_d ? Memory[raddr_d] : 16'h0;

  // reset is intentionally unused (the XS macro registers have no reset);
  // it is kept on the interface so the testbench reset sequence stays honest.
  wire unused = &{1'b0, reset};
endmodule
