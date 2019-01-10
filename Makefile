PYTHON=python3.6

MODULES=deflate.py test_deflate.py

all: build test

build: $(MODULES)
	for p in $?; do $(PYTHON) $$p; done

test: icarus

test_fast_bench.v: $(MODULES)
	for p in $?; do $(PYTHON) $$p; done

icarus: test_fast_bench.v
	iverilog -o test_deflate test_fast_bench.v dump.v
	vvp test_deflate

yosys:
	-mv test40.log test40.old.log
	sed -e '/disable MYHDL/d' -e '/\$$finish/d' < test_deflate_bench.v > test40.v
	yosys -p "synth_ice40 -blif test40.blif" test40.v 2>&1 > test40.log
	tail -20 test40.log

pico:
	yosys -p "synth_ice40 -blif test40.blif" picorv32.v 2>&1 > test40.log
	tail -25 test40.log

place:
	#arachne-pnr -d 5k -P sg48 -p upduino_v2.pcf chip.blif -o chip.txt
	arachne-pnr -d 5k -P sg48 test40.blif -o test40.txt

next:
	yosys -p "synth_ice40 -json test40.json" test40.v
	nextpnr-ice40 --up5k --json test40.json --asc test40.asc

time:
	icetime -tmd up5k test40.asc

clean:
	rm -f *.vcd
