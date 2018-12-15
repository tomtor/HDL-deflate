import unittest
import os
import zlib
import random

from myhdl import delay, now, Signal, intbv, ResetSignal, Simulation, \
                  Cosimulation, block, instance, StopSimulation, modbv, \
                  always, always_seq, always_comb, enum, Error

from deflate import IDLE, WRITE, READ, STARTC, STARTD, LBSIZE

COSIMULATION = True
COSIMULATION = False

if not COSIMULATION:
    from deflate import deflate
else:
    def deflate(i_mode, o_done, i_data, o_progress, o_byte, i_addr, clk, reset):
        print("Cosimulation")
        cmd = "iverilog -o deflate " + \
              "deflate.v " + \
              "tb_deflate.v "  # "dump.v "
        os.system(cmd)
        return Cosimulation("vvp -m ./myhdl deflate",
                            i_mode=i_mode, o_done=o_done,
                            i_data=i_data, o_progress=o_progress,
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
                             for i in range(100)])
        b_data = str_data.encode('utf-8')
    elif m == 2:
        str_data = " ".join(["Hi: " + str(random.randrange(0,0x1000)) + " "
                             for i in range(100)])
        b_data = str_data.encode('utf-8')
    elif m == 3:
        b_data = bytes([random.randrange(0,0x100) for i in range(100)])
    else:
        raise Error("unknown test mode")
    zl_data = zlib.compress(b_data)
    print("From %d to %d bytes" % (len(b_data), len(zl_data)))
    print(zl_data)
    return b_data, zl_data


class TestDeflate(unittest.TestCase):

    def testMain(self):

        def test_decompress(i_mode, o_done, i_data, o_progress,
                            o_byte, i_addr, clk, reset):

            def tick():
                clk.next = not clk

            b_data, zl_data = test_data(mode)

            reset.next = 0
            tick()
            yield delay(5)
            reset.next = 1
            tick()
            yield delay(5)

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

            print(now())
            while not o_done:
                tick()
                yield delay(5)
                tick()
                yield delay(5)
            print(now())

            last = o_progress
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

            last = o_progress
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

            last = o_progress
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
        o_progress = Signal(intbv()[LBSIZE:])
        i_addr = Signal(intbv()[LBSIZE:])

        clk = Signal(bool(0))
        reset = ResetSignal(1, 0, True)

        dut = deflate(i_mode, o_done, i_data, o_progress, o_byte, i_addr,
                      clk, reset)

        check = test(i_mode, o_done, i_data, o_progress, o_byte, i_addr,
                     clk, reset)
        sim = Simulation(dut, check)
        # traceSignals(dut)
        sim.run(quiet=1)


SLOWDOWN = 1

