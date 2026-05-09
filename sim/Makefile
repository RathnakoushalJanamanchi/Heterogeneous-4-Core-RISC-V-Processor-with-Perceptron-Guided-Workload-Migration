SIM      ?= icarus
TOPLEVEL  = hetero_4core_top
MODULE    = test_hetero_4core

# ABSOLUTE PATH — no relative path errors
VERILOG_SOURCES = /home/ubuntu/OpenLane/designs/hetero_4core/rtl/hetero_4core.v

include $(shell cocotb-config --makefiles)/Makefile.sim

COMPILE_ARGS += -g2012
COCOTB_RESOLVE_X = ZEROS

clean::
	rm -rf sim_build __pycache__ *.vcd results.xml dump.vcd
