module apb(
  inout [0:0] b_pad_gpio_porta
);
  gpio x_gpio(
    .b_pad_gpio_porta(b_pad_gpio_porta)
  );
endmodule
