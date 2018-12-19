import unittest
import os
import zlib
import random

from myhdl import delay, now, Signal, intbv, ResetSignal, Simulation, \
                  Cosimulation, block, instance, StopSimulation, modbv, \
                  always, always_seq, always_comb, enum, Error

from deflate import IDLE, WRITE, READ, STARTC, STARTD, LBSIZE, IBSIZE, CWINDOW

MAXW = 2 * CWINDOW

COSIMULATION = True
COSIMULATION = False

if not COSIMULATION:
    from deflate import deflate
else:
    def deflate(i_mode, o_done, i_data, o_iprogress, o_oprogress,
                o_byte, i_addr, clk, reset):
        print("Cosimulation")
        cmd = "iverilog -o deflate " + \
              "deflate.v " + \
              "tb_deflate.v "  # "dump.v "
        os.system(cmd)
        return Cosimulation("vvp -m ./myhdl deflate",
                            i_mode=i_mode, o_done=o_done,
                            i_data=i_data, o_iprogress=o_iprogress,
                            o_oprogress=o_oprogress,
                            o_byte=o_byte, i_addr=i_addr,
                            clk=clk, reset=reset)


def test_data(m):
    print("MODE", m)
    if m == 0:
        str_data = " ".join(["Hello World! " + str(1) + " "
                             for i in range(100)])
        b_data = str_data.encode('utf-8')
    elif m == 1:
        str_data = " ".join(["Hello World! " + str(i) + " "
                             for i in range(5)])
        b_data = str_data.encode('utf-8')
    elif m == 2:
        str_data = " ".join(["Hi: " + str(random.randrange(0,0x1000)) + " "
                             for i in range(100)])
        b_data = str_data.encode('utf-8')
    elif m == 3:
        b_data = bytes([random.randrange(0,0x100) for i in range(100)])
    else:
        raise Error("unknown test mode")
    b_data = b_data[:IBSIZE-4]
    zl_data = zlib.compress(b_data)
    print("From %d to %d bytes" % (len(b_data), len(zl_data)))
    print(zl_data)
    return b_data, zl_data


class TestDeflate(unittest.TestCase):

    def testMain(self):

        def test_decompress(i_mode, o_done, i_data, o_iprogress,
                            o_oprogress, o_byte, i_addr, clk, reset):

            def tick():
                clk.next = not clk

            print("")
            print("==========================")
            print("START TEST MODE", mode)
            print("==========================")

            b_data, zl_data = test_data(mode)

            reset.next = 0
            tick()
            yield delay(5)
            reset.next = 1
            tick()
            yield delay(5)

            print("STARTD")
            i_mode.next = STARTD
            tick()
            yield delay(5)
            tick()
            yield delay(5)
            i_mode.next = IDLE

            print("WRITE")
            i_mode.next = WRITE
            i = 0
            while i < len(zl_data):
                if o_iprogress > i - MAXW:
                    print("write", i)
                    i_data.next = zl_data[i]
                    i_addr.next = i
                    i = i + 1
                else:
                    print("Wait for space")
                tick()
                yield delay(5)
                tick()
                yield delay(5)
            i_mode.next = IDLE
            print("Wrote input, wait for end of decompression")

            """
            print("WRITE")
            i_mode.next = WRITE
            for i in range(len(zl_data)):
                i_data.next = zl_data[i]
                i_addr.next = i
                tick()
                yield delay(5)
                tick()
                yield delay(5)
            i_mode.next = IDLE

            print("STARTD")
            i_mode.next = STARTD
            tick()
            yield delay(5)
            tick()
            yield delay(5)
            i_mode.next = IDLE
            """

            print(now())
            while not o_done:
                tick()
                yield delay(5)
                tick()
                yield delay(5)
            print(now())

            last = o_oprogress
            print("GOT", last)
            i_mode.next = READ
            d_data = []
            for i in range(last):
                i_addr.next = i
                tick()
                yield delay(5)
                tick()
                yield delay(5)
                d_data.append(bytes([o_byte]))
            i_mode.next = IDLE

            d_data = b''.join(d_data)

            self.assertEqual(b_data, d_data, "decompress does NOT match")
            print(len(d_data), len(zl_data))

            print("==========COMPRESS TEST=========")

            i_mode.next = WRITE
            for i in range(len(b_data)):
                i_data.next = b_data[i]
                i_addr.next = i
                tick()
                yield delay(5)
                tick()
                yield delay(5)
            i_mode.next = IDLE

            i_mode.next = STARTC
            tick()
            yield delay(5)
            tick()
            yield delay(5)
            i_mode.next = IDLE

            print(now())
            while not o_done:
                tick()
                yield delay(5)
                tick()
                yield delay(5)
            print(now())

            # raise Error("STOP")

            last = o_oprogress
            print("last", last)
            i_mode.next = READ
            c_data = []
            for i in range(last):
                i_addr.next = i
                tick()
                yield delay(5)
                tick()
                yield delay(5)
                c_data.append(bytes([o_byte]))
            i_mode.next = IDLE

            print("b_data:", len(b_data), b_data)
            c_data = b''.join(c_data)
            print("c_data:", len(c_data), c_data)
            print("zl_data:", len(zl_data), zl_data)

            print("zlib test:", zlib.decompress(c_data))

            print("WRITE COMPRESSED RESULT")
            i_mode.next = WRITE
            for i in range(len(c_data)):
                i_data.next = c_data[i]
                i_addr.next = i
                tick()
                yield delay(5)
                tick()
                yield delay(5)
            i_mode.next = IDLE

            print("STARTD after Compress")
            i_mode.next = STARTD
            tick()
            yield delay(5)
            tick()
            yield delay(5)
            i_mode.next = IDLE

            print(now())
            while not o_done:
                tick()
                yield delay(5)
                tick()
                yield delay(5)
            print(now())

            last = o_oprogress
            i_mode.next = READ
            d_data = []
            for i in range(last):
                i_addr.next = i
                tick()
                yield delay(5)
                tick()
                yield delay(5)
                d_data.append(bytes([o_byte]))
            i_mode.next = IDLE

            d_data = b''.join(d_data)

            self.assertEqual(b_data, d_data, "decompress after compress does NOT match")
            print(len(b_data), len(zl_data), len(c_data))

        for loop in range(1):
            for mode in range(4):
                self.runTests(test_decompress)

    def runTests(self, test):
        """Helper method to run the actual tests."""

        i_mode = Signal(intbv(0)[3:])
        o_done = Signal(bool(0))

        i_data = Signal(intbv()[8:])
        o_byte = Signal(intbv()[8:])
        o_iprogress = Signal(intbv()[LBSIZE:])
        o_oprogress = Signal(intbv()[LBSIZE:])
        i_addr = Signal(intbv()[LBSIZE:])

        clk = Signal(bool(0))
        reset = ResetSignal(1, 0, True)

        dut = deflate(i_mode, o_done, i_data, o_iprogress, o_oprogress,
                      o_byte, i_addr, clk, reset)

        check = test(i_mode, o_done, i_data, o_iprogress, o_oprogress,
                     o_byte, i_addr, clk, reset)
        sim = Simulation(dut, check)
        # traceSignals(dut)
        sim.run(quiet=1)


