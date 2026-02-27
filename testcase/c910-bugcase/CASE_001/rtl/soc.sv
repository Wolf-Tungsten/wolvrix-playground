module soc(
  inout [0:0] b_pad_gpio_porta
);
  apb x_apb(
    .b_pad_gpio_porta(b_pad_gpio_porta)
  );
endmodule
