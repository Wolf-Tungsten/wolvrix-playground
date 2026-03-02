module sim_top #(
  parameter integer SLAVE = 2
) (
  input  wire [SLAVE:0]           slv_pready_vld,
  input  wire [SLAVE*32-1:0]      mst_prdata,
  output wire [(SLAVE+1)*32-1:0]  slv_pready_data_pre
);

  assign slv_pready_data_pre[31:0] = 32'b0;

  genvar k;
  generate
    for (k = 0; k < SLAVE; k = k + 1) begin: MASTER_PENABLE_REG
      assign slv_pready_data_pre[(k+2)*32-1:(k+1)*32] =
          ({32{slv_pready_vld[k]}} & mst_prdata[(k+1)*32-1:k*32])
        | slv_pready_data_pre[(k+1)*32-1:k*32];
    end
  endgenerate

endmodule
