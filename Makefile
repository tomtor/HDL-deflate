PYTHON=python3

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

clean:
	rm -f *.vcd
