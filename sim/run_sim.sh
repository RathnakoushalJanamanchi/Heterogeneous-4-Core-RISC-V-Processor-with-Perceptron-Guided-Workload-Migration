#!/bin/bash
set -e

SIM_DIR="/home/ubuntu/OpenLane/designs/hetero_4core/sim"
RTL_FILE="/home/ubuntu/OpenLane/designs/hetero_4core/rtl/hetero_4core.v"

echo "============================================"
echo "  Hetero 4-Core Simulation"
echo "============================================"

# Check prerequisites
command -v iverilog >/dev/null || { echo "ERROR: iverilog not found. Run: sudo apt install iverilog"; exit 1; }
command -v python3  >/dev/null || { echo "ERROR: python3 not found";  exit 1; }
python3 -c "import cocotb" 2>/dev/null || { echo "ERROR: cocotb not installed. Run: pip3 install cocotb"; exit 1; }
echo "[1/3] Prerequisites OK"

# Check RTL file exists
[ -f "$RTL_FILE" ] || { echo "ERROR: RTL file not found at $RTL_FILE"; exit 1; }

# Syntax check
echo "[2/3] Syntax-checking RTL..."
iverilog -g2012 -tnull "$RTL_FILE" && echo "      RTL syntax: PASS" || { echo "      RTL syntax: FAIL"; exit 1; }

# Run simulation
echo "[3/3] Running tests..."
cd "$SIM_DIR"
make SIM=icarus 2>&1 | tee sim_run.log

echo "============================================"
grep -E "PASS|FAIL|Error" sim_run.log | tail -20
echo "Log saved: $SIM_DIR/sim_run.log"
echo "============================================"
