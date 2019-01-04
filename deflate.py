"""
MyHDL FPGA Deflate (de)compressor, see RFC 1950/1951

Copyright (C) 2018/2019 by Tom Vijlbrief

See: https://github.com/tomtor

This MyHDL FPGA implementation is partially inspired by the C++ implementation
of a decoder from https://create.stephan-brumme.com/deflate-decoder

"""

from math import log2

from myhdl import always, block, Signal, intbv, Error, ResetSignal, \
    enum, always_seq, always_comb, concat, ConcatSignal, modbv

IDLE, RESET, WRITE, READ, STARTC, STARTD = range(6)

COMPRESS = False
COMPRESS = True

DECOMPRESS = False
DECOMPRESS = True

DYNAMIC = False
DYNAMIC = True

MATCH10 = False
MATCH10 = True

FAST = False
FAST = True

CWINDOW = 32    # Search window for compression

OBSIZE = 8192   # Size of output buffer (BRAM)
OBSIZE = 32768  # Size of output buffer for ANY input (BRAM)

# Size of input buffer (LUT-RAM)
IBSIZE = 16 * CWINDOW  # This size gives method 2 (dynamic tree) for testbench
IBSIZE = 2 * CWINDOW   # Minimal window

LMAX = 24       # Size of progress and I/O counters


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
               'STATIC', 'D_NEXT', 'D_NEXT_2',
               'D_INFLATE', 'SPREAD', 'NEXT', 'INFLATE', 'COPY', 'CSTATIC',
               'SEARCH', 'SEARCHF', 'DISTANCE', 'CHECKSUM') # , encoding='one_hot')

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

    # iraddr = Signal(modbv()[LIBSIZE:])

    isize = Signal(intbv()[LMAX:])
    state = Signal(d_state.IDLE)
    method = Signal(intbv()[3:])
    final = Signal(bool())
    wtick = Signal(bool())
    do_compress = Signal(bool())

    numLiterals = Signal(intbv()[9:])
    numDistance = Signal(intbv()[6:])
    numCodeLength = Signal(intbv()[9:])
    b_numCodeLength = Signal(intbv()[9:])

    CodeLengths = 19
    MaxCodeLength = 15
    InstantMaxBit = 10
    EndOfBlock = 256
    MaxBitLength = 288
    # MaxToken = 285
    InvalidToken = 300

    CODEBITS = MaxCodeLength
    BITBITS = 4

    codeLength = [Signal(intbv()[4:]) for _ in range(MaxBitLength+32)]
    bits = Signal(intbv()[4:])
    bitLengthCount = [Signal(intbv()[9:]) for _ in range(MaxCodeLength+1)]
    nextCode = [Signal(intbv()[CODEBITS+1:]) for _ in range(MaxCodeLength+1)]
    reverse = Signal(modbv()[CODEBITS:])
    # code_bits = [Signal(intbv()[MaxCodeLength:]) for _ in range(MaxBitLength)]
    distanceLength = [Signal(intbv()[4:]) for _ in range(32)]

    if DECOMPRESS:
        if DYNAMIC:
            # leaves = [Signal(intbv()[CODEBITS + BITBITS:]) for _ in range(16384)]
            leaves = [Signal(intbv()[CODEBITS + BITBITS:]) for _ in range(32768)]
            d_leaves = [Signal(intbv()[CODEBITS + BITBITS:]) for _ in range(4096)]
        else:
            leaves = [Signal(intbv()[CODEBITS + BITBITS:]) for _ in range(512)]
            d_leaves = [Signal(bool())]
        # d_leaves = [Signal(intbv()[CODEBITS + BITBITS:]) for _ in range(32768)]
    else:
        leaves = [Signal(bool())]
        d_leaves = [Signal(bool())]

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

    code = Signal(intbv()[15:])
    lastToken = Signal(intbv()[15:])
    howOften = Signal(intbv()[9:])

    cur_i = Signal(intbv()[LMAX:])
    spread_i = Signal(intbv()[9:])
    cur_HF1 = Signal(intbv()[MaxCodeLength+1:])
    cur_static = Signal(intbv()[9:])
    cur_cstatic = Signal(intbv()[LMAX:])
    cur_search = Signal(intbv(min=-1,max=1<<LMAX))
    cur_dist = Signal(intbv(min=-CWINDOW,max=IBSIZE))
    cur_next = Signal(intbv()[4:])

    do_init = Signal(bool())

    length = Signal(modbv()[LOBSIZE:])
    offset = Signal(intbv()[LOBSIZE:])

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

    if MATCH10:
        b6 = Signal(intbv()[8:])
        b7 = Signal(intbv()[8:])
        b8 = Signal(intbv()[8:])
        b9 = Signal(intbv()[8:])
        b10 = Signal(intbv()[8:])
        b110 = ConcatSignal(b1, b2, b3, b4, b5, b6, b7, b8, b9, b10)
        b110._markUsed()
    else:
        b6 = Signal(bool())
        b7 = Signal(bool())
        b8 = Signal(bool())
        b9 = Signal(bool())
        b10 = Signal(bool())
        b110 = Signal(bool())

    fcount = Signal(intbv()[4:])

    # nb = Signal(intbv()[3:])
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
        leaves[lwaddr].next = wleaf
        d_leaves[dlwaddr].next = dwleaf

    @always(clk.posedge)
    def bramread():
        orbyte.next = oram[oraddr]
        rleaf.next = leaves[lraddr]
        drleaf.next = d_leaves[dlraddr]

    @block
    def matcher3(o_m, mi):
        @always_comb
        def logic():
            o_m.next = ((concat(cwindow,b1,b2) >> (8 * mi)) & 0xFFFFFF) == (b14 >> 8)
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
                old_di.next = 0
            elif i_mode == STARTC or i_mode == STARTD:
                nb.next = 0
                old_di.next = 0
            else:
                """
                if do_compress:
                    print("FILL", di, old_di, nb, b1, b2, b3, b4)
                """
                if FAST:  # and do_compress:
                    shift = (di - old_di) * 8
                    """
                    if shift != 0:
                        print("shift", shift, cwindow, b1, b2, b3, b4)
                    """
                    if MATCH10:
                        cwindow.next = (cwindow << shift) | (b110 >> (80 - shift))
                    else:
                        cwindow.next = (cwindow << shift) | (b15 >> (40 - shift))

                # print("B1", iram[di & IBS])
                b1.next = iram[di & IBS]
                b2.next = iram[di+1 & IBS]
                b3.next = iram[di+2 & IBS]

                if old_di == di:
                    """
                    if fcount < 9:
                        print("fcount", fcount)
                    """
                    nb.next = True
                    rb = iram[di + fcount & IBS]
                    if fcount == 4:
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
                    fcount.next = 4
                    b4.next = iram[di+3 & IBS]

                old_di.next = di

    def get4(boffset, width):
        return (b41 >> (dio + boffset)) & ((1 << width) - 1)
        # return b41[dio + boffset + width: dio + boffset]

    def adv(width):
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
        return (ob1 | (d << doo)) & 0xFF

    def put_adv(d, width):
        if width > 9:
            raise Error("width > 9")
        if d > ((1 << width) - 1):
            raise Error("too big")
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
            # oaddr.next = 0
            # obyte.next = 0
        else:

            if state == d_state.IDLE:

                if COMPRESS and i_mode == STARTC:

                    print("STARTC")
                    do_compress.next = True
                    method.next = 1
                    o_done.next = False
                    o_iprogress.next = 0
                    o_oprogress.next = 0
                    di.next = 0
                    dio.next = 0
                    do.next = 0
                    doo.next = 0
                    filled.next = True
                    cur_static.next = 0
                    state.next = d_state.STATIC

                elif DECOMPRESS and i_mode == STARTD:

                    do_compress.next = False
                    o_done.next = False
                    o_iprogress.next = 0
                    o_oprogress.next = 0
                    di.next = 0
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
                elif first_block:
                    first_block.next = False
                    #print(iram[di & IBS])
                    #if iram[di & IBS] == 0x78:
                    if b1 == 0x78:
                        print("deflate mode")
                    else:
                        print(di, dio, nb, b1, b2, b3, b4, isize)
                        raise Error("unexpected mode")
                        o_done.next = True
                        state.next = d_state.IDLE
                    adv(16)
                else:
                    if get4(0, 1):
                        print("final")
                        final.next = True
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

            elif state == d_state.CSTATIC:

                # print("CSTATIC", cur_i, ob1, do, doo, isize)

                no_adv = 0
                if not COMPRESS:
                    pass
                elif not filled:
                    no_adv = 1
                    filled.next = True
                elif not nb:
                    no_adv = 1
                elif cur_cstatic == 0:
                    flush.next = False
                    ob1.next = 0
                    adler1.next = 1
                    adler2.next = 0
                    ladler1.next = 0
                    oaddr.next = 0
                    obyte.next = 0x78
                elif cur_cstatic == 1:
                    oaddr.next = 1
                    obyte.next = 0x9c
                    do.next = 2
                elif cur_cstatic == 2:
                    oaddr.next = do
                    obyte.next = put(0x3, 3)
                    put_adv(0x3, 3)
                elif flush:
                    # print("flush", do, ob1)
                    no_adv = 1
                    oaddr.next = do
                    obyte.next = ob1
                    do_flush()
                elif cur_cstatic >= isize - 10 and i_mode != IDLE:
                    print("P", cur_cstatic, isize)
                    no_adv = 1
                elif cur_cstatic - 3 > isize:
                    if cur_cstatic - 3 == isize + 1:
                        print("Put EOF", do)
                        cs_i = EndOfBlock
                        outlen = codeLength[cs_i]
                        outbits = out_codes[cs_i] # code_bits[cs_i]
                        print("EOF BITS:", cs_i, outlen, outbits)
                        oaddr.next = do
                        obyte.next = put(outbits, outlen)
                        put_adv(outbits, outlen)
                    elif cur_cstatic - 3 == isize + 2:
                        print("calc end adler")
                        adler2.next = (adler2 + ladler1) % 65521
                        if doo != 0:
                            oaddr.next = do
                            obyte.next = ob1
                            do.next = do + 1
                    elif cur_cstatic - 3 == isize + 3:
                        print("c1")
                        oaddr.next = do
                        obyte.next = adler2 >> 8
                        do.next = do + 1
                        o_oprogress.next = do + 1
                    elif cur_cstatic - 3 == isize + 4:
                        print("c2")
                        oaddr.next = do
                        obyte.next = adler2 & 0xFF
                        do.next = do + 1
                        o_oprogress.next = do + 1
                    elif cur_cstatic - 3 == isize + 5:
                        print("c3")
                        oaddr.next = do
                        obyte.next = adler1 >> 8
                        do.next = do + 1
                        o_oprogress.next = do + 1
                    elif cur_cstatic - 3 == isize + 6:
                        print("c4")
                        oaddr.next = do
                        obyte.next = adler1 & 0xFF
                        o_oprogress.next = do + 1
                    elif cur_cstatic - 3 == isize + 7:
                        print("EOF finish", do)
                        o_done.next = True
                        state.next = d_state.IDLE
                    else:
                        print(cur_cstatic, isize)
                        raise Error("???")
                else:
                    bdata = iram[di & IBS]
                    o_iprogress.next = di # & IBS
                    adler1_next = (adler1 + bdata) % 65521
                    adler1.next = adler1_next
                    adler2.next = (adler2 + ladler1) % 65521
                    ladler1.next = adler1_next
                    # print("in: ", bdata, di, isize)
                    state.next = d_state.SEARCH
                    cur_search.next = di - 1  # & IBS

                if not no_adv:
                    cur_cstatic.next = cur_cstatic + 1

            elif state == d_state.DISTANCE:

                if not COMPRESS:
                    pass
                elif flush:
                    do_flush()
                elif do_init:
                    do_init.next = False
                    outcarrybits.next = 0
                    lencode = length + 254
                    # print("fast:", distance, di, isize, match)
                    outlen = codeLength[lencode]
                    outbits = out_codes[lencode] # code_bits[lencode]
                    # print("BITS:", outlen, outbits)
                    oaddr.next = do
                    obyte.next = put(outbits, outlen)
                    put_adv(outbits, outlen)
                    cur_i.next = 0
                elif outcarrybits:
                    # print("CARRY", outcarry, outcarrybits)
                    oaddr.next = do
                    obyte.next = put(outcarry, outcarrybits)
                    put_adv(outcarry, outcarrybits)
                    cur_i.next = di - length + 1
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
                        outcode = (rev_bits(cur_i, 5) | (extra_dist << 5))
                        oaddr.next = do
                        if extra_bits <= 4:
                            # print("outcode", outcode)
                            obyte.next = put(outcode, 5 + extra_bits)
                            put_adv(outcode, 5 + extra_bits)
                            #state.next = d_state.CSTATIC
                            cur_i.next = di - length + 1
                            state.next = d_state.CHECKSUM
                        else:
                            # print("LONG", extra_bits, outcode)
                            # outcarry.next = outcode & ((1 << (extra_bits - 4)) - 1)
                            outcarry.next = outcode >> 8
                            outcarrybits.next = extra_bits - 3
                            outcode = outcode & 0xFF
                            obyte.next = put(outcode, 8)
                            put_adv(outcode, 8)
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
                    lfmatch = length
                    distance = lfmatch + 1
                    # print("FSEARCH", distance)
                    fmatch2 = di - lfmatch + 2
                    # Length is 3 code
                    lencode = 257
                    match = 3
                    mdone = True

                    if di < isize - 4 and \
                            iram[fmatch2 & IBS] == b4:
                        lencode = 258
                        match = 4
                        if fcount < 5:
                            mdone = False
                            print("fcount", fcount)
                        elif di < isize - 5 and \
                                iram[fmatch2+1 & IBS] == b5:
                            lencode = 259
                            match = 5
                            if MATCH10:
                              if fcount < 6:
                                  mdone = False
                                  print("fcount", fcount)
                              elif di < isize - 6 and \
                                    iram[fmatch2+2 & IBS] == b6:
                                lencode = 260
                                match = 6
                                if fcount < 7:
                                    mdone = False
                                    print("fcount", fcount)
                                elif di < isize - 7 and \
                                        iram[fmatch2+3 & IBS] == b7:
                                    lencode = 261
                                    match = 7
                                    if fcount < 8:
                                        mdone = False
                                        print("fcount", fcount)
                                    elif di < isize - 8 and \
                                            iram[fmatch2+4 & IBS] == b8:
                                        lencode = 262
                                        match = 8
                                        if fcount < 9:
                                            mdone = False
                                            print("fcount", fcount)
                                        elif di < isize - 9 and \
                                                iram[fmatch2+5 & IBS] == b9:
                                            lencode = 263
                                            match = 9
                                            if fcount < 10:
                                                mdone = False
                                                print("fcount", fcount)
                                            elif di < isize - 10 and \
                                                    iram[fmatch2+6 & IBS] == b10:
                                                lencode = 264
                                                match = 10

                    if mdone:
                        # distance = di - cur_search
                        print("d/l", di, distance, match)
                        cur_dist.next = distance
                        do_init.next = True
                        # adv(match * 8)
                        di.next = di + match
                        cur_cstatic.next = cur_cstatic + match - 1
                        length.next = match
                        state.next = d_state.DISTANCE

            elif state == d_state.SEARCH:

                if not COMPRESS:
                    pass
                elif not filled:
                    filled.next = True
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
                                length.next = fmatch
                                state.next = d_state.SEARCHF

                        elif not FAST and iram[cur_search & IBS] == b1 and \
                                iram[cur_search+1 & IBS] == b2 and \
                                iram[cur_search+2 & IBS] == b3:
                            # Length is 3 code
                            lencode = 257
                            match = 3
                            mdone = True

                            if di < isize - 4 and \
                                    iram[cur_search+3 & IBS] == b4: # iram[di + 3 & IBS]:
                                lencode = 258
                                match = 4
                                if fcount < 5:
                                    mdone = False
                                    print("fcount", fcount)
                                elif di < isize - 5 and \
                                        iram[cur_search+4 & IBS] == b5:
                                    lencode = 259
                                    match = 5
                                    if MATCH10:
                                        if fcount < 10:
                                            mdone = False
                                            print("fcount", fcount)
                                        elif di < isize - 6 and \
                                                iram[cur_search+5 & IBS] == b6:
                                            lencode = 260
                                            match = 6
                                            if di < isize - 7 and \
                                                iram[cur_search+6 & IBS] == b7:
                                                lencode = 261
                                                match = 7
                                                if di < isize - 8 and \
                                                        iram[cur_search+7 & IBS] == b8:
                                                    lencode = 262
                                                    match = 8
                                                    if di < isize - 9 and \
                                                            iram[cur_search+8 & IBS] == b9:
                                                        lencode = 263
                                                        match = 9
                                                        if di < isize - 10 and \
                                                                iram[cur_search+9 & IBS] == b10:
                                                            lencode = 264
                                                            match = 10

                            if mdone:
                                distance = di - cur_search
                                print("d/l", distance, match)
                                cur_dist.next = distance
                                do_init.next = True
                                # adv(match * 8)
                                di.next = di + match
                                cur_cstatic.next = cur_cstatic + match - 1
                                length.next = match
                                state.next = d_state.DISTANCE
                        else:
                            cur_search.next = cur_search - 1
                    else:
                        bdata = b1  # iram[di]
                        # adv(8)
                        di.next = di + 1
                        outlen = codeLength[bdata]
                        outbits = out_codes[bdata] # code_bits[bdata]
                        # print("CBITS:", bdata, outlen, outbits)
                        oaddr.next = do
                        obyte.next = put(outbits, outlen)
                        put_adv(outbits, outlen)
                        state.next = d_state.CSTATIC

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
                if do_compress:
                    state.next = d_state.CSTATIC
                else:
                    cur_HF1.next = 0
                    state.next = d_state.HF1

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

                if not DECOMPRESS:
                    pass
                elif cur_i < len(codeLength): # MaxBitLength:
                    codeLength[cur_i].next = 0
                    cur_i.next = cur_i + 1
                else:
                    # numCodeLength.next = MaxBitLength
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

                if not DECOMPRESS:
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

                if DECOMPRESS:
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
                if not DECOMPRESS:
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
                    if method == 4:
                        d_maxBits.next = 0
                    else:
                        maxBits.next = 0
                    minBits.next = MaxCodeLength

            elif state == d_state.HF2:
                # shortest and longest codes

                # print("HF2")
                if not DECOMPRESS:
                    pass
                elif cur_i <= MaxCodeLength:
                    if bitLengthCount[cur_i] != 0:
                        if cur_i < minBits:
                            minBits.next = cur_i
                        if method == 4:
                            if cur_i > d_maxBits:
                                d_maxBits.next = cur_i
                        else:
                            if cur_i > maxBits:
                                maxBits.next = cur_i
                    cur_i.next = cur_i + 1
                else:
                    print(minBits, maxBits)
                    t = InstantMaxBit
                    if method == 4 and DYNAMIC:
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
                if DECOMPRESS:
                    amb = maxBits
                    if method == 4 and DYNAMIC:
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

                if DECOMPRESS:
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

                if not DECOMPRESS:
                    pass
                elif method == 4 and DYNAMIC:
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

                if not DECOMPRESS:
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
                    if do_compress:
                        state.next = d_state.CSTATIC
                        cur_cstatic.next = 0
                    elif method == 3 and DYNAMIC:
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

                if DECOMPRESS:
                    if method == 4 and DYNAMIC:
                        # print(spread, spread_i)
                        dlwaddr.next = spread
                        dwleaf.next = makeLeaf(spread_i, codeLength[spread_i])
                        # d_leaves[spread].next = makeLeaf(spread_i, codeLength[spread_i])
                    else:
                        lwaddr.next = spread
                        wleaf.next = makeLeaf(spread_i, codeLength[spread_i])
                        # leaves[spread].next = makeLeaf(spread_i, codeLength[spread_i])
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
                    filled.next = True
                elif cur_next == 0:
                    # print("INIT:", di, dio, instantMaxBit, maxBits)
                    cto = get4(0, maxBits)
                    mask = (1 << instantMaxBit) - 1
                    lraddr.next = (cto & mask)
                    # leaf.next = leaves[cto & mask]
                    filled.next = False
                    cur_next.next = instantMaxBit + 1
                    # print(cur_next, mask, leaf, maxBits)
                # elif get_bits(leaf) >= cur_next:
                elif get_bits(rleaf) >= cur_next:
                    print("CACHE MISS", cur_next)
                    cto = get4(0, maxBits)
                    mask = (1 << cur_next) - 1
                    lraddr.next = (cto & mask)
                    # leaf.next = leaves[cto & mask]
                    filled.next = False
                    cur_next.next = cur_next + 1
                else:
                    # if get_bits(leaf) < 1:
                    if get_bits(rleaf) < 1:
                        print("< 1 bits: ")
                        raise Error("< 1 bits: ")
                    #adv(get_bits(leaf))
                    adv(get_bits(rleaf))
                    """
                    if get_code(leaf) == 0:
                        print("leaf 0", di, isize)
                    """
                    #code.next = get_code(leaf)
                    code.next = get_code(rleaf)
                    # print("ADV:", di, get_bits(leaf), get_code(leaf))
                    if method == 2 and DYNAMIC:
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
                elif not filled:
                    filled.next = True
                elif di >= isize - 4 and not i_mode == IDLE:
                    pass  # fetch more bytes
                elif do >= i_raddr + OBSIZE: # - 10:
                    # print("HOLDB")
                    # filled.next = False
                    pass
                elif di > isize - 3:  # checksum is 4 bytes
                    state.next = d_state.IDLE
                    o_done.next = True
                    print("NO EOF ", di)
                    raise Error("NO EOF!")
                elif code == EndOfBlock:
                    print("EOF:", di, do)
                    if not final:
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
                        if static:
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
                            moreBits = ExtraDistanceBits[distanceCode
                                                            >> 1]
                            distance += get4(extraLength + 5, moreBits)
                            # print("distance2", distance)
                            adv(extraLength + 5 + moreBits)
                            # print("adv", extraLength + 5 + moreBits)
                            offset.next = do - distance
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
                elif not filled:
                    filled.next = True
                elif cur_i == 0 and do + length >= i_raddr + OBSIZE: # - 10:
                    # print("HOLDW", length, offset, cur_i, do, i_raddr)
                    pass
                elif di >= isize - 2:
                    # print("HOLD2")
                    pass
                elif method == 0:
                    if cur_i < length:
                        oaddr.next = do
                        obyte.next = b3
                        adv(8)
                        cur_i.next = cur_i + 1
                        do.next = do + 1
                        o_oprogress.next = do + 1
                    elif not final:
                        adv(16)
                        state.next = d_state.HEADER
                        filled.next = False
                        print("new block")
                    else:
                        o_done.next = True
                        state.next = d_state.IDLE
                elif cur_i < length + 2:
                    # print("L/O", length, offset)
                    oraddr.next = offset + cur_i
                    if cur_i == 1:
                        copy1.next = orbyte
                        # print("c1", cur_i, length, offset, do, orbyte)
                    if cur_i == 3:
                        copy2.next = orbyte
                    if cur_i > 1:
                        # Special 1 byte offset handling:
                        if (offset + cur_i) & OBS == (do + 1) & OBS:
                            obyte.next = copy1
                        elif cur_i == 3 or (offset + cur_i) & OBS != do & OBS:
                            obyte.next = orbyte
                        # Special 2 byte offset handling:
                        elif cur_i > 2:
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
    d.convert()
