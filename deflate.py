"""
MyHDL FPGA Deflate (de)compressor, see RFC 1950/1951

Copyright (C) 2018/2019 by Tom Vijlbrief

See: https://github.com/tomtor

This MyHDL FPGA implementation is partially inspired by the C++ implementation
of a decoder from https://create.stephan-brumme.com/deflate-decoder

"""

from math import log2

from myhdl import always, block, Signal, intbv, Error, ResetSignal, \
    enum, always_comb, concat, ConcatSignal, modbv

IDLE, RESET, WRITE, READ, STARTC, STARTD = range(6)

# Trade speed and functionality (DYNAMIC trees) for LUTs
LOWLUT = True
LOWLUT = False

# set options manually
COMPRESS = False
COMPRESS = True

DECOMPRESS = True
DECOMPRESS = False

DYNAMIC = True
DYNAMIC = False

MATCH10 = False
MATCH10 = True

FAST = False
FAST = True

ONEBLOCK = True
ONEBLOCK = False

if LOWLUT:
    if COMPRESS:
        # raise Error("compress cannot be combined with LOWLUT")
        pass
    DYNAMIC = False
    MATCH10 = False
    FAST = False
    ONEBLOCK = True

if not COMPRESS:
    MATCH10 = False
    FAST = False

# Search window for compression
if FAST or LOWLUT:
    CWINDOW = 32
else:
    CWINDOW = 256

OBSIZE = 32768  # Size of output buffer for ANY input (BRAM)
OBSIZE = 512    # Minimal size of output buffer (BRAM)

# Size of input buffer (LUT-RAM)
if FAST:
    IBSIZE = 16 * CWINDOW  # This size gives dynamic tree for testbench
else:
    IBSIZE = 2 * CWINDOW   # Minimal window

print("IBSIZE", IBSIZE)

# Size of progress and I/O counters
if LOWLUT:
    LMAX = 16
else:
    LMAX = 24

# =============== End of user settable parameters ==================

if OBSIZE > IBSIZE:
    LBSIZE = int(log2(OBSIZE))
else:
    LBSIZE = int(log2(IBSIZE))

LIBSIZE = int(log2(IBSIZE))
LOBSIZE = int(log2(OBSIZE))

IBS = (1 << LIBSIZE) - 1
OBS = (1 << LOBSIZE) - 1

d_state = enum('IDLE', 'HEADER', 'BL', 'READBL', 'REPEAT', 'DISTTREE', 'INIT3',
               'HF1', 'HF1INIT', 'HF2', 'HF3', 'HF4', 'HF4_2', 'HF4_3',
               'STATIC', 'D_NEXT', 'D_NEXT_2', 'D_INFLATE', 'SPREAD', 'NEXT',
               'INFLATE', 'COPY', 'CSTATIC', 'SEARCH', 'SEARCH10', 'SEARCHF',
               'DISTANCE', 'CHECKSUM')  # , encoding='one_hot')

CodeLengthOrder = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14,
                   1, 15)

CopyLength = (3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35,
              43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258)

ExtraLengthBits = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
                   3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0)

CopyDistance = (1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193,
                257, 385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193,
                12289, 16385, 24577)

ExtraDistanceBits = (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)

out_codes = (
    0x00c, 0x08c, 0x04c, 0x0cc, 0x02c, 0x0ac, 0x06c, 0x0ec,
    0x01c, 0x09c, 0x05c, 0x0dc, 0x03c, 0x0bc, 0x07c, 0x0fc,
    0x002, 0x082, 0x042, 0x0c2, 0x022, 0x0a2, 0x062, 0x0e2,
    0x012, 0x092, 0x052, 0x0d2, 0x032, 0x0b2, 0x072, 0x0f2,
    0x00a, 0x08a, 0x04a, 0x0ca, 0x02a, 0x0aa, 0x06a, 0x0ea,
    0x01a, 0x09a, 0x05a, 0x0da, 0x03a, 0x0ba, 0x07a, 0x0fa,
    0x006, 0x086, 0x046, 0x0c6, 0x026, 0x0a6, 0x066, 0x0e6,
    0x016, 0x096, 0x056, 0x0d6, 0x036, 0x0b6, 0x076, 0x0f6,
    0x00e, 0x08e, 0x04e, 0x0ce, 0x02e, 0x0ae, 0x06e, 0x0ee,
    0x01e, 0x09e, 0x05e, 0x0de, 0x03e, 0x0be, 0x07e, 0x0fe,
    0x001, 0x081, 0x041, 0x0c1, 0x021, 0x0a1, 0x061, 0x0e1,
    0x011, 0x091, 0x051, 0x0d1, 0x031, 0x0b1, 0x071, 0x0f1,
    0x009, 0x089, 0x049, 0x0c9, 0x029, 0x0a9, 0x069, 0x0e9,
    0x019, 0x099, 0x059, 0x0d9, 0x039, 0x0b9, 0x079, 0x0f9,
    0x005, 0x085, 0x045, 0x0c5, 0x025, 0x0a5, 0x065, 0x0e5,
    0x015, 0x095, 0x055, 0x0d5, 0x035, 0x0b5, 0x075, 0x0f5,
    0x00d, 0x08d, 0x04d, 0x0cd, 0x02d, 0x0ad, 0x06d, 0x0ed,
    0x01d, 0x09d, 0x05d, 0x0dd, 0x03d, 0x0bd, 0x07d, 0x0fd,
    0x013, 0x113, 0x093, 0x193, 0x053, 0x153, 0x0d3, 0x1d3,
    0x033, 0x133, 0x0b3, 0x1b3, 0x073, 0x173, 0x0f3, 0x1f3,
    0x00b, 0x10b, 0x08b, 0x18b, 0x04b, 0x14b, 0x0cb, 0x1cb,
    0x02b, 0x12b, 0x0ab, 0x1ab, 0x06b, 0x16b, 0x0eb, 0x1eb,
    0x01b, 0x11b, 0x09b, 0x19b, 0x05b, 0x15b, 0x0db, 0x1db,
    0x03b, 0x13b, 0x0bb, 0x1bb, 0x07b, 0x17b, 0x0fb, 0x1fb,
    0x007, 0x107, 0x087, 0x187, 0x047, 0x147, 0x0c7, 0x1c7,
    0x027, 0x127, 0x0a7, 0x1a7, 0x067, 0x167, 0x0e7, 0x1e7,
    0x017, 0x117, 0x097, 0x197, 0x057, 0x157, 0x0d7, 0x1d7,
    0x037, 0x137, 0x0b7, 0x1b7, 0x077, 0x177, 0x0f7, 0x1f7,
    0x00f, 0x10f, 0x08f, 0x18f, 0x04f, 0x14f, 0x0cf, 0x1cf,
    0x02f, 0x12f, 0x0af, 0x1af, 0x06f, 0x16f, 0x0ef, 0x1ef,
    0x01f, 0x11f, 0x09f, 0x19f, 0x05f, 0x15f, 0x0df, 0x1df,
    0x03f, 0x13f, 0x0bf, 0x1bf, 0x07f, 0x17f, 0x0ff, 0x1ff,
    0x000, 0x040, 0x020, 0x060, 0x010, 0x050, 0x030, 0x070,
    0x008, 0x048, 0x028, 0x068, 0x018, 0x058, 0x038, 0x078,
    0x004, 0x044, 0x024, 0x064, 0x014, 0x054, 0x034, 0x074,
    0x003, 0x083, 0x043, 0x0c3, 0x023, 0x0a3, 0x063, 0x0e3
)

