# HDL-deflate
FPGA implementation of deflate (de)compress RFC 1950/1951

This design is implemented in MyHDL (www.myhdl.org) and can be translated to Verilog or VHDL.

It has been verified in Icarus, Xilinx Vivado and on a physical Xilinx device (Digilent Arty).

Usage should be clear from the test bench in test_deflate.py.

# Tunable parameters

    OBSIZE = 8192   # Size of output buffer (BRAM)
    IBSIZE = 2048   # Size of input buffer (LUT-RAM)

    CWINDOW = 32    # Search window for compression