SLOWDOWN = 1

@block
def test_deflate_bench(i_clk, o_led, led0_g, led1_b, led2_r):

    u_data, c_data = test_data(1)

    CDATA = tuple(c_data)
    UDATA = tuple(u_data)

    d_data = [Signal(intbv()[8:]) for _ in range(len(u_data))]

    i_mode = Signal(intbv(0)[3:])
    o_done = Signal(bool(0))

    i_data = Signal(intbv()[8:])
    o_byte = Signal(intbv()[8:])
    u_data = Signal(intbv()[8:])
    o_iprogress = Signal(intbv()[LBSIZE:])
    o_oprogress = Signal(intbv()[LBSIZE:])
    resultlen = Signal(intbv()[LBSIZE:])
    i_addr = Signal(intbv()[LBSIZE:])

    reset = ResetSignal(1, 0, True)

    dut = deflate(i_mode, o_done, i_data, o_iprogress, o_oprogress,
                  o_byte, i_addr, i_clk, reset)

    tb_state = enum('RESET', 'START', 'WRITE', 'DECOMPRESS', 'WAIT', 'VERIFY',
                    'PAUSE', 'CWRITE', 'COMPRESS', 'CWAIT', 'CRESULT',
                    'VWRITE', 'VDECOMPRESS', 'VWAIT', 'CVERIFY', 'CPAUSE',
                    'FAIL', 'HALT')
    tstate = Signal(tb_state.RESET)

    tbi = Signal(modbv(0)[15:])
    # ud = Signal(intbv()[8:])

    scounter = Signal(modbv(0)[SLOWDOWN:])
    counter = Signal(modbv(0)[16:])

    wtick = Signal(bool(0))

    resume = Signal(modbv(0)[6:])

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
            reset.next = 0
            led0_g.next = 0
            led1_b.next = 0
            led2_r.next = 0
            tbi.next = 0
            tstate.next = tb_state.START

        elif SLOWDOWN > 2 and scounter != 0:
            pass

        elif tstate == tb_state.START:
            # A few cycles reset low
            if tbi < 1:
                tbi.next = tbi.next + 1
            else:
                reset.next = 1
                tstate.next = tb_state.WRITE
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
                # o_led.next = tbi
                led1_b.next = o_done
                led2_r.next = not led2_r
                i_mode.next = WRITE
                i_data.next = CDATA[tbi]
                i_addr.next = tbi
                tbi.next = tbi + 1
            else:
                i_mode.next = IDLE
                led2_r.next = 0
                tstate.next = tb_state.DECOMPRESS

        elif tstate == tb_state.DECOMPRESS:
            i_mode.next = STARTD
            tstate.next = tb_state.WAIT

        elif tstate == tb_state.WAIT:
            led1_b.next = not led1_b
            i_mode.next = IDLE
            if i_mode == IDLE and o_done:
                print("result len", o_oprogress)
                if o_oprogress == 0x4F:
                    tstate.next = tb_state.HALT
                resultlen.next = o_oprogress
                tbi.next = 0
                i_addr.next = 0
                i_mode.next = READ
                wtick.next = True
                tstate.next = tb_state.VERIFY
                """
                if o_oprogress == 0x4F:
                    tstate.next = tb_state.HALT
                else:
                    tstate.next = tb_state.FAIL
                """

        elif tstate == tb_state.VERIFY:
            # print("VERIFY", o_data)
            led1_b.next = 0
            # o_led.next = tbi
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
                d_data[tbi].next = o_byte
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
                i_addr.next = tbi + 1
                tbi.next = tbi + 1
                wtick.next = True
            else:
                print(len(UDATA))
                print("DECOMPRESS test OK!, pausing", tbi)
                i_mode.next = IDLE
                tbi.next = 0
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
            # o_led.next = tbi
            if tbi < len(UDATA):
                # print(tbi)
                led2_r.next = 0
                led1_b.next = not led1_b
                i_mode.next = WRITE
                i_data.next = UDATA[tbi]
                i_addr.next = tbi
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
                print("WAIT COMPRESS")
                i_mode.next = IDLE
                led1_b.next = 0
            elif o_done:
                print("result len", o_oprogress)
                resultlen.next = o_oprogress
                tbi.next = 0
                i_addr.next = 0
                i_mode.next = READ
                tstate.next = tb_state.CRESULT
                wtick.next = True

        # verify compression
        elif tstate == tb_state.CRESULT:
            # print("GET COMPRESS RESULT", tbi, o_data)
            led2_r.next = 0
            # o_led.next = tbi
            if wtick:
                wtick.next = False
            elif tbi < resultlen:
                led1_b.next = not led1_b
                if tbi >= 0:
                    d_data[tbi].next = o_byte
                tbi.next = tbi + 1
                i_addr.next = tbi + 1
                wtick.next = True
            else:
                print("Compress bytes read", resultlen, tbi - 1)
                i_mode.next = IDLE
                tbi.next = 0
                tstate.next = tb_state.VWRITE

        elif tstate == tb_state.VWRITE:
            led1_b.next = 0
            # o_led.next = tbi
            if tbi < resultlen:
                # print(tbi, d_data[tbi])
                led2_r.next = not led2_r
                i_mode.next = WRITE
                i_data.next = d_data[tbi]
                i_addr.next = tbi
                tbi.next = tbi + 1
            else:
                print("did write compress bytes", tbi)
                i_mode.next = IDLE
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
                i_addr.next = 0
                i_mode.next = READ
                wtick.next = True
                tstate.next = tb_state.CVERIFY

        elif tstate == tb_state.CVERIFY:
            # print("COMPRESS VERIFY", tbi, o_byte)
            led1_b.next = 0
            led2_r.next = not led2_r
            # o_led.next = tbi
            if wtick:
                wtick.next = False
            elif tbi < len(UDATA):
                ud2 = UDATA[tbi]
                # print(tbi, o_byte, ud2)
                d_data[tbi].next = o_byte
                if o_byte != ud2:
                    tstate.next = tb_state.RESET
                    i_mode.next = IDLE
                    print("FAIL", len(UDATA), tbi, ud2, o_byte)
                    raise Error("bad result")
                    tstate.next = tb_state.FAIL
                tbi.next = tbi + 1
                i_addr.next = tbi + 1
                wtick.next = True
            else:
                print(len(UDATA))
                print("ALL OK!", tbi)
                led2_r.next = 0
                i_mode.next = IDLE
                resume.next = 1
                if SLOWDOWN <= 4:
                    raise StopSimulation()
                tstate.next = tb_state.CPAUSE
                # tstate.next = tb_state.HALT

        elif tstate == tb_state.CPAUSE:
            if resume == 0:
                print("--------------RESET-------------")
                o_led.next = o_led + 1
                tstate.next = tb_state.RESET
            else:
                led0_g.next = not led0_g
                resume.next = resume + 1

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
    tb.convert(name="test_fast_bench", initial_values=True)
    """
    os.system("iverilog -o test_deflate " +
              "test_fast_bench.v dump.v; " +
              "vvp test_deflate")
              """
if 1:
    print("Start Unit test")
    unittest.main(verbosity=2)
