"""
MyHDL FPGA Deflate (de)compressor, see RFC 1950/1951

Copyright 2018 by Tom Vijlbrief

See: https://github.com/tomtor

This MyHDL FPGA implementation is partially inspired by the C++ implementation
from https://create.stephan-brumme.com/deflate-decoder

"""

from math import log2

from myhdl import always, block, Signal, intbv, Error, ResetSignal, \
    enum, always_seq, always_comb, concat, ConcatSignal, modbv

IDLE, RESET, WRITE, READ, STARTC, STARTD = range(6)

CWINDOW = 32    # Search window for compression

OBSIZE = 8192   # Size of output buffer (BRAM)
IBSIZE = 4 * CWINDOW  # 2048   # Size of input buffer (LUT-RAM)

if OBSIZE > IBSIZE:
    LBSIZE = log2(OBSIZE)
else:
    LBSIZE = log2(IBSIZE)

IBS = (1 << int(log2(IBSIZE))) - 1

d_state = enum('IDLE', 'HEADER', 'BL', 'READBL', 'REPEAT', 'DISTTREE', 'INIT3',
               'HF1', 'HF1INIT', 'HF2', 'HF3', 'HF4', 'STATIC', 'D_NEXT',
               'D_INFLATE', 'SPREAD', 'NEXT', 'INFLATE', 'COPY', 'CSTATIC',
               'SEARCH', 'DISTANCE', 'CHECKSUM') # , encoding='one_hot')

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


