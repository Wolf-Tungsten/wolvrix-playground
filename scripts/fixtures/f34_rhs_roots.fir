FIRRTL version 6.0.0
circuit RhsRoots :
  module RhsRoots :
    input clock : Clock
    input a : UInt<256>
    input b : UInt<256>
    input elements : UInt<8>[2]
    output aliasOut : UInt<256>
    output fullOut : UInt<256>
    output partialOut : UInt<8>
    output indexedOut : UInt<8>
    output signedOut : SInt<256>
    output stateLow : UInt<128>
    output stateHigh : UInt<128>
    node source = xor(a, b)
    node namedAlias = source
    node fullBits = bits(namedAlias, 255, 0)
    node partialBits = bits(namedAlias, 15, 8)
    node indexed = elements[1]
    node signedView = asSInt(namedAlias)
    reg state : UInt<256>, clock
    connect state, source
    connect aliasOut, namedAlias
    connect fullOut, fullBits
    connect partialOut, partialBits
    connect indexedOut, indexed
    connect signedOut, signedView
    connect stateLow, bits(state, 127, 0)
    connect stateHigh, bits(state, 255, 128)