stat_leaves = (
    4103, 1288, 264, 4488, 4359, 1800, 776, 3081,
    4231, 1544, 520, 2569, 8, 2056, 1032, 3593,
    4167, 1416, 392, 2313, 4423, 1928, 904, 3337,
    4295, 1672, 648, 2825, 136, 2184, 1160, 3849,
    4135, 1352, 328, 4552, 4391, 1864, 840, 3209,
    4263, 1608, 584, 2697, 72, 2120, 1096, 3721,
    4199, 1480, 456, 2441, 4455, 1992, 968, 3465,
    4327, 1736, 712, 2953, 200, 2248, 1224, 3977,
    4119, 1320, 296, 4520, 4375, 1832, 808, 3145,
    4247, 1576, 552, 2633, 40, 2088, 1064, 3657,
    4183, 1448, 424, 2377, 4439, 1960, 936, 3401,
    4311, 1704, 680, 2889, 168, 2216, 1192, 3913,
    4151, 1384, 360, 4584, 4407, 1896, 872, 3273,
    4279, 1640, 616, 2761, 104, 2152, 1128, 3785,
    4215, 1512, 488, 2505, 4471, 2024, 1000, 3529,
    4343, 1768, 744, 3017, 232, 2280, 1256, 4041,
    4103, 1304, 280, 4504, 4359, 1816, 792, 3113,
    4231, 1560, 536, 2601, 24, 2072, 1048, 3625,
    4167, 1432, 408, 2345, 4423, 1944, 920, 3369,
    4295, 1688, 664, 2857, 152, 2200, 1176, 3881,
    4135, 1368, 344, 4568, 4391, 1880, 856, 3241,
    4263, 1624, 600, 2729, 88, 2136, 1112, 3753,
    4199, 1496, 472, 2473, 4455, 2008, 984, 3497,
    4327, 1752, 728, 2985, 216, 2264, 1240, 4009,
    4119, 1336, 312, 4536, 4375, 1848, 824, 3177,
    4247, 1592, 568, 2665, 56, 2104, 1080, 3689,
    4183, 1464, 440, 2409, 4439, 1976, 952, 3433,
    4311, 1720, 696, 2921, 184, 2232, 1208, 3945,
    4151, 1400, 376, 4600, 4407, 1912, 888, 3305,
    4279, 1656, 632, 2793, 120, 2168, 1144, 3817,
    4215, 1528, 504, 2537, 4471, 2040, 1016, 3561,
    4343, 1784, 760, 3049, 248, 2296, 1272, 4073,
    4103, 1288, 264, 4488, 4359, 1800, 776, 3097,
    4231, 1544, 520, 2585, 8, 2056, 1032, 3609,
    4167, 1416, 392, 2329, 4423, 1928, 904, 3353,
    4295, 1672, 648, 2841, 136, 2184, 1160, 3865,
    4135, 1352, 328, 4552, 4391, 1864, 840, 3225,
    4263, 1608, 584, 2713, 72, 2120, 1096, 3737,
    4199, 1480, 456, 2457, 4455, 1992, 968, 3481,
    4327, 1736, 712, 2969, 200, 2248, 1224, 3993,
    4119, 1320, 296, 4520, 4375, 1832, 808, 3161,
    4247, 1576, 552, 2649, 40, 2088, 1064, 3673,
    4183, 1448, 424, 2393, 4439, 1960, 936, 3417,
    4311, 1704, 680, 2905, 168, 2216, 1192, 3929,
    4151, 1384, 360, 4584, 4407, 1896, 872, 3289,
    4279, 1640, 616, 2777, 104, 2152, 1128, 3801,
    4215, 1512, 488, 2521, 4471, 2024, 1000, 3545,
    4343, 1768, 744, 3033, 232, 2280, 1256, 4057,
    4103, 1304, 280, 4504, 4359, 1816, 792, 3129,
    4231, 1560, 536, 2617, 24, 2072, 1048, 3641,
    4167, 1432, 408, 2361, 4423, 1944, 920, 3385,
    4295, 1688, 664, 2873, 152, 2200, 1176, 3897,
    4135, 1368, 344, 4568, 4391, 1880, 856, 3257,
    4263, 1624, 600, 2745, 88, 2136, 1112, 3769,
    4199, 1496, 472, 2489, 4455, 2008, 984, 3513,
    4327, 1752, 728, 3001, 216, 2264, 1240, 4025,
    4119, 1336, 312, 4536, 4375, 1848, 824, 3193,
    4247, 1592, 568, 2681, 56, 2104, 1080, 3705,
    4183, 1464, 440, 2425, 4439, 1976, 952, 3449,
    4311, 1720, 696, 2937, 184, 2232, 1208, 3961,
    4151, 1400, 376, 0, 4407, 1912, 888, 3321,
    4279, 1656, 632, 2809, 120, 2168, 1144, 3833,
    4215, 1528, 504, 2553, 4471, 2040, 1016, 3577,
    4343, 1784, 760, 3065, 248, 2296, 1272, 4089
)


