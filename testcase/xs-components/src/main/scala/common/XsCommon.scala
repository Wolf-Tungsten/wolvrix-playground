package xscomponents

import chisel3._
import chisel3.util.Cat

object XsCommon {
  def rotl(x: UInt, n: Int): UInt = Cat(x(63 - n, 0), x(63, 64 - n))
  def rotr(x: UInt, n: Int): UInt = Cat(x(n - 1, 0), x(63, n))

  def mix64(a: UInt, b: UInt, salt: Int): UInt = {
    val x = a ^ rotl(b, (salt % 31) + 1) ^ (BigInt("9e3779b97f4a7c15", 16) + salt).U(64.W)
    val y = x + rotr(a ^ b, (salt % 17) + 1)
    y ^ rotl(y, (salt % 23) + 1)
  }

  def fold(values: Seq[UInt]): UInt = {
    var acc = values.head
    for ((value, idx) <- values.tail.zipWithIndex) {
      acc = mix64(acc, value, idx + 1)
    }
    acc
  }
}
