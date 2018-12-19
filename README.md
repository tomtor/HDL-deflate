# HDL-deflate
FPGA implementation of deflate (de)compress RFC 1950/1951

This design is implemented in MyHDL (www.myhdl.org) and can be translated to Verilog or VHDL.

It has been verified in Icarus, Xilinx Vivado and on a physical Xilinx device (Digilent Arty).

Usage should be clear from the test bench in `test_deflate.py`.

# Tunable parameters

    OBSIZE = 8192   # Size of output buffer (BRAM)
    IBSIZE = 2048   # Size of input buffer (LUT-RAM)

    CWINDOW = 32    # Search window for compression

One can use a sliding window to reduce the size of the input buffer and the LUT-usage.

The optimal value is 4 * CWINDOW (128 bytes), the first decompression in the UnitTest in `test_deflate.py`
uses this strategy.

By default the compressor will reduce repeated 3/4/5 byte sequences in the search window to 15 bit.
This will result in a decent compression ratio for many real life input data patterns.

At the expense of additional LUTs one can improve this by enlarging the `CWINDOW` or expanding
the matching code to include 6/7/8/9/10 byte matches. This code is commented out in FSM state
`d_state.SEARCH` around line 600 in `deflate.py`.

Another strategy for data sets with just a small set of used byte values would be
to use a dedicated pre-computed Huffman tree. I could add this if there is interest, but it is probably
better to use a more dense coding in your FPGA application data in the first place.

# FPGA validation

Resource|Estimation
--------|----------
LUT	|7559
LUTRAM	|776
FF	|2862
BRAM	|4

# Future Improvements (when there is interest)

* Reduce LUT usage
* Improve speed from current 80Mhz to 100Mhz
* Improve compression performance
