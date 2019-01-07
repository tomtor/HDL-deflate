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
	mv test40.log test40.old.log
	sed -e '/disable MY/d' -e '/\$finish/d' < test_deflate_bench.v > test40.v
	yosys -p "synth_ice40 -blif test40.blif" test40.v 2>&1 > test40.log
	tail -20 test40.log

clean:
	rm -f *.vcd
