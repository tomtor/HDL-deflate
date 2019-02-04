# HDL-deflate
[FPGA](https://en.m.wikipedia.org/wiki/Field-programmable_gate_array) implementation of [deflate](https://en.m.wikipedia.org/wiki/DEFLATE) (de)compress RFC 1950/1951 ((g)zip / zlib)

This design is implemented in MyHDL (www.myhdl.org) and can be translated to Verilog.

It has been verified in [Icarus](http://iverilog.icarus.com/),
[Xilinx Vivado](https://www.xilinx.com/products/design-tools/vivado.html)
and on a physical Xilinx device ([Digilent Arty](https://store.digilentinc.com/arty-a7-artix-7-fpga-development-board-for-makers-and-hobbyists/)).

In addition it has been tested with [Lattice iCE40 UltraPlus](https://www.latticesemi.com/Products/FPGAandCPLD/iCE40UltraPlus)
using [IceStorm](http://www.clifford.at/icestorm/) and an
[Upduino](http://www.latticesemi.com/en/Products/DevelopmentBoardsAndKits/GnarlyGreyUPDuinoBoard).

Also on an [ECP5 board](http://www.latticesemi.com/en/Products/DevelopmentBoardsAndKits/ECP5EvaluationBoard) with [Lattice Diamond](http://www.latticesemi.com/latticediamond) on [Ubuntu 18.04](http://releases.ubuntu.com/18.04/).

Usage should be clear from the test bench in `test_deflate.py`.

# Tunable parameters

    OBSIZE = 8192   # Size of output buffer (BRAM)
                    # You need 32768 to compress ALL valid deflate streams!

    IBSIZE = 2048   # Size of input buffer (LUT-RAM)

    CWINDOW = 32    # Search window for compression

## Sliding input window

One can use a sliding window to reduce the size of the input buffer and the LUT-usage.

The minimal value is 2 * CWINDOW (64 bytes), the UnitTest in `test_deflate.py`
uses this strategy.

## Compression efficiency

By default the compressor will reduce repeated 3/4/5 byte sequences in the search window to 15 bit.
This will result in a decent compression ratio for many real life input data patterns.

At the expense of additional LUTs one can improve this by enlarging the `CWINDOW` or expanding
the matching code to include 6/7/8/9/10 byte matches. Set `MATCH10` to `True` in the top of `deflate.py`
to activate this option.

Another strategy for data sets with just a small set of used byte values would be
to use a dedicated pre-computed Huffman tree. I could add this if there is interest, but it is probably
better to use a more dense coding in your FPGA application data in the first place.

## Decompression speed

Method 0 (copy mode) 2 cycles for each output byte. Other methods from 1 (long repeated sequences)
to 4 cycles for each output byte.

## Compression speed

To reduce LUT usage the original implementation matched each slot in the search window in a dedicated clock cycle.
By setting `FAST` to `True` it will generate the logic to match the whole window in a single cycle.
The effective speed will be around 1 input byte every 3 cycles.

## Disabling functionality to save LUTs

The compress mode can be disabled by setting `COMPRESS` to `False`.

The decompress mode can be disabled by setting `DECOMPRESS` to `False`.

As an option you can disable dynamic tree decompression by setting `DYNAMIC` to `False`. 
This will save a lot of BRAM and LUTs and HDL-Deflate compressed output is always using a static tree,
but zlib will normally generate dynamic trees. Set zlib option `Z_FIXED` to generate streams with
a static tree.

In general the size of `leaves` and `d_leaves` can be reduced a lot when the maximal length of the input stream
is less than 32768. One can replace `test_data()` in `test_deflate.py` with a specific version which generates
typical test data for the intended FPGA application, and repeatedly halve the sizes of the `leaves` arrays
until the test fails.

FAST MATCH10 compress only has quite good resource usage.

LOWLUT disables some options (DYNAMIC and multi block handling) for minimal LUT usage.

## Practical considerations

In general HDL-Deflate is interesting when speed is important. When speed is not a real issue using a (soft)
CPU with zlib and dynamic RAM is probably the better approach. Especially decompression is also reasonable
fast with a CPU and HDL-Deflate needs a lot of BRAM when configured to decompress ANY deflate input stream.

Compression is another story because it is a LOT faster in hardware with the `FAST` option and uses a reasonable amount of LUTs on Xilinx. Lattice compress resource usage is bigger because it has no LUT-ram.

Decompression only mode with the LOWLUT option can be interesting because it also has a reasonable size. Its size is comparable with a soft CPU on Lattice (but it is a lot faster) and it is much smaller on Xilinx.

# FPGA validation

## Xilinx

### Default (Decompress with IBUF = 16 * CWINDOW and Compress with FAST/MATCH10)

Resource|Estimation
--------|----------
LUT	|9823
LUTRAM	|1248
FF	|2910
BRAM	|18

### Compress only and FAST and MATCH10

Resource|Estimation
--------|----------
LUT	|2854
LUTRAM	|156
FF	|760
BRAM	|8.5

### Compress only and FAST

Resource|Estimation
--------|----------
LUT	|2397
LUTRAM	|84
FF	|695
BRAM	|8.5

### Compress only and MATCH10

Resource|Estimation
--------|----------
LUT	|1191
LUTRAM	|84
FF	|385
BRAM	|1

### Decompress only

Resource|Estimation
--------|----------
LUT	|4752
LUTRAM	|48
FF	|2443
BRAM	|17.5

### Decompress only and LOWLUT

Resource|Estimation
--------|----------
LUT	|712
LUTRAM	|24
FF	|330
BRAM	|1

## Lattice ECP5 (LFE5UM5G-85F)

### Default setting

    Number of registers:   3108 out of 84255 (4%)
      PFU registers:         3108 out of 83640 (4%)
      PIO registers:            0 out of   615 (0%)
    Number of SLICEs:     12491 out of 41820 (30%)
      SLICEs as Logic/ROM:  10955 out of 41820 (26%)
      SLICEs as RAM:         1536 out of 31365 (5%)
      SLICEs as Carry:       1276 out of 41820 (3%)
    Number of LUT4s:        21678 out of 83640 (26%)
      Number used as logic LUTs:        16054
      Number used as distributed RAM:   3072

## Lattice UltraPLus

### Decompress only with LOWLUT

    Number of cells:               3312
     SB_CARRY                      511
     SB_DFF                         41
     SB_DFFE                       302
     SB_DFFESR                      33
     SB_DFFESS                      10
     SB_LUT4                      2412
     SB_RAM40_4K                     3

### Compress

    Number of cells                6796
     SB_CARRY                      917
     SB_DFF                         43
     SB_DFFE                       794
     SB_DFFESR                      49
     SB_DFFESS                       6
     SB_LUT4                      4986

## Speed

The Vivado timing report fails at 100Mhz for FAST/MATCH10, but the test bench runs fine on my Arty at 100Mhz.
Non FAST passes timing constraints for 100 Mhz.

# Future Improvements (when there is interest)

* ~~Reduce cell usage: Try to fit in a Lattice ultra plus 5k. Because these devices have no LUT-ram the input buffer must be rewritten to use BRAM. This will reduce the cell usage.~~ Done for decompress.
* ~~Improve speed from current 80Mhz to 100Mhz~~
* ~~Improve compression performance~~
* Handle compress input streams < 4 bytes
