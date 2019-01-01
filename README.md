# HDL-deflate
FPGA implementation of deflate (de)compress RFC 1950/1951

This design is implemented in MyHDL (www.myhdl.org) and can be translated to Verilog or VHDL.

It has been verified in Icarus, Xilinx Vivado and on a physical Xilinx device (Digilent Arty).

Usage should be clear from the test bench in `test_deflate.py`.

# Tunable parameters

    OBSIZE = 8192   # Size of output buffer (BRAM)
                    # You need 32768 to compress ALL valid deflate streams!

    IBSIZE = 2048   # Size of input buffer (LUT-RAM)

    CWINDOW = 32    # Search window for compression

## Compression efficiency

One can use a sliding window to reduce the size of the input buffer and the LUT-usage.

The minimal value is 2 * CWINDOW (64 bytes), the UnitTest in `test_deflate.py`
uses this strategy.

By default the compressor will reduce repeated 3/4/5 byte sequences in the search window to 15 bit.
This will result in a decent compression ratio for many real life input data patterns.

At the expense of additional LUTs one can improve this by enlarging the `CWINDOW` or expanding
the matching code to include 6/7/8/9/10 byte matches. Set `MATCH10` to `True` in the top of `deflate.py`
to activate this option.

Another strategy for data sets with just a small set of used byte values would be
to use a dedicated pre-computed Huffman tree. I could add this if there is interest, but it is probably
better to use a more dense coding in your FPGA application data in the first place.

## Compression speed

To reduce LUT usage the original implementation matched each slot in the search window in a dedicated clock cycle.
By setting `FAST` to `True` it will generate the logic to match the whole window in a single cycle.
The effective speed will be around 1 input byte every two cycles.

## Disabling functionality to save LUTs

The compress mode can be disabled by setting `COMPRESS` to `False`.

The decompress mode can be disabled by setting `DECOMPRESS` to `False`.

As an option you can disable dynamic tree decompression by setting `DYNAMIC` to `False`. 
This will save a lot of LUT-ram and HDL-Deflate compressed output is always using a static tree,
but zlib will normally generate dynamic trees. Set zlib option `Z_FIXED` to generate streams with
a static tree.

In general the size of `leaves` and `d_leaves` can be reduced a lot when the maximal length of the input stream
is less than 32768. One can replace `test_data()` in `test_deflate.py` with a specific version which generates
typical test data for the intended FPGA application, and repeatedly halve the sizes of the `leaves` arrays
until the test fails.

FAST MATCH10 compress only has quite good resource usage.

## Practical considerations

In general HDL-Deflate is interesting when speed is important. When speed is not a real issue using a (soft)
CPU with zlib is probably the better approach. Especially decompression is also quite fast with a CPU and HDL-Deflate
needs a lot of LUTs when configured to decompress ANY deflate input stream. Compression is another story because it
is a LOT faster in hardware with the `FAST` option and uses a reasonable amount of LUTs.

# FPGA validation

## Minimal with smaller leaves arrays

Resource|Estimation
--------|----------
LUT	|7116
LUTRAM	|800
FF	|2265
BRAM	|4

## Compress False and smaller leaves arrays

Resource|Estimation
--------|----------
LUT	|5769
LUTRAM	|512
FF	|2169
BRAM	|4

## Decompress False and FAST and MATCH10

Resource|Estimation
--------|----------
LUT	|5118
LUTRAM	|84
FF	|1577
BRAM	|2

## FAST

Resource|Estimation
--------|----------
LUT	|8246
LUTRAM	|704
FF	|2520
BRAM	|4

## FAST and MATCH10

Resource|Estimation
--------|----------
LUT	|11888
LUTRAM	|536
FF	|3308
BRAM	|4

## Speed

The Vivado timing report fails at 100Mhz, but the test bench runs fine on my Arty at 100Mhz.

# Future Improvements (when there is interest)

* ~~Reduce LUT usage~~
* ~~Improve speed from current 80Mhz to 100Mhz~~
* ~~Improve compression performance~~
