// CASE_025: minimal reproducer of the XS latch-based integrated clock gate
// (verbatim shape from build/xs/rtl/rtl/ClockGate.sv).
module ClockGate (
  input  wire TE,
  input  wire E,
  input  wire CK,
  output wire Q
);
  reg EN;
  always_latch begin
    if(!CK) EN = TE | E;
  end
  assign Q = CK & EN;
endmodule
