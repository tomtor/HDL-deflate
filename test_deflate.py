import unittest
import os
import zlib
import random
import urllib.request

from myhdl import delay, now, Signal, intbv, ResetSignal, Simulation, \
                  Cosimulation, block, instance, StopSimulation, modbv, \
                  always, always_seq, always_comb, enum, Error

from deflate import IDLE, WRITE, READ, STARTC, STARTD, LBSIZE, IBSIZE, \
                    CWINDOW, COMPRESS, DECOMPRESS, OBSIZE, LMAX, LIBSIZE, \
                    DYNAMIC, LOBSIZE, LOWLUT

MAXW = CWINDOW

COSIMULATION = True
COSIMULATION = False

if not COSIMULATION:
    from deflate import deflate
else:
    def deflate(i_mode, o_done, i_data, o_iprogress, o_oprogress,
                o_byte, i_waddr, i_raddr, clk, reset):
        print("Cosimulation")
        cmd = "iverilog -o deflate " + \
              "deflate.v " + \
              "tb_deflate.v "  # "dump.v "
        os.system(cmd)
        return Cosimulation("vvp -m ./myhdl deflate",
                            i_mode=i_mode, o_done=o_done,
                            i_data=i_data, o_iprogress=o_iprogress,
                            o_oprogress=o_oprogress,
                            o_byte=o_byte, i_waddr=i_waddr, i_raddr=i_raddr,
                            clk=clk, reset=reset)


def test_data(m, tlen=100, limit=False):
    print("MODE", m, tlen)
    if m == 0:
        str_data = " ".join(["Hello World! " + str(1) + " "
                             for i in range(tlen)])
        b_data = str_data.encode('utf-8')
    elif m == 1:
        str_data = " ".join(["   Hello World! " + str(i) + "     "
                             for i in range(tlen)])
        b_data = str_data.encode('utf-8')
    elif m == 2:
        str_data = " ".join(["Hi: " + str(random.randrange(0,0x1000)) + " "
                             for i in range(tlen)])
        b_data = str_data.encode('utf-8')
    elif m == 3:
        if DYNAMIC:
            b_data = bytes([random.randrange(0,0x100) for i in range(tlen)])
        else:
            # prevent method 0 (copy mode)
            str_data = " ".join(["   Hello World! " + str(i) + "     "
                             for i in range(tlen)])
            b_data = str_data.encode('utf-8')
    elif m == 4:
        str_data = "".join([str(random.randrange(0,2))
                             for i in range(tlen)])
        b_data = str_data.encode('utf-8')
    elif m == 5:
        str_data = ""
        b_data = str_data.encode('utf-8')
    elif m == 6:
        b_data = urllib.request.urlopen("http://v7f.eu").read()
    elif m == 7:
        b_data = urllib.request.urlopen("https://ajax.googleapis.com/ajax/libs/jquery/1.12.0/jquery.min.js").read()
    else:
        raise Error("unknown test mode")
    # print(str_data)
    if limit:
        b_data = b_data[:IBSIZE - 4 - 10]
    if not DYNAMIC:
        co = zlib.compressobj(strategy=zlib.Z_FIXED,wbits=LOBSIZE)
    else:
        co = zlib.compressobj(wbits=LOBSIZE)
    data1 = co.compress(b_data)
    data2 = co.flush()
    zl_data = data1 + data2
    print("From %d to %d bytes" % (len(b_data), len(zl_data)))
    print(zl_data[:500])
    return b_data, zl_data


