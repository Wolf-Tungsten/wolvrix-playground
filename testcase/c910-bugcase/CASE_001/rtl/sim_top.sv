module sim_top;
  wire [0:0] b_pad_gpio_porta;

  soc x_soc(
    .b_pad_gpio_porta(b_pad_gpio_porta)
  );
endmodule
