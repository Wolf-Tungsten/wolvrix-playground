module sim_top(
  input  I,
  input  CE,
  output O
);
  BUFGCE u_bufgce(
    .I(I),
    .CE(CE),
    .O(O)
  );
endmodule