@block
def deflate(i_mode, o_done, i_data, o_iprogress, o_oprogress, o_byte,
            i_waddr, i_raddr, clk, reset):

    """ Deflate (de)compress

    Ports:

    """

    iram = [Signal(intbv()[8:]) for _ in range(IBSIZE)]
    oram = [Signal(intbv()[8:]) for _ in range(OBSIZE)]

    oaddr = Signal(modbv()[LOBSIZE:])
    oraddr = Signal(modbv()[LOBSIZE:])
    obyte = Signal(intbv()[8:])
    orbyte = Signal(intbv()[8:])
    irbyte = Signal(intbv()[8:])

    # iraddr = Signal(modbv()[LIBSIZE:])

    isize = Signal(intbv()[LMAX:])
    state = Signal(d_state.IDLE)
    method = Signal(intbv()[3:])
    prev_method = Signal(intbv()[2:])
    final = Signal(bool())

    do_compress = Signal(bool())

    numLiterals = Signal(intbv()[9:])
    numDistance = Signal(intbv()[6:])
    numCodeLength = Signal(intbv()[9:])
    b_numCodeLength = Signal(intbv()[9:])

    CodeLengths = 19
    if DYNAMIC:
        MaxCodeLength = 15
        InstantMaxBit = 10
    else:
        MaxCodeLength = 9
        InstantMaxBit = 9

    EndOfBlock = 256
    MaxBitLength = 288
    InvalidToken = 300

    CODEBITS = MaxCodeLength
    BITBITS = 4

    codeLength = [Signal(intbv()[4:]) for _ in range(MaxBitLength+32)]
    bits = Signal(intbv()[4:])
    bitLengthCount = [Signal(intbv()[9:]) for _ in range(MaxCodeLength+1)]
    nextCode = [Signal(intbv()[CODEBITS+1:]) for _ in range(MaxCodeLength+1)]
    reverse = Signal(modbv()[CODEBITS:])
    distanceLength = [Signal(intbv()[4:]) for _ in range(32)]

    if DECOMPRESS:
        if DYNAMIC:
            leaves = [Signal(intbv()[CODEBITS + BITBITS:])
                      for _ in range(32768)]
            d_leaves = [Signal(intbv()[CODEBITS + BITBITS:])
                        for _ in range(4096)]
        else:
            leaves = [Signal(bool())]
            d_leaves = [Signal(bool())]
    else:
        leaves = [Signal(bool())]
        d_leaves = [Signal(bool())]
    stat_leaf = Signal(intbv()[CODEBITS + BITBITS:])

    lwaddr = Signal(intbv()[MaxCodeLength:])
    lraddr = Signal(intbv()[MaxCodeLength:])
    rleaf = Signal(intbv()[CODEBITS + BITBITS:])
    wleaf = Signal(intbv()[CODEBITS + BITBITS:])

    dlwaddr = Signal(intbv()[MaxCodeLength:])
    dlraddr = Signal(intbv()[MaxCodeLength:])
    drleaf = Signal(intbv()[CODEBITS + BITBITS:])
    dwleaf = Signal(intbv()[CODEBITS + BITBITS:])

    leaf = Signal(intbv()[CODEBITS + BITBITS:])

    minBits = Signal(intbv()[5:])
    maxBits = Signal(intbv()[5:])
    d_maxBits = Signal(intbv()[5:])
    instantMaxBit = Signal(intbv()[InstantMaxBit:])
    d_instantMaxBit = Signal(intbv()[InstantMaxBit:])
    instantMask = Signal(intbv()[MaxCodeLength:])
    d_instantMask = Signal(intbv()[MaxCodeLength:])
    spread = Signal(intbv()[InstantMaxBit:])
    step = Signal(intbv()[InstantMaxBit:])

    static = Signal(bool())

    code = Signal(intbv()[CODEBITS:])
    lastToken = Signal(intbv()[9:])
    howOften = Signal(intbv()[9:])

    cur_i = Signal(intbv()[LMAX:])
    spread_i = Signal(intbv()[9:])
    cur_HF1 = Signal(intbv()[MaxCodeLength+1:])
    cur_static = Signal(intbv()[9:])
    cur_cstatic = Signal(intbv()[4:])
    cur_search = Signal(intbv(min=-1, max=1 << LMAX))
    more = Signal(intbv()[4:])
    cur_dist = Signal(intbv(min=-CWINDOW, max=IBSIZE))
    cur_next = Signal(intbv()[5:])

    do_init = Signal(bool())

    length = Signal(modbv()[LOBSIZE:])
    mlength = Signal(modbv()[4:])
    dlength = Signal(modbv()[10:])
    offset = Signal(intbv()[LOBSIZE:])
    off1 = Signal(bool())
    off2 = Signal(bool())

    di = Signal(modbv()[LMAX:])
    old_di = Signal(intbv()[LMAX:])
    dio = Signal(intbv()[3:])
    do = Signal(intbv()[LMAX:])
    doo = Signal(intbv()[3:])

    b1 = Signal(intbv()[8:])
    b2 = Signal(intbv()[8:])
    b3 = Signal(intbv()[8:])
    b4 = Signal(intbv()[8:])
    b5 = Signal(intbv()[8:])

    b41 = ConcatSignal(b4, b3, b2, b1)
    b41._markUsed()

    b14 = ConcatSignal(b1, b2, b3, b4)
    b14._markUsed()
    b15 = ConcatSignal(b1, b2, b3, b4, b5)

    b6 = Signal(intbv()[8:])
    b7 = Signal(intbv()[8:])
    b8 = Signal(intbv()[8:])
    b9 = Signal(intbv()[8:])
    b10 = Signal(intbv()[8:])
    if MATCH10:
        b110 = ConcatSignal(b1, b2, b3, b4, b5, b6, b7, b8, b9, b10)
        b110._markUsed()
    else:
        b110 = Signal(bool())

    fcount = Signal(intbv(min=0, max=15))
    rcount = Signal(intbv(min=0, max=15))

    nb = Signal(bool())

    filled = Signal(bool())
    first_block = Signal(bool())

    ob1 = Signal(intbv()[8:])
    outcarry = Signal(intbv()[9:])
    outcarrybits = Signal(intbv()[4:])
    copy1 = Signal(intbv()[8:])
    copy2 = Signal(intbv()[8:])
    flush = Signal(bool())

    adler1 = Signal(intbv()[16:])
    adler2 = Signal(intbv()[16:])
    ladler1 = Signal(intbv()[16:])

    @always(clk.posedge)
    def bramwrite():
        oram[oaddr].next = obyte
        if DYNAMIC:
            leaves[lwaddr].next = wleaf
        d_leaves[dlwaddr].next = dwleaf

    @always(clk.posedge)
    def bramread():
        orbyte.next = oram[oraddr]
        drleaf.next = d_leaves[dlraddr]

    if DYNAMIC:
        @always(clk.posedge)
        def rleafread():
            rleaf.next = leaves[lraddr]

    if LOWLUT:
        @always(clk.posedge)
        def iramread():
            irbyte.next = iram[di + rcount & IBS]

    @block
    def matcher3(o_m, mi):
        @always_comb
        def logic():
            o_m.next = (((concat(cwindow, b1, b2) >> (8 * mi)) & 0xFFFFFF)
                        == (b14 >> 8))
        return logic

    if FAST:
        smatch = [Signal(bool()) for _ in range(CWINDOW)]
        cwindow = Signal(modbv()[8 * CWINDOW:])
        matchers = [matcher3(smatch[mi], mi) for mi in range(CWINDOW)]
    else:
        cwindow = Signal(bool())
        smatch = [Signal(bool())]

    @always(clk.posedge)
    def fill_buf():
        if not reset:
            print("FILL RESET")
            nb.next = 0
        else:
            if isize < 4:
                nb.next = 0
                if FAST:
                    old_di.next = 0
            elif i_mode == STARTC or i_mode == STARTD:
                nb.next = 0
                if FAST:
                    old_di.next = 0
            else:
                """
                if do_compress:
                    print("FILL", di, old_di, nb, b1, b2, b3, b4)
                """
                if FAST:
                    shift = (di - old_di) * 8
                    """
                    if shift != 0:
                        print("shift", shift, cwindow, b1, b2, b3, b4)
                    """
                    if MATCH10:
                        cwindow.next = ((cwindow << shift)
                                        | (b110 >> (80 - shift)))
                    else:
                        cwindow.next = ((cwindow << shift)
                                        | (b15 >> (40 - shift)))

                # print("old di fcount", old_di, di, fcount)
                # print("irbyte read", di, fcount, isize, irbyte)

                if not LOWLUT:
                    b1.next = iram[di & IBS]
                    b2.next = iram[di+1 & IBS]
                    b3.next = iram[di+2 & IBS]

                if old_di == di:
                    """
                    if fcount < 9:
                        print("fcount", fcount)
                    """
                    if LOWLUT:
                        if fcount >= 4:
                            nb.next = True
                    else:
                        nb.next = True

                    rb = irbyte
                    if LOWLUT:
                        fcount.next = rcount
                        if rcount == 1:
                            b1.next = rb
                        elif rcount == 2:
                            b2.next = rb
                        elif rcount == 3:
                            b3.next = rb
                        elif rcount == 4:
                            b4.next = rb
                        elif rcount == 5:
                            b5.next = rb
                        if rcount < 5:
                            rcount.next = rcount + 1
                    elif fcount == 4:
                        b5.next = rb
                        fcount.next = 5
                    elif MATCH10:
                        if fcount == 5:
                            b6.next = rb
                        elif fcount == 6:
                            b7.next = rb
                        elif fcount == 7:
                            b8.next = rb
                        elif fcount == 8:
                            b9.next = rb
                        elif fcount == 9:
                            b10.next = rb
                        if fcount < 10:
                            fcount.next = fcount + 1
                else:
                    # print("fcount set", fcount)
                    if LOWLUT:
                        rcount.next = 0
                        fcount.next = 0
                    else:
                        fcount.next = 4
                        b4.next = iram[di+3 & IBS]

                old_di.next = di

    def get4(boffset, width):
        return (b41 >> (dio + boffset)) & ((1 << width) - 1)
        # return b41[dio + boffset + width: dio + boffset]

    def adv(width):
        if not DECOMPRESS:
            raise Error("?")
        # print("adv", width, di, dio, do, doo)
        nshift = ((dio + width) >> 3)
        # print("nshift: ", nshift)

        o_iprogress.next = di
        dio.next = (dio + width) & 0x7
        di.next = di + nshift

        if nshift != 0:
            filled.next = False

    def put(d, width):
        if width > 9:
            raise Error("width > 9")
        if d > ((1 << width) - 1):
            raise Error("too big")
        # print("put:", d, width, do, doo, ob1, (ob1 | (d << doo)))
        obyte.next = (ob1 | (d << doo)) & 0xFF
        oaddr.next = do

        # print("put_adv:", d, width, do, doo, di, dio)
        pshift = (doo + width) > 8
        # print("pshift: ", pshift)
        if pshift:
            carry = width - (8 - doo)
            # print("carry:", carry, d >> (8 - carry))
            ob1.next = d >> (width - carry)
        else:
            # print("put_adv:", ob1, d, doo)
            ob1.next = ob1 | (d << doo)
            # print("ob1.next", ob1 | (d << doo))
        do.next = do + pshift
        o_oprogress.next = do + pshift
        doo_next = (doo + width) & 0x7
        if doo_next == 0:
            flush.next = True
        doo.next = doo_next

    def do_flush():
        # print("FLUSH")
        flush.next = False
        ob1.next = 0
        o_oprogress.next = do + 1
        do.next = do + 1

    def rev_bits(b, nb):
        if b >= 1 << nb:
            raise Error("too few bits")
            print("too few bits")
        if nb > 15:
            raise Error("nb too large")
        r = (((b >> 14) & 0x1) << 0) | (((b >> 13) & 0x1) << 1) | \
            (((b >> 12) & 0x1) << 2) | (((b >> 11) & 0x1) << 3) | \
            (((b >> 10) & 0x1) << 4) | (((b >> 9) & 0x1) << 5) | \
            (((b >> 8) & 0x1) << 6) | (((b >> 7) & 0x1) << 7) | \
            (((b >> 6) & 0x1) << 8) | (((b >> 5) & 0x1) << 9) | \
            (((b >> 4) & 0x1) << 10) | (((b >> 3) & 0x1) << 11) | \
            (((b >> 2) & 0x1) << 12) | (((b >> 1) & 0x1) << 13) | \
            (((b >> 0) & 0x1) << 14)
        r >>= (15 - nb)
        return r

    def makeLeaf(lcode, lbits):
        if lcode >= 1 << CODEBITS:
            raise Error("code too big")
        if lbits >= 1 << BITBITS:
            raise Error("bits too big")
        return (lcode << BITBITS) | lbits

    def get_bits(aleaf):
        return aleaf & ((1 << BITBITS) - 1)

    def get_code(aleaf):
        return (aleaf >> BITBITS)  # & ((1 << CODEBITS) - 1)

    @always(clk.posedge)
    def io_logic():
        o_byte.next = oram[i_raddr & OBS]
        if i_mode == WRITE:
            # print("WRITE:", i_addr, i_data)
            iram[i_waddr & IBS].next = i_data
            isize.next = i_waddr

    @always(clk.posedge)
    def logic():
        if not reset:
            print("DEFLATE RESET")
            state.next = d_state.IDLE
            o_done.next = False
            # prev_method.next = 3  # Illegal value
        else:

            if state == d_state.IDLE:

                if COMPRESS and i_mode == STARTC:

                    print("STARTC")
                    do_compress.next = True
                    # method.next = 1
                    o_done.next = False
                    o_iprogress.next = 0
                    o_oprogress.next = 0
                    di.next = 0
                    dio.next = 0
                    do.next = 0
                    doo.next = 0
                    filled.next = True
                    cur_static.next = 0
                    cur_cstatic.next = 0
                    state.next = d_state.STATIC

                elif DECOMPRESS and i_mode == STARTD:

                    maxBits.next = 9
                    instantMaxBit.next = 9
                    prev_method.next = 3
                    do_compress.next = False
                    o_done.next = False
                    o_iprogress.next = 0
                    o_oprogress.next = 0
                    di.next = 2
                    dio.next = 0
                    # oaddr.next = 0
                    do.next = 0
                    doo.next = 0
                    filled.next = True
                    first_block.next = True
                    state.next = d_state.HEADER

                else:
                    pass

            elif state == d_state.HEADER:

                if not DECOMPRESS:
                    pass
                elif not filled:
                    filled.next = True
                elif not nb:
                    pass
                # Read block header
                elif False and first_block:
                    first_block.next = False
                    # We skip this test because smaller windows give
                    # another header

                    if b1 == 0x78:
                        print("deflate mode")
                    else:
                        print(di, dio, nb, b1, b2, b3, b4, isize)
                        raise Error("unexpected mode")
                        o_done.next = True
                        state.next = d_state.IDLE
                else:
                    if not ONEBLOCK:
                        if get4(0, 1):
                            print("final")
                            final.next = True
                        else:
                            final.next = False
                    if DYNAMIC:
                        hm = get4(1, 2)
                        method.next = hm
                        print("method", hm)
                        # print(di, dio, nb, b1, b2, b3, b4, hm, isize)
                        if hm == 2:
                            if not DYNAMIC:
                                print("dynamic tree mode disabled")
                                raise Error("dynamic tree mode disabled")
                            state.next = d_state.BL
                            numCodeLength.next = 0
                            numLiterals.next = 0
                            static.next = False
                            adv(3)
                        elif hm == 1:
                            static.next = True
                            cur_static.next = 0
                            print("prev method is", prev_method)
                            if prev_method == 1:
                                print("skip HF init")
                                state.next = d_state.NEXT
                                cur_next.next = 0
                            else:
                                state.next = d_state.STATIC
                            adv(3)
                        elif hm == 0:
                            state.next = d_state.COPY
                            skip = 8 - dio
                            if skip <= 2:
                                skip = 16 - dio
                            length.next = get4(skip, 16)
                            adv(skip + 16)
                            cur_i.next = 0
                            offset.next = 7
                        else:
                            state.next = d_state.IDLE
                            print("Bad method")
                            raise Error("Bad method")
                        prev_method.next = hm
                        print("set prev", hm)
                    else:
                        # static.next = True
                        method.next = 1
                        cur_next.next = 0
                        if ONEBLOCK:
                            dio.next = 3
                        else:
                            adv(3)
                        state.next = d_state.NEXT

            elif state == d_state.CSTATIC:

                # print("CSTATIC", cur_i, ob1, do, doo, isize)

                if not COMPRESS:
                    pass
                elif not nb:
                    pass
                elif not FAST and not filled:
                    filled.next = True
                elif LOWLUT and fcount == 0:
                    pass
                elif cur_cstatic == 0:
                    flush.next = False
                    ob1.next = 0
                    adler1.next = 1
                    adler2.next = 0
                    ladler1.next = 0
                    oaddr.next = 0
                    obyte.next = 0x78
                    cur_cstatic.next = 1
                elif cur_cstatic == 1:
                    oaddr.next = 1
                    obyte.next = 0x9c
                    do.next = 2
                    cur_cstatic.next = 2
                elif cur_cstatic == 2:
                    put(0x3, 3)
                    cur_cstatic.next = 3
                elif flush:
                    # print("flush", do, ob1)
                    oaddr.next = do
                    obyte.next = ob1
                    do_flush()
                elif di >= isize - 10 and i_mode != IDLE:
                    print("P", di, isize)
                    pass
                elif di > isize:
                    if cur_cstatic == 3:
                        cur_cstatic.next = 4
                        print("Put EOF", do)
                        cs_i = EndOfBlock
                        outlen = codeLength[cs_i]
                        outbits = out_codes[cs_i]
                        print("EOF BITS:", cs_i, outlen, outbits)
                        put(outbits, outlen)
                    elif cur_cstatic == 4:
                        cur_cstatic.next = 5
                        print("calc end adler")
                        adler2.next = (adler2 + ladler1) % 65521
                        if doo != 0:
                            oaddr.next = do
                            obyte.next = ob1
                            do.next = do + 1
                    elif cur_cstatic == 5:
                        cur_cstatic.next = 6
                        print("c1", adler2)
                        oaddr.next = do
                        obyte.next = adler2 >> 8
                        do.next = do + 1
                        o_oprogress.next = do + 1
                    elif cur_cstatic == 6:
                        cur_cstatic.next = 7
                        print("c2")
                        oaddr.next = do
                        obyte.next = adler2 & 0xFF
                        do.next = do + 1
                        o_oprogress.next = do + 1
                    elif cur_cstatic == 7:
                        cur_cstatic.next = 8
                        print("c3", adler1)
                        oaddr.next = do
                        obyte.next = adler1 >> 8
                        do.next = do + 1
                        o_oprogress.next = do + 1
                    elif cur_cstatic == 8:
                        cur_cstatic.next = 9
                        print("c4")
                        oaddr.next = do
                        obyte.next = adler1 & 0xFF
                        o_oprogress.next = do + 1
                    elif cur_cstatic == 9:
                        cur_cstatic.next = 10
                        print("EOF finish", do)
                        o_done.next = True
                        state.next = d_state.IDLE
                    else:
                        print(cur_cstatic, isize)
                        raise Error("???")
                else:
                    # print("fcount", fcount)
                    # bdata = b1
                    bdata = iram[di & IBS]
                    o_iprogress.next = di
                    adler1_next = (adler1 + bdata) % 65521
                    adler1.next = adler1_next
                    adler2.next = (adler2 + ladler1) % 65521
                    ladler1.next = adler1_next
                    # print("in: ", bdata, di, isize)
                    state.next = d_state.SEARCH
                    cur_search.next = di - 1

            elif state == d_state.DISTANCE:

                if not COMPRESS:
                    pass
                elif flush:
                    do_flush()
                elif do_init:
                    do_init.next = False
                    outcarrybits.next = 0
                    lencode = mlength + 254
                    # print("fast:", distance, di, isize, match)
                    outlen = codeLength[lencode]
                    outbits = out_codes[lencode]
                    # print("BITS:", outlen, outbits)
                    put(outbits, outlen)
                    cur_i.next = 0
                elif outcarrybits:
                    # print("CARRY", outcarry, outcarrybits)
                    put(outcarry, outcarrybits)
                    state.next = d_state.CHECKSUM
                else:
                    # print("DISTANCE", di, do, cur_i, cur_dist)
                    nextdist = CopyDistance[cur_i+1]
                    if nextdist > cur_dist:
                        copydist = CopyDistance[cur_i]
                        # print("Found distance", copydist)
                        extra_dist = cur_dist - copydist
                        # print("extra dist", extra_dist)
                        extra_bits = ExtraDistanceBits[cur_i // 2]
                        # print("extra bits", extra_bits)
                        if extra_dist > ((1 << extra_bits) - 1):
                            raise Error("too few extra")
                        # print("rev", cur_i, rev_bits(cur_i, 5))
                        cur_i.next = di - mlength + 1
                        outcode = (rev_bits(cur_i, 5) | (extra_dist << 5))
                        if extra_bits <= 4:
                            # print("outcode", outcode)
                            put(outcode, 5 + extra_bits)
                            state.next = d_state.CHECKSUM
                        else:
                            # print("LONG", extra_bits, outcode)
                            outcarry.next = outcode >> 8
                            outcarrybits.next = extra_bits - 3
                            outcode = outcode & 0xFF
                            put(outcode, 8)
                    else:
                        cur_i.next = cur_i + 1

            elif state == d_state.CHECKSUM:

                if not COMPRESS:
                    pass
                elif cur_i < di:
                    # print("CHECKSUM", cur_i, di, iram[cur_i])
                    bdata = iram[cur_i & IBS]
                    adler1_next = (adler1 + bdata) % 65521
                    adler1.next = adler1_next
                    adler2.next = (adler2 + ladler1) % 65521
                    ladler1.next = adler1_next
                    cur_i.next = cur_i.next + 1
                else:
                    state.next = d_state.CSTATIC

            elif state == d_state.SEARCHF:

                if FAST and COMPRESS:
                    lfmatch = dlength
                    distance = lfmatch + 1
                    # print("FSEARCH", distance)
                    fmatch2 = di - lfmatch + 2
                    # Length is 3 code
                    match = 3
                    mdone = True

                    if di < isize - 4 and \
                            iram[fmatch2 & IBS] == b4:
                        match = 4
                        if fcount < 5:
                            mdone = False
                            # print("fcount", fcount)
                        elif di < isize - 5 and \
                                iram[fmatch2+1 & IBS] == b5:
                            match = 5
                            if MATCH10:
                                if fcount < 6:
                                    mdone = False
                                    # print("fcount", fcount)
                                elif di < isize - 6 and \
                                        iram[fmatch2+2 & IBS] == b6:
                                    match = 6
                                    if fcount < 7:
                                        mdone = False
                                        # print("fcount", fcount)
                                    elif di < isize - 7 and \
                                            iram[fmatch2+3 & IBS] == b7:
                                        match = 7
                                        if fcount < 8:
                                            mdone = False
                                            # print("fcount", fcount)
                                        elif di < isize - 8 and \
                                                iram[fmatch2+4 & IBS] == b8:
                                            match = 8
                                            if fcount < 9:
                                                mdone = False
                                                # print("fcount", fcount)
                                            elif di < isize - 9 and \
                                                    iram[fmatch2+5 & IBS] == b9:
                                                match = 9
                                                if fcount < 10:
                                                    mdone = False
                                                    # print("fcount", fcount)
                                                elif di < isize - 10 and \
                                                        iram[fmatch2+6 & IBS] == b10:
                                                    match = 10

                    if mdone:
                        # distance = di - cur_search
                        # print("d/l", di, distance, match)
                        cur_dist.next = distance
                        do_init.next = True
                        # adv(match * 8)
                        di.next = di + match
                        if not FAST:
                            filled.next = False
                        mlength.next = match
                        state.next = d_state.DISTANCE

            elif state == d_state.SEARCH:

                if not COMPRESS:
                    pass
                elif not FAST and not filled:
                    print("!")
                    filled.next = True
                elif LOWLUT and fcount < 3:
                    # print("SEARCH", fcount)
                    pass
                else:
                    # print("cs",  cur_search, di, di - CWINDOW)
                    if cur_search >= 0 \
                             and cur_search >= di - CWINDOW \
                             and di < isize - 3:

                        if FAST:
                            found = 0
                            fmatch = 0
                            for si in range(CWINDOW):
                                # print("test", di, si, di - si - 1)
                                if smatch[si]:
                                    # print("fmatch", si)
                                    fmatch = si
                                    found = 1
                                    break
                            if not found or di - fmatch - 1 < 0:
                                cur_search.next = -1
                                # print("NO FSEARCH")
                            else:
                                dlength.next = fmatch
                                state.next = d_state.SEARCHF

                        elif iram[cur_search & IBS] == b1 and \
                                iram[cur_search + 1 & IBS] == b2 and \
                                iram[cur_search + 2 & IBS] == b3:
                            more.next = 4
                            state.next = d_state.SEARCH10

                        else:
                            cur_search.next = cur_search - 1
                    else:
                        bdata = b1  # iram[di]
                        # print("B1", b1)
                        # adv(8)
                        di.next = di + 1
                        # o_iprogress.next = di
                        if not FAST:
                            filled.next = False
                        outlen = codeLength[bdata]
                        outbits = out_codes[bdata]
                        # print("CBITS:", bdata, outlen, outbits)
                        put(outbits, outlen)
                        state.next = d_state.CSTATIC

            elif state == d_state.SEARCH10:

                if not COMPRESS or FAST:
                    pass
                else:
                    # print("SEARCH10", more, fcount)
                    mdone = True
                    mlimit = 5
                    if MATCH10:
                        mlimit = 10
                    # print("more/fcount", more, fcount)
                    if more <= mlimit:
                        cbyte = b4
                        if more == 5:
                            cbyte = b5
                        elif MATCH10:
                            if more == 6:
                                cbyte = b6
                            elif more == 7:
                                cbyte = b7
                            elif more == 8:
                                cbyte = b8
                            elif more == 9:
                                cbyte = b9
                            elif more == 10:
                                cbyte = b10

                        if di < isize - more and \
                                iram[cur_search + more - 1 & IBS] == cbyte:
                            more.next = more + 1
                            mdone = False

                    if mdone:
                        match = more - 1
                        distance = di - cur_search
                        # print("d/l", distance, match)
                        cur_dist.next = distance
                        do_init.next = True
                        # adv(match * 8)
                        di.next = di + match
                        # o_iprogress.next = di
                        if not FAST:
                            filled.next = False
                        mlength.next = match
                        state.next = d_state.DISTANCE

            elif state == d_state.STATIC:

                for stat_i in range(0, 144):
                    codeLength[stat_i].next = 8
                for stat_i in range(144, 256):
                    codeLength[stat_i].next = 9
                for stat_i in range(256, 280):
                    codeLength[stat_i].next = 7
                for stat_i in range(280, 288):
                    codeLength[stat_i].next = 8
                numCodeLength.next = 288
                if COMPRESS and do_compress:
                    state.next = d_state.CSTATIC
                elif DYNAMIC:
                    cur_HF1.next = 0
                    state.next = d_state.HF1
                else:
                    cur_next.next = 0
                    state.next = d_state.NEXT

            elif state == d_state.BL:

                if not DECOMPRESS or not DYNAMIC:
                    pass
                elif not filled:
                    filled.next = True
                elif numLiterals == 0:
                    print(di, isize)
                    numLiterals.next = 257 + get4(0, 5)
                    print("NL:", 257 + get4(0, 5))
                    numDistance.next = 1 + get4(5, 5)
                    print("ND:", 1 + get4(5, 5))
                    b_numCodeLength.next = 4 + get4(10, 4)
                    print("NCL:", 4 + get4(10, 4))
                    numCodeLength.next = 0
                    adv(14)
                else:
                    if numCodeLength < CodeLengths:
                        clo_i = CodeLengthOrder[numCodeLength]
                        # print("CLI: ", clo_i)
                        if numCodeLength < b_numCodeLength:
                            codeLength[clo_i].next = get4(0, 3)
                            adv(3)
                        else:
                            # print("SKIP")
                            codeLength[clo_i].next = 0
                        numCodeLength.next = numCodeLength + 1
                    else:
                        numCodeLength.next = CodeLengths
                        cur_HF1.next = 0
                        state.next = d_state.HF1

            elif state == d_state.READBL:

                if not DECOMPRESS or not DYNAMIC:
                    pass
                elif not filled:
                    filled.next = True
                elif numCodeLength < numLiterals + numDistance:
                    # print(numLiterals + numDistance, numCodeLength)
                    n_adv = 0
                    if code < 16:
                        howOften.next = 1
                        lastToken.next = code
                    elif code == 16:
                        howOften.next = 3 + get4(0, 2)
                        n_adv = 2
                    elif code == 17:
                        howOften.next = 3 + get4(0, 3)
                        lastToken.next = 0
                        n_adv = 3
                    elif code == 18:
                        howOften.next = 11 + get4(0, 7)
                        lastToken.next = 0
                        n_adv = 7
                    else:
                        raise Error("Invalid data")

                    # print(numCodeLength, howOften, code, di, n_adv)
                    if n_adv != 0:
                        adv(n_adv)

                    state.next = d_state.REPEAT
                else:
                    print("FILL UP")

                    for dbl_i in range(32):
                        dbl = 0
                        if dbl_i + numLiterals < numCodeLength:
                            dbl = int(codeLength[dbl_i + numLiterals])
                        # print("dbl:", dbl)
                        distanceLength[dbl_i].next = dbl

                    # print(numCodeLength, numLiterals, MaxBitLength)

                    cur_i.next = numLiterals
                    state.next = d_state.INIT3

            elif state == d_state.INIT3:

                if not DECOMPRESS or not DYNAMIC:
                    pass
                elif cur_i < len(codeLength):
                    codeLength[cur_i].next = 0
                    cur_i.next = cur_i + 1
                else:
                    method.next = 3  # Start building bit tree
                    cur_HF1.next = 0
                    state.next = d_state.HF1

            elif state == d_state.DISTTREE:

                if DECOMPRESS and DYNAMIC:
                    print("DISTTREE")
                    for dist_i in range(32):
                        codeLength[dist_i].next = distanceLength[dist_i]
                        # print(dist_i, distanceLength[dist_i])
                    numCodeLength.next = 32
                    method.next = 4  # Start building dist tree
                    cur_HF1.next = 0
                    state.next = d_state.HF1

            elif state == d_state.REPEAT:

                if not DECOMPRESS or not DYNAMIC:
                    pass
                elif howOften != 0:
                    codeLength[numCodeLength].next = lastToken
                    howOften.next = howOften - 1
                    numCodeLength.next = numCodeLength + 1
                elif numCodeLength < numLiterals + numDistance:
                    cur_next.next = 0
                    state.next = d_state.NEXT
                else:
                    state.next = d_state.READBL

            elif state == d_state.HF1:

                if DECOMPRESS and DYNAMIC:
                    if cur_HF1 < len(bitLengthCount):
                        bitLengthCount[cur_HF1].next = 0
                    if cur_HF1 < len(d_leaves) and DYNAMIC:
                        dlwaddr.next = cur_HF1
                        dwleaf.next = 0
                        # d_leaves[cur_HF1].next = 0
                    if method != 4 and cur_HF1 < len(leaves):
                        lwaddr.next = cur_HF1
                        wleaf.next = 0
                        # leaves[cur_HF1].next = 0
                    limit = len(leaves)
                    if method == 4 and DYNAMIC:
                        limit = len(d_leaves)
                    if cur_HF1 < limit:
                        cur_HF1.next = cur_HF1 + 1
                    else:
                        print("DID HF1 INIT")
                        cur_i.next = 0
                        state.next = d_state.HF1INIT

            elif state == d_state.HF1INIT:
                # get frequencies of each bit length and ignore 0's

                # print("HF1")
                if not DECOMPRESS or not DYNAMIC:
                    pass
                elif cur_i < numCodeLength:
                    j = codeLength[cur_i]
                    bitLengthCount[j].next = bitLengthCount[j] + 1
                    # print(cur_i, j, bitLengthCount[j] + 1)
                    cur_i.next = cur_i + 1
                else:
                    bitLengthCount[0].next = 0
                    state.next = d_state.HF2
                    cur_i.next = 1
                    if DYNAMIC and method == 4:
                        d_maxBits.next = 0
                    else:
                        maxBits.next = 0
                    minBits.next = MaxCodeLength

            elif state == d_state.HF2:
                # shortest and longest codes

                # print("HF2")
                if not DECOMPRESS or not DYNAMIC:
                    pass
                elif cur_i <= MaxCodeLength:
                    if bitLengthCount[cur_i] != 0:
                        if cur_i < minBits:
                            minBits.next = cur_i
                        if DYNAMIC and method == 4:
                            if cur_i > d_maxBits:
                                d_maxBits.next = cur_i
                        else:
                            if cur_i > maxBits:
                                maxBits.next = cur_i
                    cur_i.next = cur_i + 1
                else:
                    print(minBits, maxBits)
                    t = InstantMaxBit
                    if DYNAMIC and method == 4:
                        if t > int(d_maxBits):
                            t = int(d_maxBits)
                        d_instantMaxBit.next = t
                        d_instantMask.next = (1 << t) - 1
                    else:
                        if t > int(maxBits):
                            t = int(maxBits)
                        instantMaxBit.next = t
                        instantMask.next = (1 << t) - 1
                    print((1 << t) - 1)
                    state.next = d_state.HF3
                    cur_i.next = minBits
                    code.next = 0
                    for hf2_i in range(len(nextCode)):
                        nextCode[hf2_i].next = 0
                    print("to HF3")

            elif state == d_state.HF3:
                # find bit code for first element of each bitLength group

                # print("HF3")
                if DECOMPRESS and DYNAMIC:
                    amb = maxBits
                    if DYNAMIC and method == 4:
                        amb = d_maxBits
                    if cur_i <= amb:
                        ncode = ((code + bitLengthCount[cur_i - 1]) << 1)
                        code.next = ncode
                        nextCode[cur_i].next = ncode
                        # print(cur_i, ncode)
                        cur_i.next = cur_i + 1
                    else:
                        state.next = d_state.HF4
                        cur_i.next = 0
                        spread_i.next = 0
                        print("to HF4")

            elif state == d_state.HF4_2:

                if DECOMPRESS and DYNAMIC:
                    canonical = nextCode[bits]
                    nextCode[bits].next = nextCode[bits] + 1
                    if bits > MaxCodeLength:
                        raise Error("too many bits: %d" % bits)
                    # print(canonical, bits)
                    reverse.next = rev_bits(canonical, bits)
                    # print("LEAF: ", spread_i, bits, reverse, canonical)
                    leaf.next = makeLeaf(spread_i, bits)
                    state.next = d_state.HF4_3

            elif state == d_state.HF4_3:

                if not DECOMPRESS or not DYNAMIC:
                    pass
                elif DYNAMIC and method == 4:
                    dwleaf.next = leaf
                    dlwaddr.next = reverse
                    # d_leaves[reverse].next = leaf
                    if bits <= d_instantMaxBit:
                        if reverse + (1 << bits) <= d_instantMask:
                            step.next = 1 << bits
                            spread.next = reverse + (1 << bits)
                            state.next = d_state.SPREAD
                        else:
                            spread_i.next = spread_i + 1
                            state.next = d_state.HF4
                    else:
                        state.next = d_state.HF4
                        spread_i.next = spread_i + 1
                else:
                    wleaf.next = leaf
                    lwaddr.next = reverse
                    # leaves[reverse].next = leaf # makeLeaf(spread_i, bits)
                    # code_bits[spread_i].next = reverse
                    if bits <= instantMaxBit:
                        if reverse + (1 << bits) <= instantMask:
                            step.next = 1 << bits
                            spread.next = reverse + (1 << bits)
                            state.next = d_state.SPREAD
                        else:
                            spread_i.next = spread_i + 1
                            state.next = d_state.HF4
                    else:
                        spread_i.next = spread_i + 1
                        state.next = d_state.HF4

            elif state == d_state.HF4:
                # create binary codes for each literal

                if not DECOMPRESS or not DYNAMIC:
                    pass
                elif spread_i < numCodeLength:
                    bits_next = codeLength[spread_i]
                    if bits_next != 0:
                        bits.next = bits_next
                        state.next = d_state.HF4_2
                    else:
                        # print("SKIP UNUSED")
                        spread_i.next = spread_i + 1
                else:
                    if method == 3 and DYNAMIC:
                        state.next = d_state.DISTTREE
                    elif method == 4 and DYNAMIC:
                        print("DEFLATE m2!")
                        state.next = d_state.NEXT
                    elif method == 2 and DYNAMIC:
                        numCodeLength.next = 0
                        state.next = d_state.NEXT
                    else:
                        state.next = d_state.NEXT
                    cur_next.next = 0
                    cur_i.next = 0

            elif state == d_state.SPREAD:

                if DECOMPRESS and DYNAMIC:
                    if method == 4 and DYNAMIC:
                        # print(spread, spread_i)
                        dlwaddr.next = spread
                        dwleaf.next = makeLeaf(spread_i, codeLength[spread_i])
                    else:
                        lwaddr.next = spread
                        wleaf.next = makeLeaf(spread_i, codeLength[spread_i])
                    # print("SPREAD:", spread, step, instantMask)
                    aim = instantMask
                    if method == 4 and DYNAMIC:
                        aim = d_instantMask
                    if spread > aim - step:
                        spread_i.next = spread_i + 1
                        state.next = d_state.HF4
                    else:
                        spread.next = spread + step

            elif state == d_state.NEXT:

                if not DECOMPRESS:
                    pass
                elif not filled:
                    # print("NEXT !F")
                    filled.next = True
                elif cur_next == 0:
                    # print("INIT:", di, dio, instantMaxBit, maxBits)
                    cto = get4(0, maxBits)
                    mask = (1 << instantMaxBit) - 1
                    if DYNAMIC:
                        lraddr.next = (cto & mask)
                        filled.next = False
                    else:
                        stat_leaf.next = stat_leaves[cto & mask]
                    # print(cto & mask)
                    # leaf.next = leaves[cto & mask]
                    cur_next.next = instantMaxBit + 1
                    # print(cur_next, mask, leaf, maxBits)
                # elif get_bits(leaf) >= cur_next:
                elif DYNAMIC and get_bits(rleaf) >= cur_next:
                    print("CACHE MISS", cur_next)
                    cto = get4(0, maxBits)
                    mask = (1 << cur_next) - 1
                    lraddr.next = (cto & mask)
                    # leaf.next = leaves[cto & mask]
                    filled.next = False
                    cur_next.next = cur_next + 1
                else:
                    the_leaf = rleaf
                    if not DYNAMIC:
                        the_leaf = stat_leaf
                    # if get_bits(leaf) < 1:
                    # print(di, do, rleaf)
                    if get_bits(the_leaf) < 1:
                        print("< 1 bits: ")
                        raise Error("< 1 bits: ")
                    adv(get_bits(the_leaf))
                    code.next = get_code(the_leaf)
                    if DYNAMIC and method == 2:
                        state.next = d_state.READBL
                    else:
                        state.next = d_state.INFLATE

            elif state == d_state.D_NEXT:

                if not DECOMPRESS or not DYNAMIC:
                    pass
                elif not filled:
                    filled.next = True
                elif cur_next == 0:
                    # print("D_INIT:", di, dio, d_instantMaxBit, d_maxBits)
                    if d_instantMaxBit > InstantMaxBit:
                        raise Error("???")
                    token = code - 257
                    # print("token: ", token)
                    extraLength = ExtraLengthBits[token]
                    # print("extra length bits:", extraLength)
                    # print("d_maxBits", d_maxBits, d_instantMaxBit)
                    cto = get4(extraLength, d_maxBits)
                    mask = (1 << d_instantMaxBit) - 1
                    dlraddr.next = (cto & mask)
                    filled.next = False
                    # leaf.next = d_leaves[cto & mask]
                    cur_next.next = instantMaxBit + 1
                elif get_bits(drleaf) >= cur_next:
                    print("DCACHE MISS", cur_next)
                    token = code - 257
                    # print("token: ", token)
                    extraLength = ExtraLengthBits[token]
                    cto = get4(extraLength, d_maxBits)
                    mask = (1 << cur_next) - 1
                    dlraddr.next = (cto & mask)
                    filled.next = False
                    # leaf.next = d_leaves[cto & mask]
                    cur_next.next = cur_next + 1
                else:
                    state.next = d_state.D_NEXT_2

            elif state == d_state.D_NEXT_2:

                if DECOMPRESS and DYNAMIC:
                    if get_bits(drleaf) == 0:
                        raise Error("0 bits")
                    token = code - 257
                    # print("E2:", token, drleaf)
                    tlength = CopyLength[token]
                    # print("tlength:", tlength)
                    extraLength = ExtraLengthBits[token]
                    # print("extra length bits:", extraLength)
                    tlength += get4(0, extraLength)
                    # print("extra length:", tlength)
                    distanceCode = get_code(drleaf)
                    # print("distance code:", distanceCode)
                    distance = CopyDistance[distanceCode]
                    # print("distance:", distance)
                    moreBits = ExtraDistanceBits[distanceCode >> 1]
                    # print("more bits:", moreBits)
                    # print("bits:", get_bits(drleaf))
                    mored = get4(extraLength + get_bits(drleaf), moreBits)
                    # print("mored:", mored)
                    distance += mored
                    # print("distance more:", distance, do, di, isize)
                    if distance > do:
                        print(distance, do)
                        raise Error("distance too big")
                    adv(moreBits + extraLength + get_bits(drleaf))
                    # print("offset:", do - distance)
                    # print("FAIL?: ", di, dio, do, b1, b2, b3, b4)
                    offset.next = (do - distance) & OBS
                    length.next = tlength
                    # cur_next.next = 0
                    cur_i.next = 0
                    oraddr.next = do - distance
                    state.next = d_state.COPY

            elif state == d_state.INFLATE:

                if not DECOMPRESS:
                    pass
                elif LOWLUT and fcount < 3:
                    # print("INFLATE fc", fcount)
                    pass
                elif method == 1 and not filled:
                    # print("INFLATE !F")
                    filled.next = True
                elif di >= isize - 4 and not i_mode == IDLE:
                    pass  # fetch more bytes
                elif do >= i_raddr + OBSIZE:
                    print("HOLDB")
                    # filled.next = False
                    pass
                elif di > isize - 3:  # checksum is 4 bytes
                    state.next = d_state.IDLE
                    o_done.next = True
                    print("NO EOF ", di)
                    raise Error("NO EOF!")
                elif code == EndOfBlock:
                    print("EOF:", isize, di, do)
                    if not ONEBLOCK and not final:
                        state.next = d_state.HEADER
                        filled.next = False
                        print("New Block!")
                    else:
                        o_done.next = True
                        state.next = d_state.IDLE
                else:
                    if code < EndOfBlock:
                        # print("B:", code, di, do)
                        oaddr.next = do
                        obyte.next = code
                        o_oprogress.next = do + 1
                        do.next = do + 1
                        cur_next.next = 0
                        state.next = d_state.NEXT
                        # raise Error("DF!")
                    elif code == InvalidToken:
                        raise Error("invalid token")
                    else:
                        if not DYNAMIC or static:
                            token = code - 257
                            # print("E:", token)
                            tlength = CopyLength[token]
                            # print("tlength", tlength)
                            extraLength = ExtraLengthBits[token]
                            # print("extralengthbits", extraLength)
                            tlength += get4(0, extraLength)
                            # print("tlength extra", tlength)
                            t = get4(extraLength, 5)
                            distanceCode = rev_bits(t, 5)
                            # print("dcode", distanceCode)
                            distance = CopyDistance[distanceCode]
                            # print("distance", distance)
                            moreBits = ExtraDistanceBits[distanceCode >> 1]
                            distance += get4(extraLength + 5, moreBits)
                            # print("distance2", distance)
                            adv(extraLength + 5 + moreBits)
                            # print("adv", extraLength + 5 + moreBits)
                            offset.next = (do - distance) & OBS
                            length.next = tlength
                            cur_i.next = 0
                            oraddr.next = do - distance
                            state.next = d_state.COPY
                        else:
                            if not DYNAMIC:
                                print("DYNAMIC mode disabled")
                                raise Error("DYNAMIC mode disabled")
                            state.next = d_state.D_NEXT
                    cur_next.next = 0

            elif state == d_state.COPY:

                if not DECOMPRESS:
                    pass
                elif cur_i == 0 and do + length >= i_raddr + OBSIZE:
                    # print("HOLDW", length, offset, cur_i, do, i_raddr)
                    pass
                elif di >= isize - 2:
                    # print("HOLD2")
                    pass
                elif DYNAMIC and method == 0:
                    if not filled:
                        # print("COPY !F")
                        filled.next = True
                    elif cur_i < length:
                        oaddr.next = do
                        obyte.next = b3
                        # adv(8)
                        di.next = di + 1
                        o_iprogress.next = di
                        cur_i.next = cur_i + 1
                        do.next = do + 1
                        o_oprogress.next = do + 1
                    elif not ONEBLOCK and not final:
                        # adv(16)
                        di.next = di + 2
                        o_iprogress.next = di
                        state.next = d_state.HEADER
                        filled.next = False
                        print("new block")
                    else:
                        o_done.next = True
                        state.next = d_state.IDLE
                elif cur_i < length + 2:
                    # print("L/O", length, offset, do)
                    oraddr.next = offset + cur_i
                    if cur_i == 1:
                        off1.next = (offset == (do - 1) & OBS)
                        off2.next = (offset == (do - 2) & OBS)
                        copy1.next = orbyte
                        # print("c1", cur_i, length, offset, do, orbyte)
                    if cur_i == 3:
                        copy2.next = orbyte
                    if cur_i > 1:
                        # Special 1 byte offset handling:
                        if off1:
                            # print("1 byte", do)
                            obyte.next = copy1
                        elif cur_i == 3 or not off2:
                            obyte.next = orbyte
                        # Special 2 byte offset handling:
                        elif cur_i > 2:
                            # print("2 byte", do)
                            if cur_i & 1:
                                obyte.next = copy2
                            else:
                                obyte.next = copy1
                        else:  # cur_i == 2
                            obyte.next = copy1
                        oaddr.next = do
                        o_oprogress.next = do + 1
                        do.next = do + 1
                    cur_i.next = cur_i + 1
                else:
                    cur_next.next = 0
                    state.next = d_state.NEXT

            else:

                print("unknown state?!")
                state.next = d_state.IDLE

    if FAST:
        return io_logic, logic, fill_buf, bramwrite, bramread, matchers
    else:
        return io_logic, logic, fill_buf, bramwrite, bramread


if __name__ == "__main__":
    d = deflate(Signal(intbv()[3:]), Signal(bool(0)),
                Signal(intbv()[8:]), Signal(intbv()[LMAX:]),
                Signal(intbv()[LMAX:]),
                Signal(intbv()[8:]),
                Signal(modbv()[LIBSIZE:]), Signal(modbv()[LBSIZE:]),
                Signal(bool(0)), ResetSignal(1, 0, True))
    d.convert(initial_values=False)