@block
def deflate(i_mode, o_done, i_data, o_iprogress, o_oprogress, o_byte, i_addr, clk, reset):

    """ Deflate (de)compress

    Ports:

    """

    iram = [Signal(intbv()[8:]) for _ in range(IBSIZE)]
    oram = [Signal(intbv()[8:]) for _ in range(OBSIZE)]

    oaddr = Signal(intbv()[LBSIZE:])
    oraddr = Signal(intbv()[LBSIZE:])
    obyte = Signal(intbv()[8:])
    orbyte = Signal(intbv()[8:])
    ocopy = Signal(bool())
    iraddr = Signal(intbv()[LBSIZE:])

    isize = Signal(intbv()[LBSIZE:])
    state = Signal(d_state.IDLE)
    method = Signal(intbv()[3:])
    final = Signal(bool())
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
    BITBITS = 9

    codeLength = [Signal(intbv()[4:]) for _ in range(MaxBitLength+2)]
    bitLengthCount = [Signal(intbv()[9:]) for _ in range(MaxCodeLength+1)]
    nextCode = [Signal(intbv()[CODEBITS:]) for _ in range(MaxCodeLength)]
    reverse = Signal(intbv()[CODEBITS:])
    HF4_init = Signal(bool())
    code_bits = [Signal(intbv()[9:]) for _ in range(MaxBitLength)]
    distanceLength = [Signal(intbv()[4:]) for _ in range(32)]

    leaves = [Signal(intbv()[CODEBITS + BITBITS:]) for _ in range(512)]
    d_leaves = [Signal(intbv()[CODEBITS + BITBITS:]) for _ in range(128)]
    leaf = Signal(intbv()[CODEBITS + BITBITS:])

    minBits = Signal(intbv()[5:])
    maxBits = Signal(intbv()[5:])
    d_maxBits = Signal(intbv()[5:])
    instantMaxBit = Signal(intbv()[InstantMaxBit:])
    d_instantMaxBit = Signal(intbv()[InstantMaxBit:])
    instantMask = Signal(intbv()[MaxCodeLength:])
    d_instantMask = Signal(intbv()[MaxCodeLength:])
    spread = Signal(intbv()[10:])
    step = Signal(intbv()[10:])

    static = Signal(bool())

    code = Signal(intbv()[15:])
    lastToken = Signal(intbv()[15:])
    howOften = Signal(intbv()[9:])

    cur_i = Signal(intbv()[LBSIZE:])
    spread_i = Signal(intbv()[9:])
    cur_HF1 = Signal(intbv()[10:])
    cur_cstatic = Signal(intbv()[LBSIZE:])
    cur_search = Signal(intbv(min=-CWINDOW,max=IBSIZE))
    cur_dist = Signal(intbv(min=-CWINDOW,max=IBSIZE))
    cur_next = Signal(intbv()[5:])

    length = Signal(intbv()[LBSIZE:])
    offset = Signal(intbv()[LBSIZE:])

    di = Signal(intbv()[LBSIZE:])
    old_di = Signal(intbv()[LBSIZE:])
    dio = Signal(intbv()[3:])
    do = Signal(intbv()[LBSIZE:])
    doo = Signal(intbv()[3:])

    b1 = Signal(intbv()[8:])
    b2 = Signal(intbv()[8:])
    b3 = Signal(intbv()[8:])
    b4 = Signal(intbv()[8:])

    b41 = ConcatSignal(b4, b3, b2, b1)
    b41._markUsed()

    nb = Signal(intbv()[3:])

    newnb = Signal(intbv()[3:])
    filled = Signal(bool())

    ob1 = Signal(intbv()[8:])
    flush = Signal(bool(0))

    adler1 = Signal(intbv()[16:])
    adler2 = Signal(intbv()[16:])
    ladler1 = Signal(intbv()[16:])


    @always(clk.posedge)
    def oramwrite():
        oram[oaddr].next = obyte

    #@always_comb
    @always(clk.posedge)
    def oramread():
        orbyte.next = oram[oraddr]

    @always_seq(clk.posedge, reset)
    def fill_buf():
        if not reset:
            nb.next = 0
            old_di.next = 0
            b1.next = 0
            b2.next = 0
            b3.next = 0
            b4.next = 0
        else:
            if isize < 4:
                pass
            elif i_mode == STARTC or i_mode == STARTD:
                nb.next = 0
            else:
                # print("FILL", di, isize)
                nb.next = 4
                b1.next = iram[di & IBS]
                b2.next = iram[di+1 & IBS]
                b3.next = iram[di+2 & IBS]
                b4.next = iram[di+3 & IBS]
    """
    @always_seq(clk.posedge, reset)
    def fill_buf():
        if not reset:
            nb.next = 0
            old_di.next = 0
            b1.next = 0
            b2.next = 0
            b3.next = 0
            b4.next = 0
        else:
            if isize < 4:
                pass
            elif i_mode == STARTC or i_mode == STARTD:
                nb.next = 0
            elif not filled and nb == 4 and di - old_di <= 4:
                delta = di - old_di
                if delta == 1:
                    # print("delta == 1")
                    b1.next = b2
                    b2.next = b3
                    b3.next = b4
                    b4.next = iram[di+3 & IBS]
                elif delta == 2:
                    b1.next = b3
                    b2.next = b4
                    b3.next = iram[di+2 & IBS]
                    nb.next = 3
                elif delta == 3:
                    b1.next = b4
                    b2.next = iram[di+1 & IBS]
                    nb.next = 2
                elif delta == 4:
                    b1.next = iram[di & IBS]
                    nb.next = 1
                else:
                    pass
            elif not filled or nb == 0:
                # print("nb.next = 1")
                b1.next = iram[di & IBS]
                nb.next = 1
            elif not filled or nb == 1:
                b2.next = iram[di+1 & IBS]
                nb.next = 2
            elif not filled or nb == 2:
                b3.next = iram[di+2 & IBS]
                nb.next = 3
            elif not filled or nb == 3:
                b4.next = iram[di+3 & IBS]
                nb.next = 4
            else:
                pass
            old_di.next = di
    """

    def get4(boffset, width):
        if nb != 4:
            print("----NB----")
            raise Error("NB")
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

                if i_mode == WRITE:

                    # print("WRITE:", i_addr, i_data)
                    iram[i_addr & IBS].next = i_data
                    isize.next = i_addr

                elif i_mode == READ:

                    # o_data.next = oram[i_addr]
                    # oraddr.next = i_addr
                    o_byte.next = oram[i_addr]

                else:
                    pass


    @always_seq(clk.posedge, reset)
    def logic():
        if not reset:
            print("DEFLATE RESET")
            state.next = d_state.IDLE
            o_done.next = False
            # oaddr.next = 0
            # obyte.next = 0
        else:

            if state == d_state.IDLE:

                ocopy.next = False

                if i_mode == STARTC:

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
                    state.next = d_state.STATIC

                elif i_mode == STARTD:

                    do_compress.next = False
                    o_done.next = False
                    #di.next = 2
                    di.next = 0
                    dio.next = 0
                    do.next = 0
                    doo.next = 0
                    filled.next = True
                    state.next = d_state.HEADER

                else:
                    pass

            elif state == d_state.HEADER:

                if not filled:
                    filled.next = True
                elif nb < 4:
                    pass
                # Read block header
                elif di == 0:
                    #print(iram[di & IBS])
                    #if iram[di & IBS] == 0x78:
                    if b1 == 0x78:
                        print("deflate mode")
                    else:
                        print(di, dio, nb, b1, b2, b3, b4, isize)
                        raise Error("unexpected mode")
                    adv(8)
                elif di == 1:
                    #print(iram[di & IBS])
                    #if iram[di & IBS] != 0x9c:
                    if b1 != 0x9c:
                        raise Error("unexpected level")
                    adv(8)
                else:
                    if get4(0, 1):
                        print("final")
                        final.next = True
                    i = get4(1, 2)
                    method.next = i
                    print("method", i)
                    print(di, dio, nb, b1, b2, b3, b4, i, isize)
                    if i == 2:
                        state.next = d_state.BL
                        numCodeLength.next = 0
                        numLiterals.next = 0
                        static.next = False
                        adv(3)
                    elif i == 1:
                        static.next = True
                        state.next = d_state.STATIC
                        adv(3)
                    elif i == 0:
                        state.next = d_state.COPY
                        skip = 8 - dio
                        if skip <= 2:
                            skip = 16 - dio
                        i = get4(skip, 16)
                        adv(skip + 16)
                        length.next = i
                        cur_i.next = 0
                        offset.next = 7
                    else:
                        print("Bad method")
                        raise Error("Bad method")

            elif state == d_state.CSTATIC:

                # print("CSTATIC", cur_i, ob1, do, doo, isize)

                no_adv = 0
                if not filled:
                    no_adv = 1
                    filled.next = True
                elif nb < 4:
                    no_adv = 1
                    pass
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
                    print("flush", do, ob1)
                    no_adv = 1
                    oaddr.next = do
                    obyte.next = ob1
                    do_flush()
                elif cur_cstatic - 3 > isize:
                    if cur_cstatic - 3 == isize + 1:
                        print("Put EOF", do)
                        i = EndOfBlock
                        outlen = codeLength[i]
                        outbits = code_bits[i]
                        print("EOF BITS:", i, outlen, outbits)
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
                    elif cur_cstatic - 3 == isize + 4:
                        print("c2")
                        oaddr.next = do
                        obyte.next = adler2 & 0xFF
                        do.next = do + 1
                    elif cur_cstatic - 3 == isize + 5:
                        print("c3")
                        oaddr.next = do
                        obyte.next = adler1 >> 8
                        do.next = do + 1
                    elif cur_cstatic - 3 == isize + 6:
                        print("c4")
                        oaddr.next = do
                        obyte.next = adler1 & 0xFF
                    elif cur_cstatic - 3 == isize + 7:
                        print("EOF finish", do)
                        o_done.next = True
                        o_oprogress.next = do + 1
                        state.next = d_state.IDLE
                    else:
                        print(cur_cstatic, isize)
                        raise Error("???")
                else:
                    bdata = iram[di]
                    # Fix this when > 1 byte output:
                    # print("cs1", bdata)
                    adler1_next = (adler1 + bdata) % 65521
                    adler1.next = adler1_next
                    adler2.next = (adler2 + ladler1) % 65521
                    ladler1.next = adler1_next
                    # print("in: ", bdata, di, isize)
                    state.next = d_state.SEARCH
                    cur_search.next = di - 3

                if not no_adv:
                    cur_cstatic.next = cur_cstatic + 1

            elif state == d_state.DISTANCE:

                if flush:
                    do_flush()
                else:
                    # print("DISTANCE", di, do, cur_i, cur_dist)
                    nextdist = CopyDistance[cur_i+1]
                    if nextdist > cur_dist:
                        print("Found distance", cur_i)
                        copydist = CopyDistance[cur_i]
                        extra_dist = cur_dist - copydist
                        # print("extra dist", extra_dist)
                        extra_bits = ExtraDistanceBits[cur_i // 2]
                        # print("extra bits", extra_bits)
                        if extra_dist > ((1 << extra_bits) - 1):
                            raise Error("too few extra")
                        # print("rev", cur_i, rev_bits(cur_i, 5))
                        outcode = (rev_bits(cur_i, 5) | (extra_dist << 5))
                        # print("outcode", outcode)
                        oaddr.next = do
                        obyte.next = put(outcode, 5 + extra_bits)
                        put_adv(outcode, 5 + extra_bits)
                        #state.next = d_state.CSTATIC
                        cur_i.next = di - length + 1
                        state.next = d_state.CHECKSUM
                    else:
                        cur_i.next = cur_i + 1

            elif state == d_state.CHECKSUM:

                if cur_i < di:
                    # print("CHECKSUM", cur_i, di, iram[cur_i])
                    bdata = iram[cur_i & IBS]
                    adler1_next = (adler1 + bdata) % 65521
                    adler1.next = adler1_next
                    adler2.next = (adler2 + ladler1) % 65521
                    ladler1.next = adler1_next
                    cur_i.next = cur_i.next + 1
                else:
                    state.next = d_state.CSTATIC

            elif state == d_state.SEARCH:

                if not filled:
                    filled.next = True
                elif nb < 4:
                    pass
                else:
                    if cur_search >= 0 \
                             and cur_search >= di - CWINDOW \
                             and di >= 3 and di < isize - 3:
                        if iram[cur_search & IBS] == b1 and \
                                iram[cur_search+1 & IBS] == b2 and \
                                iram[cur_search+2 & IBS] == b3:
                            # Length is 3 code
                            lencode = 257
                            match = 3

                            if di < isize - 4 and \
                                    iram[cur_search+3 & IBS] == b4: # iram[di + 3 & IBS]:
                                lencode = 258
                                match = 4
                                if di < isize - 5 and \
                                        iram[cur_search+4 & IBS] == iram[di + 4 & IBS]:
                                    lencode = 259
                                    match = 5
                            """
                                    if di < isize - 6 and \
                                            iram[cur_search+5 & IBS] == iram[di + 5 & IBS]:
                                        lencode = 260
                                        match = 6
                                        if di < isize - 7 and \
                                                iram[cur_search+6 & IBS] == iram[di + 6 & IBS]:
                                            lencode = 261
                                            match = 7
                                            if di < isize - 8 and \
                                                    iram[cur_search+7 & IBS] == iram[di + 7 & IBS]:
                                                lencode = 262
                                                match = 8
                                                if di < isize - 9 and \
                                                        iram[cur_search+8 & IBS] == iram[di + 8 & IBS]:
                                                    lencode = 263
                                                    match = 9
                                                    if di < isize - 10 and \
                                                            iram[cur_search+9 & IBS] == iram[di + 9 & IBS]:
                                                        lencode = 264
                                                        match = 10
                            """
                            print("found:", cur_search, di, isize, match)
                            outlen = codeLength[lencode]
                            outbits = code_bits[lencode]
                            # print("BITS:", outlen, outbits)
                            oaddr.next = do
                            obyte.next = put(outbits, outlen)
                            put_adv(outbits, outlen)

                            distance = di - cur_search
                            # print("distance", distance)
                            cur_dist.next = distance
                            cur_i.next = 0
                            adv(match * 8)
                            cur_cstatic.next = cur_cstatic + match - 1
                            length.next = match
                            state.next = d_state.DISTANCE
                        else:
                            cur_search.next = cur_search - 1
                    else:
                        bdata = iram[di]
                        adv(8)
                        outlen = codeLength[bdata]
                        outbits = code_bits[bdata]
                        # print("CBITS:", bdata, outlen, outbits)
                        oaddr.next = do
                        obyte.next = put(outbits, outlen)
                        put_adv(outbits, outlen)
                        state.next = d_state.CSTATIC

            elif state == d_state.STATIC:

                for i in range(0, 144):
                    codeLength[i].next = 8
                for i in range(144, 256):
                    codeLength[i].next = 9
                for i in range(256, 280):
                    codeLength[i].next = 7
                for i in range(280, 288):
                    codeLength[i].next = 8
                numCodeLength.next = 288
                cur_HF1.next = 0
                state.next = d_state.HF1

            elif state == d_state.BL:

                if not filled:
                    filled.next = True
                elif nb < 4:
                    pass
                elif numLiterals == 0:
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
                        i = CodeLengthOrder[numCodeLength]
                        # print("CLI: ", i)
                        if numCodeLength < b_numCodeLength:
                            codeLength[i].next = get4(0, 3)
                            adv(3)
                        else:
                            # print("SKIP")
                            codeLength[i].next = 0
                        numCodeLength.next = numCodeLength + 1
                    else:
                        numCodeLength.next = CodeLengths
                        cur_HF1.next = 0
                        state.next = d_state.HF1

            elif state == d_state.READBL:

                if not filled:
                    filled.next = True
                elif nb < 4:
                    pass
                elif numCodeLength < numLiterals + numDistance:
                    # print(numLiterals + numDistance, numCodeLength)
                    i = 0
                    if code < 16:
                        howOften.next = 1
                        lastToken.next = code
                    elif code == 16:
                        howOften.next = 3 + get4(0, 2)
                        i = 2
                    elif code == 17:
                        howOften.next = 3 + get4(0, 3)
                        lastToken.next = 0
                        i = 3
                    elif code == 18:
                        howOften.next = 11 + get4(0, 7)
                        lastToken.next = 0
                        i = 7
                    else:
                        raise Error("Invalid data")

                    # print(numCodeLength, howOften, code, di, i)
                    if i != 0:
                        adv(i)

                    state.next = d_state.REPEAT
                else:
                    print("FILL UP")

                    for i in range(32):
                        dbl = 0
                        if i + numLiterals < numCodeLength:
                            dbl = int(codeLength[i + numLiterals])
                        # print("dbl:", dbl)
                        distanceLength[i].next = dbl

                    # print(numCodeLength, numLiterals, MaxBitLength)

                    cur_i.next = numLiterals
                    state.next = d_state.INIT3

            elif state == d_state.INIT3:

                    if cur_i < MaxBitLength:
                        codeLength[cur_i].next = 0
                        cur_i.next = cur_i + 1
                    else:
                        numCodeLength.next = MaxBitLength
                        method.next = 3  # Start building bit tree
                        cur_HF1.next = 0
                        state.next = d_state.HF1

            elif state == d_state.DISTTREE:

                print("DISTTREE")
                for i in range(32):
                    codeLength[i].next = distanceLength[i]
                    # print(i, distanceLength[i])
                numCodeLength.next = 32
                method.next = 4  # Start building dist tree
                # cur_i.next = 0
                cur_HF1.next = 0
                state.next = d_state.HF1

            elif state == d_state.REPEAT:

                # print("HOWOFTEN: ", numCodeLength, howOften)
                if howOften != 0:
                    codeLength[numCodeLength].next = lastToken
                    howOften.next = howOften - 1
                    numCodeLength.next = numCodeLength + 1
                elif numCodeLength < numLiterals + numDistance:
                    cur_next.next = 0
                    state.next = d_state.NEXT
                else:
                    state.next = d_state.READBL

            elif state == d_state.HF1:

                if cur_HF1 < len(bitLengthCount):
                    bitLengthCount[cur_HF1].next = 0
                if cur_HF1 < len(d_leaves):
                    d_leaves[cur_HF1].next = 0
                if method != 4 and cur_HF1 < len(leaves):
                    leaves[cur_HF1].next = 0
                limit = len(leaves)
                if method == 4:
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
                if cur_i < numCodeLength:
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
                if cur_i <= MaxCodeLength:
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
                    if method == 4:
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
                    for i in range(len(nextCode)):
                        nextCode[i].next = 0
                    print("to HF3")

            elif state == d_state.HF3:
                # find bit code for first element of each bitLength group

                # print("HF3")
                amb = maxBits
                if method == 4:
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
                    HF4_init.next = 0
                    print("to HF4")

            elif state == d_state.HF4:
                # create binary codes for each literal

                if spread_i < numCodeLength:
                    bits = codeLength[spread_i]
                    if bits != 0:
                        if HF4_init == 0:
                            canonical = nextCode[bits]
                            nextCode[bits].next = nextCode[bits] + 1
                            if bits > MaxCodeLength:
                                raise Error("too many bits: %d" % bits)
                            # print(canonical, bits)
                            reverse.next = rev_bits(canonical, bits)
                            # print("LEAF: ", spread_i, bits, reverse, canonical)
                            leaf.next = makeLeaf(spread_i, bits)
                            HF4_init.next = 1
                        elif method == 4:
                            d_leaves[reverse].next = leaf # makeLeaf(spread_i, bits)
                            if bits <= d_instantMaxBit:
                                if reverse + (1 << bits) <= d_instantMask:
                                    step.next = 1 << bits
                                    spread.next = reverse + (1 << bits)
                                    state.next = d_state.SPREAD
                                else:
                                    spread_i.next = spread_i + 1
                            else:
                                spread_i.next = spread_i + 1
                            HF4_init.next = 0
                        else:
                            leaves[reverse].next = leaf # makeLeaf(spread_i, bits)
                            code_bits[spread_i].next = reverse
                            if bits <= instantMaxBit:
                                if reverse + (1 << bits) <= instantMask:
                                    step.next = 1 << bits
                                    spread.next = reverse + (1 << bits)
                                    state.next = d_state.SPREAD
                                else:
                                    spread_i.next = spread_i + 1
                            else:
                                spread_i.next = spread_i + 1
                            HF4_init.next = 0
                    else:
                        spread_i.next = spread_i + 1
                else:
                    if do_compress:
                        state.next = d_state.CSTATIC
                        cur_cstatic.next = 0
                    elif method == 3:
                        state.next = d_state.DISTTREE
                    elif method == 4:
                        print("DEFLATE m2!")
                        state.next = d_state.NEXT
                    elif method == 2:
                        numCodeLength.next = 0
                        state.next = d_state.NEXT
                    else:
                        state.next = d_state.NEXT
                    cur_next.next = 0
                    cur_i.next = 0

            elif state == d_state.SPREAD:

                if method == 4:
                    # print(spread, spread_i)
                    d_leaves[spread].next = makeLeaf(
                        spread_i, codeLength[spread_i])
                else:
                    leaves[spread].next = makeLeaf(
                        spread_i, codeLength[spread_i])
                # print("SPREAD:", spread, step, instantMask)
                aim = instantMask
                if method == 4:
                    aim = d_instantMask
                if spread > aim - step:
                    spread_i.next = spread_i + 1
                    state.next = d_state.HF4
                else:
                    spread.next = spread + step

            elif state == d_state.NEXT:

                if not filled:
                    filled.next = True
                elif nb < 4:
                    pass
                elif cur_next == 0:
                    # print("INIT:", di, dio, instantMaxBit, maxBits)
                    if instantMaxBit <= maxBits:
                        cto = get4(0, maxBits)
                        cur_next.next = instantMaxBit
                        mask = (1 << instantMaxBit) - 1
                        leaf.next = leaves[cto & mask]
                        # print(cur_next, mask, leaf, maxBits)
                    else:
                        print("FAIL instantMaxBit <= maxBits")
                        raise Error("FAIL instantMaxBit <= maxBits")
                elif cur_next <= maxBits:
                    # print("NEXT:", cur_next)
                    if get_bits(leaf) <= cur_next:
                        if get_bits(leaf) < 1:
                            print("< 1 bits: ")
                            raise Error("< 1 bits: ")
                        adv(get_bits(leaf))
                        if get_code(leaf) == 0:
                            print("leaf 0")
                        code.next = get_code(leaf)
                        # print("ADV:", di, get_bits(leaf), get_code(leaf))
                        if method == 2:
                            state.next = d_state.READBL
                        else:
                            state.next = d_state.INFLATE
                    else:
                        print("FAIL get_bits(leaf) <= cur_next")
                        raise Error("?")
                else:
                    print("no next token")
                    raise Error("no next token")

            elif state == d_state.D_NEXT:

                if not filled:
                    filled.next = True
                elif nb < 4:
                    pass
                elif cur_next == 0:
                    # print("D_INIT:", di, dio, d_instantMaxBit, d_maxBits)
                    if d_instantMaxBit <= d_maxBits:
                        token = code - 257
                        # print("token: ", token)
                        extraLength = ExtraLengthBits[token]
                        # print("extra length bits:", extraLength)
                        cto = get4(extraLength, d_maxBits)
                        cur_next.next = d_instantMaxBit
                        mask = (1 << d_instantMaxBit) - 1
                        leaf.next = d_leaves[cto & mask]
                        # print(cur_next, mask, leaf, d_maxBits)
                    else:
                        raise Error("???")

                elif cur_next <= d_maxBits:
                    if get_bits(leaf) <= cur_next:
                        if get_bits(leaf) == 0:
                            raise Error("0 bits")
                        token = code - 257
                        # print("E2:", token, leaf)
                        tlength = CopyLength[token]
                        # print("tlength:", tlength)
                        extraLength = ExtraLengthBits[token]
                        # print("extra length bits:", extraLength)
                        tlength += get4(0, extraLength)
                        # print("extra length:", tlength)
                        distanceCode = get_code(leaf)
                        # print("distance code:", distanceCode)
                        distance = CopyDistance[distanceCode]
                        # print("distance:", distance)
                        moreBits = ExtraDistanceBits[distanceCode >> 1]
                        # print("more bits:", moreBits)
                        # print("bits:", get_bits(leaf))
                        mored = get4(extraLength + get_bits(leaf), moreBits)
                        # print("mored:", mored)
                        distance += mored
                        # print("distance more:", distance)
                        adv(moreBits + extraLength + get_bits(leaf))
                        # print("offset:", do - distance)
                        # print("FAIL?: ", di, dio, do, b1, b2, b3, b4)
                        offset.next = do - distance
                        length.next = tlength
                        # cur_next.next = 0
                        cur_i.next = 0
                        state.next = d_state.COPY

                    else:
                        raise Error("?")
                else:
                    raise Error("no next token")

            elif state == d_state.INFLATE:

                    if not filled:
                        filled.next = True
                    elif nb < 4:  # nb <= 2 or (nb == 3 and dio > 1):
                        # print("EXTRA FETCH", nb, dio)
                        pass  # fetch more bytes
                    elif di > isize - 3:  # checksum is 4 bytes
                        state.next = d_state.IDLE
                        o_done.next = True
                        print("NO EOF ", di)
                        raise Error("NO EOF!")
                    elif code == EndOfBlock:
                        print("EOF:", di, do)
                        if not final:
                            state.next = d_state.HEADER
                        else:
                            o_done.next = True
                            o_oprogress.next = do
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
                                state.next = d_state.COPY
                            else:
                                # raise Error("TO DO")
                                state.next = d_state.D_NEXT
                        cur_next.next = 0

            elif state == d_state.COPY:

                if not filled:
                    filled.next = True
                elif nb < 4:
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
                        state.next = d_state.HEADER
                    else:
                        o_oprogress.next = do # + 1
                        o_done.next = True
                        state.next = d_state.IDLE
                elif cur_i < length + 1:
                    oraddr.next = offset + cur_i
                    cur_i.next = cur_i + 1
                    if cur_i > 1:
                        # print("byte", orbyte)
                        oaddr.next = do
                        obyte.next = orbyte
                        o_oprogress.next = do + 1
                        do.next = do + 1
                else:
                    oaddr.next = do
                    obyte.next = orbyte
                    do.next = do + 1
                    o_oprogress.next = do + 1
                    cur_next.next = 0
                    state.next = d_state.NEXT

            else:

                print("unknow state?!")
                state.next = d_state.IDLE

    return io_logic, logic, fill_buf, oramwrite, oramread


if __name__ == "__main__":
    d = deflate(Signal(intbv()[3:]), Signal(bool(0)),
                Signal(intbv()[8:]), Signal(intbv()[LBSIZE:]),
                Signal(intbv()[LBSIZE:]),
                Signal(intbv()[8:]), Signal(intbv()[LBSIZE:]),
                Signal(bool(0)), ResetSignal(1, 0, True))
    d.convert()