class TestDeflate(unittest.TestCase):

    def testMain(self):

        def test_decompress(i_mode, o_done, i_data, o_iprogress,
                            o_oprogress, o_byte, i_waddr, i_raddr, clk, reset):

          def tick():
              clk.next = not clk

          for tloop in range(1):

            print("")
            print("==========================")
            print("START TEST MODE", mode, tloop)
            print("==========================")

            b_data, zl_data = test_data(mode, 2500 if not LOWLUT else 1000)

            if mode == 0:
                reset.next = 1
                tick()
                yield delay(5)
                reset.next = 0
                tick()
                yield delay(5)

            if DECOMPRESS:
                print("=========== STREAMING DECOMPRESS TEST ===========")

                print("STREAM LENGTH", len(zl_data))

                print("CLEAR OLD INPUT")
                i_mode.next = WRITE
                i_waddr.next = 0
                i_raddr.next = 0
                tick()
                yield delay(5)
                tick()
                yield delay(5)

                print("STARTD")
                i_mode.next = STARTD
                tick()
                yield delay(5)
                tick()
                yield delay(5)

                print("WRITE")
                i = 0
                ri = 0
                sresult = []
                start = now()
                wait = 0
                while True:
                    if ri >= 1000 and ri % 10000 == 0:
                        print(ri)
                    if ri < o_oprogress:
                        did_read = 1
                        # print("do read", ri, o_oprogress)
                        i_mode.next = READ
                        i_raddr.next = ri
                        tick()
                        yield delay(5)
                        tick()
                        yield delay(5)
                        ri = ri + 1
                    else:
                        did_read = 0

                    if i < len(zl_data):
                        if o_iprogress > i - MAXW:
                            i_mode.next = WRITE
                            i_waddr.next = i
                            i_data.next = zl_data[i]
                            # print("write", i, zl_data[i])
                            i = i + 1
                        else:
                            # print("Wait for space", i)
                            wait += 1
                    else:
                        i_mode.next = IDLE

                    tick()
                    yield delay(5)
                    tick()
                    yield delay(5)

                    if did_read:
                        # print("read", ri, o_oprogress, o_byte)
                        sresult.append(bytes([o_byte]))

                    if o_done:
                        # print("DONE", o_oprogress, ri)
                        if o_oprogress == ri:
                            break

                i_mode.next = IDLE
                tick()
                yield delay(5)
                tick()
                yield delay(5)

                print("IN/OUT/CYCLES/WAIT", len(zl_data), len(sresult),
                      (now() - start) // 10, wait)
                sresult = b''.join(sresult)
                self.assertEqual(b_data, sresult)
                print("Decompress OK!")

            if COMPRESS:
                print("=========== STREAMING COMPRESS TEST ===========")

                print("CLEAR OLD INPUT")
                i_mode.next = WRITE
                i_waddr.next = 0
                i_raddr.next = 0
                tick()
                yield delay(5)
                tick()
                yield delay(5)

                print("STARTC")
                i_mode.next = STARTC
                tick()
                yield delay(5)
                tick()
                yield delay(5)

                print("WRITE")
                i = 0
                ri = 0
                slen = 10000
                sresult = []
                wait = 0
                start = now()
                while True:
                    if ri < o_oprogress:
                        did_read = 1
                        # print("do read", ri, o_oprogress)
                        i_mode.next = READ
                        i_raddr.next = ri
                        tick()
                        yield delay(5)
                        tick()
                        yield delay(5)
                        if ri % 2500 == 0:
                            print(ri)
                        ri = ri + 1
                    else:
                        did_read = 0

                    if len(b_data) < 4 and i == 0:
                        """
                        Short length input, just write 4 bytes.
                        This is an API limitation!
                        """
                        print("SHORT INPUT")
                        i_mode.next = WRITE
                        i_waddr.next = 4
                        i_data.next = 0
                        i = 1
                    elif i < slen and len(b_data) > 0:
                        if o_iprogress > i - MAXW:
                            i_mode.next = WRITE
                            i_waddr.next = i
                            i_data.next = b_data[i % len(b_data)]
                            # print("write", i, b_data[i % len(b_data)])
                            i = i + 1
                        else:
                            # print("Wait for space", i)
                            wait += 1
                    else:
                        i_mode.next = IDLE

                    tick()
                    yield delay(5)
                    tick()
                    yield delay(5)

                    if did_read:
                        # print("read", ri, o_oprogress, o_byte)
                        sresult.append(bytes([o_byte]))

                    if o_done:
                        # print("DONE", o_oprogress, ri)
                        if o_oprogress == ri:
                            break;

                i_mode.next = IDLE

                print("IN/OUT/CYCLES/WAIT", slen, len(sresult),
                    (now() - start) // 10, wait)
                sresult = b''.join(sresult)
                # print("len sresult", len(sresult))
                rlen = min(len(b_data), slen)
                # print("rlen", rlen)
                # print(sresult)
                self.assertEqual(zlib.decompress(sresult)[:rlen], b_data[:rlen])
                print("zlib test:", zlib.decompress(sresult)[:130])

            print("DONE!")


        for loop in range(1):
            # for mode in range(3,8):
            # for mode in range(8):
            for mode in range(6):
            # for mode in range(4):
                self.runTests(test_decompress)

    def runTests(self, test):
        """Helper method to run the actual tests."""

        i_mode = Signal(intbv(0)[3:])
        o_done = Signal(bool(0))

        i_data = Signal(intbv()[8:])
        o_byte = Signal(intbv()[8:])
        o_iprogress = Signal(intbv()[LMAX:])
        o_oprogress = Signal(intbv()[LMAX:])
        i_waddr = Signal(modbv()[LMAX:])
        i_raddr = Signal(modbv()[LMAX:])

        clk = Signal(bool(0))
        reset = ResetSignal(0, 1, True)

        dut = deflate(i_mode, o_done, i_data, o_iprogress, o_oprogress,
                      o_byte, i_waddr, i_raddr, clk, reset)

        check = test(i_mode, o_done, i_data, o_iprogress, o_oprogress,
                     o_byte, i_waddr, i_raddr, clk, reset)
        sim = Simulation(dut, check)
        # traceSignals(dut)
        sim.run(quiet=1)


SLOWDOWN = 1

@block
def test_deflate_bench(i_clk, o_led, led0_g, led1_b, led2_r):

    u_data, c_data = test_data(1, 100, IBSIZE)

    CDATA = tuple(c_data)
    UDATA = tuple(u_data)

    i_mode = Signal(intbv(0)[3:])
    o_done = Signal(bool(0))

    i_data = Signal(intbv()[8:])
    o_byte = Signal(intbv()[8:])
    o_iprogress = Signal(intbv()[LMAX:])
    o_oprogress = Signal(intbv()[LMAX:])
    resultlen = Signal(intbv()[LMAX:])
    i_waddr = Signal(modbv()[LMAX:])
    i_raddr = Signal(modbv()[LMAX:])

    reset = ResetSignal(0, 1, True)

    dut = deflate(i_mode, o_done, i_data, o_iprogress, o_oprogress,
                  o_byte, i_waddr, i_raddr, i_clk, reset)

    tb_state = enum('RESET', 'START', 'WRITE', 'DECOMPRESS', 'WAIT', 'VERIFY',
                    'PAUSE', 'CWRITE', 'COMPRESS', 'CWAIT', 'CRESULT',
                    'VWRITE', 'VDECOMPRESS', 'VWAIT', 'CVERIFY', 'CPAUSE',
                    'FAIL', 'HALT')
    tstate = Signal(tb_state.RESET)

    tbi = Signal(modbv(0)[15:])
    copy = Signal(intbv()[8:])

    scounter = Signal(modbv(0)[SLOWDOWN:])
    counter = Signal(modbv(0)[16:])

    wtick = Signal(bool(0))

    resume = Signal(modbv(0)[6:])

    start = Signal(intbv(0)[16:])

    @instance
    def clkgen():
        i_clk.next = 0
        while True:
            yield delay(5)
            i_clk.next = not i_clk

    @always(i_clk.posedge)
    def count():
        # o_led.next = counter
        if scounter == 0:
            counter.next = counter + 1
        scounter.next = scounter + 1

    @always(i_clk.posedge)
    def logic():

        if tstate == tb_state.RESET:
            print("RESET", counter)
            reset.next = 1
            led0_g.next = 0
            led1_b.next = 0
            led2_r.next = 0
            tbi.next = 0
            wtick.next = 0
            tstate.next = tb_state.START

        elif SLOWDOWN > 2 and scounter != 0:
            pass

        elif tstate == tb_state.START:
            # A few cycles reset low
            if tbi < 1:
                tbi.next = tbi.next + 1
            else:
                reset.next = 0
                if DECOMPRESS:
                    tstate.next = tb_state.WRITE
                else:
                    tstate.next = tb_state.CWRITE
                tbi.next = 0

        elif tstate == tb_state.HALT:
            led0_g.next = 1
            led2_r.next = 0
            led1_b.next = 0

        elif tstate == tb_state.FAIL:
            # Failure: blink all color leds
            led0_g.next = not led0_g
            led2_r.next = not led2_r
            led1_b.next = o_done

        elif tstate == tb_state.WRITE:
            if tbi < len(CDATA):
                # print(tbi)
                o_led.next = tbi
                led1_b.next = o_done
                led2_r.next = not led2_r
                i_mode.next = WRITE
                i_data.next = CDATA[tbi]
                i_waddr.next = tbi
                tbi.next = tbi + 1
            else:
                i_mode.next = IDLE
                led2_r.next = 0
                tstate.next = tb_state.DECOMPRESS

        elif tstate == tb_state.DECOMPRESS:
            # start.next = now()
            i_mode.next = STARTD
            tstate.next = tb_state.WAIT

        elif tstate == tb_state.WAIT:
            led1_b.next = not led1_b
            i_mode.next = IDLE
            if i_mode == IDLE and o_done:
                # print("FINISH DECOMPRESS IN", (now() - start) // 10)
                print("result len", o_oprogress)
                resultlen.next = o_oprogress
                tbi.next = 0
                i_raddr.next = 0
                i_mode.next = READ
                wtick.next = True
                tstate.next = tb_state.VERIFY

        elif tstate == tb_state.VERIFY:
            # print("VERIFY", o_data)
            led1_b.next = 0
            o_led.next = tbi
            """
            Note that the read can also be pipelined in a tight loop
            without the WTICK delay, but this will not work with
            SLOWDOWN > 1
            """
            if wtick:
                wtick.next = False
            elif tbi < len(UDATA):
                led2_r.next = not led2_r
                ud1= UDATA[tbi]
                # print(o_byte, ud1)
                if o_byte != ud1:
                    i_mode.next = IDLE
                    print("FAIL", len(UDATA), tbi, o_byte, ud1)
                    # resume.next = 1
                    # tstate.next = tb_state.PAUSE
                    tstate.next = tb_state.FAIL
                    # tstate.next = tb_state.RESET
                    raise Error("bad result")
                else:
                    pass
                    # print(tbi, o_data)
                i_raddr.next = tbi + 1
                tbi.next = tbi + 1
                wtick.next = True
            else:
                print(len(UDATA))
                print("DECOMPRESS test OK!, pausing", tbi)
                i_mode.next = IDLE
                tbi.next = 0
                if not COMPRESS:
                    tstate.next = tb_state.CPAUSE
                else:
                    tstate.next = tb_state.PAUSE
                # tstate.next = tb_state.HALT
                # state.next = tb_state.CPAUSE
                resume.next = 1
                # tstate.next = tb_state.CWRITE

        elif tstate == tb_state.PAUSE:
            led2_r.next = 0
            if resume == 0:
                print("--------------COMPRESS-------------")
                tbi.next = 0
                led0_g.next = 0
                tstate.next = tb_state.CWRITE
                # tstate.next = tb_state.RESET
            else:
                led2_r.next = not led2_r
                resume.next = resume + 1

        #####################################
        # COMPRESS TEST
        #####################################

        elif tstate == tb_state.CWRITE:
            o_led.next = tbi
            if tbi < len(UDATA):
                # print(tbi)
                led2_r.next = 0
                led1_b.next = not led1_b
                i_mode.next = WRITE
                i_data.next = UDATA[tbi]
                i_waddr.next = tbi
                tbi.next = tbi + 1
            else:
                print("wrote bytes to compress", tbi)
                i_mode.next = IDLE
                tstate.next = tb_state.COMPRESS

        elif tstate == tb_state.COMPRESS:
            i_mode.next = STARTC
            tstate.next = tb_state.CWAIT

        elif tstate == tb_state.CWAIT:
            led2_r.next = not led2_r
            if i_mode == STARTC:
                # start.next = now()
                print("WAIT COMPRESS")
                i_mode.next = IDLE
                led1_b.next = 0
            elif o_done:
                # print("FINISH COMPRESS IN", (now() - start) // 10)
                print("result len", o_oprogress)
                resultlen.next = o_oprogress
                tbi.next = 0
                i_raddr.next = 0
                i_mode.next = READ
                if not DECOMPRESS:
                    if (o_oprogress == 0x2a        # for CWINDOW = 32
                        or o_oprogress == 0x10f):  # for CWINDOW = 256
                            tstate.next = tb_state.CPAUSE
                            resume.next = 1
                            print("compress OK!")
                    else:
                        print("compress len FAILED", o_oprogress)
                        tstate.next = tb_state.FAIL
                    if SLOWDOWN <= 4:
                        raise StopSimulation()
                else:
                    tstate.next = tb_state.CRESULT
                    wtick.next = True

        # verify compression
        elif tstate == tb_state.CRESULT:
            # print("COPY COMPRESS RESULT", tbi, o_data)
            led2_r.next = 0
            o_led.next = tbi
            if wtick:
                if tbi > 0:
                    i_mode.next = WRITE
                    i_data.next = copy
                    i_waddr.next = tbi - 1
                wtick.next = False
                tbi.next = tbi + 1
            elif tbi < resultlen:
                i_mode.next = READ
                led1_b.next = not led1_b
                i_raddr.next = tbi
                copy.next = o_byte
                wtick.next = True
            else:
                print("Compress output bytes copied to input", resultlen, tbi - 1)
                i_mode.next = IDLE
                tbi.next = 0
                tstate.next = tb_state.VDECOMPRESS

        elif tstate == tb_state.VDECOMPRESS:
            print("start decompress of test compression")
            i_mode.next = STARTD
            tstate.next = tb_state.VWAIT

        elif tstate == tb_state.VWAIT:
            led2_r.next = 0
            led1_b.next = not led1_b
            i_mode.next = IDLE
            if i_mode == IDLE and o_done:
                print("DONE DECOMPRESS VERIFY", o_oprogress)
                tbi.next = 0
                i_raddr.next = 0
                i_mode.next = READ
                wtick.next = True
                tstate.next = tb_state.CVERIFY

        elif tstate == tb_state.CVERIFY:
            # print("COMPRESS VERIFY", tbi, o_byte)
            led1_b.next = 0
            led2_r.next = not led2_r
            o_led.next = tbi
            if wtick:
                wtick.next = False
            elif tbi < len(UDATA):
                ud2 = UDATA[tbi]
                # print(tbi, o_byte, ud2)
                if o_byte != ud2:
                    tstate.next = tb_state.RESET
                    i_mode.next = IDLE
                    print("FAIL", len(UDATA), tbi, ud2, o_byte)
                    raise Error("bad result")
                    tstate.next = tb_state.FAIL
                tbi.next = tbi + 1
                i_raddr.next = tbi + 1
                wtick.next = True
            else:
                print(len(UDATA))
                print("ALL OK!", tbi)
                led2_r.next = 0
                i_mode.next = IDLE
                resume.next = 1
                tstate.next = tb_state.CPAUSE
                # tstate.next = tb_state.HALT

        elif tstate == tb_state.CPAUSE:
            if SLOWDOWN <= 4:
                raise StopSimulation()
            if resume == 0:
                print("--------------RESET-------------")
                o_led.next = o_led + 1
                tstate.next = tb_state.RESET
            else:
                led0_g.next = not led0_g
                resume.next = resume + 1

        else:
            print("test unknown state")
            tstate.next = tb_state.RESET

        """
        if now() > 50000:
            raise StopSimulation()
        """

    if SLOWDOWN == 1:
        return clkgen, dut, count, logic
    else:
        return dut, count, logic


if 1: # not COSIMULATION:
    SLOWDOWN = 22

    tb = test_deflate_bench(Signal(bool(0)), Signal(intbv(0)[4:]),
                        Signal(bool(0)), Signal(bool(0)), Signal(bool(0)))

    tb.convert(initial_values=False)

if 1:
    SLOWDOWN = 1
    tb = test_deflate_bench(Signal(bool(0)), Signal(intbv(0)[4:]),
                            Signal(bool(0)), Signal(bool(0)), Signal(bool(0)))
    print("convert SLOWDOWN: ", SLOWDOWN)
    tb.convert(name="test_fast_bench", initial_values=False)
    """
    os.system("iverilog -o test_deflate " +
              "test_fast_bench.v dump.v; " +
              "vvp test_deflate")
              """
if 1:
    print("Start Unit test")
    unittest.main(verbosity=2)
