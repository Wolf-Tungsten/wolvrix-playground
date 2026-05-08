class LoadStoreTop extends Module {
  val io = IO(new Bundle {
    val reqValid = Input(Bool())
    val respReady = Output(Bool())
  })

  val writebackReg = RegInit(0.U(64.W))
  val retryFlag = RegInit(false.B)

  when(io.reqValid) {
    writebackReg := 42.U
    retryFlag := false.B
  }

  io.respReady := retryFlag
}