@block
def test_deflate_bench(i_clk, o_led, led0_g, led1_b, led2_r):

    d_data = [Signal(intbv()[8:]) for _ in range(2048)]
    u_data, c_data = test_data(1)

    CDATA = tuple(c_data)
    UDATA = tuple(u_data)

    i_mode = Signal(intbv(0)[3:])
    o_done = Signal(bool(0))

    i_data = Signal(intbv()[8:])
    o_byte = Signal(intbv()[8:])
    u_data = Signal(intbv()[8:])
    o_progress = Signal(intbv()[LBSIZE:])
    resultlen = Signal(intbv()[LBSIZE:])
    i_addr = Signal(intbv()[LBSIZE:])

    reset = ResetSignal(1, 0, True)

    dut = deflate(i_mode, o_done, i_data, o_progress, o_byte, i_addr,
                  i_clk, reset)

    tb_state = enum('RESET', 'WRITE', 'DECOMPRESS', 'WAIT', 'VERIFY', 'PAUSE',
                    'CWRITE', 'COMPRESS', 'CWAIT', 'CRESULT', 'VWRITE',
                    'VDECOMPRESS', 'VWAIT', 'CVERIFY', 'CPAUSE', 'FAIL')
    tstate = Signal(tb_state.RESET)

    tbi = Signal(modbv(0)[15:])
    ud = Signal(intbv()[8:])

    scounter = Signal(modbv(0)[SLOWDOWN:])
    counter = Signal(modbv(0)[16:])

    resume = Signal(modbv(0)[18:])


    @instance
    def clkgen():
        reset.next = 0
        i_clk.next = 0
        while True:
            yield delay(5)
            i_clk.next = not i_clk
            if tstate == tb_state.WRITE:
                reset.next = 1

    @always_seq(i_clk.posedge, reset)
    def count():
        if not reset:
            counter.next = 0
            scounter.next = 0
        else:
            o_led.next = counter
            if scounter == 0:
                counter.next = counter + 1
            scounter.next = scounter + 1

    # @always_seq(i_clk.posedge, reset)
    @always(i_clk.posedge)
    def logic():

        if not reset or tstate == tb_state.RESET:
            # led0_g.next = 0
            led1_b.next = 0
            led2_r.next = 0
            tbi.next = 0
            tstate.next = tb_state.WRITE

        elif SLOWDOWN > 1 and scounter != 0:
            pass

        elif tstate == tb_state.FAIL:

            led0_g.next = not led0_g
            led1_b.next = not led1_b
            led2_r.next = not led2_r

        elif tstate == tb_state.WRITE:
            if tbi < len(CDATA):
                # print(tbi)
                led1_b.next = 0
                if scounter == 0:
                    led2_r.next = not led2_r
                i_mode.next = WRITE
                i_data.next = CDATA[tbi]
                i_addr.next = tbi
                tbi.next = tbi + 1
            else:
                i_mode.next = IDLE
                tstate.next = tb_state.DECOMPRESS

        elif tstate == tb_state.DECOMPRESS:
            i_mode.next = STARTD
            tstate.next = tb_state.WAIT

        elif tstate == tb_state.WAIT:
            if i_mode == STARTD:
                print("WAIT")
                i_mode.next = IDLE
                if scounter == 0:
                    led1_b.next = not led1_b
            elif o_done:
                print("result len", o_progress)
                resultlen.next = o_progress
                tstate.next = tb_state.VERIFY
                tbi.next = 0
                i_addr.next = 0
                i_mode.next = READ

        elif tstate == tb_state.VERIFY:
            #print("VERIFY", o_data)
            led1_b.next = 1
            if tbi < len(UDATA)+1:
                led1_b.next = 0
                if scounter == 0:
                    led2_r.next = not led2_r
                if tbi > 0:
                    # print(o_data)
                    d_data[tbi-1].next = o_byte
                    rud = UDATA[tbi-1]
                    if o_byte != rud:
                        tstate.next = tb_state.RESET
                        i_mode.next = IDLE
                        print("FAIL", len(UDATA), tbi, o_byte, rud)
                        tstate.next = tb_state.FAIL
                        raise Error("bad result")
                    else:
                        pass
                        # print(tbi, o_data)
                i_addr.next = tbi + 1
                tbi.next = tbi + 1
            else:
                print(len(UDATA))
                print("DECOMPRESS test OK!, pausing", tbi)
                i_mode.next = IDLE
                tbi.next = 0
                # state.next = tb_state.PAUSE
                # state.next = tb_state.CPAUSE
                tstate.next = tb_state.CWRITE
                resume.next = 1

        elif tstate == tb_state.PAUSE:
            if resume == 0:
                print("--------------COMPRESS-------------")
                tstate.next = tb_state.CWRITE
                tbi.next = 0
            else:
                resume.next = resume + 1

        # COMPRESS

        elif tstate == tb_state.CWRITE:
            if tbi < len(UDATA):
                # print(tbi)
                led2_r.next = 0
                if scounter == 0:
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
            if i_mode == STARTC:
                print("WAIT COMPRESS")
                i_mode.next = IDLE
                led1_b.next = 0
                if scounter == 0:
                    led2_r.next = not led2_r
            elif o_done:
                print("result len", o_progress)
                resultlen.next = o_progress
                tstate.next = tb_state.CRESULT
                tbi.next = 0
                i_addr.next = 0
                i_mode.next = READ

        # verify compression
        elif tstate == tb_state.CRESULT:
            # print("GET COMPRESS RESULT", tbi, o_data)
            led1_b.next = 1
            if tbi < resultlen+1:
                led2_r.next = 0
                if scounter == 0:
                    led1_b.next = not led1_b
                if tbi > 0:
                    d_data[tbi-1].next = o_byte
                tbi.next = tbi + 1
                i_addr.next = tbi + 1
            else:
                print("Compress bytes read", resultlen, tbi - 1)
                i_mode.next = IDLE
                tstate.next = tb_state.VWRITE
                tbi.next = 0

        elif tstate == tb_state.VWRITE:
            if tbi < resultlen:
                # print(tbi, d_data[tbi])
                led1_b.next = 0
                if scounter == 0:
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
            i_mode.next = STARTD
            tstate.next = tb_state.VWAIT

        elif tstate == tb_state.VWAIT:
            if i_mode == STARTD:
                led2_r.next = 0
                if scounter == 0:
                    led1_b.next = not led1_b
                print("WAIT DECOMPRESS VERIFY")
                i_mode.next = IDLE
            elif o_done:
                print("DONE DECOMPRESS VERIFY", o_progress)
                tstate.next = tb_state.CVERIFY
                if scounter == 0:
                    led1_b.next = not led1_b
                tbi.next = 0
                i_addr.next = 0
                i_mode.next = READ

        elif tstate == tb_state.CVERIFY:
            # print("COMPRESS VERIFY", tbi, o_byte)
            led1_b.next = 1
            if tbi < len(UDATA)+1:
                led1_b.next = 0
                if scounter == 0:
                    led2_r.next = not led2_r
                # print(tbi, o_data)
                if tbi > 0:
                    d_data[tbi-1].next = o_byte
                    cud = UDATA[tbi-1]
                    if o_byte != cud:
                        tstate.next = tb_state.RESET
                        i_mode.next = IDLE
                        print("FAIL", len(UDATA), tbi, cud, o_byte)
                        tstate.next = tb_state.FAIL
                        raise Error("bad result")
                tbi.next = tbi + 1
                i_addr.next = tbi + 1
            else:
                print(len(UDATA))
                print("ALL OK!", tbi)
                led0_g.next = not led0_g
                led2_r.next = 0
                i_mode.next = IDLE
                tstate.next = tb_state.CPAUSE
                resume.next = 1
                if SLOWDOWN == 1:
                    raise StopSimulation()

        elif tstate == tb_state.CPAUSE:
            if resume == 0:
                print("--------------RESET-------------")
                tstate.next = tb_state.RESET
            else:
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
    SLOWDOWN = 18 # 24

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
