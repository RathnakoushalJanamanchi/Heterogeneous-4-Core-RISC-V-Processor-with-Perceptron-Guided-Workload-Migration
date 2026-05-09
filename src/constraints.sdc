# =============================================================
#  constraints.sdc — hetero_4core_top
#  PDK  : sky130A (sky130_fd_sc_hd)
#  Tool : OpenLane / OpenROAD / OpenSTA
#  Clock: 50 MHz  (20 ns period)
# =============================================================

# ── 1. PRIMARY CLOCK ─────────────────────────────────────────
create_clock -name clk \
             -period 20.0 \
             -waveform {0 10} \
             [get_ports clk]

# ── 2. CLOCK UNCERTAINTY ─────────────────────────────────────
set_clock_uncertainty -setup 0.5 [get_clocks clk]
set_clock_uncertainty -hold  0.2 [get_clocks clk]

# ── 3. CLOCK TRANSITION ──────────────────────────────────────
set_clock_transition 0.15 [get_clocks clk]

# ── 4. INPUT DELAYS ──────────────────────────────────────────
set_input_delay -clock clk -max 8.0 [get_ports therm_pcore]
set_input_delay -clock clk -min 1.0 [get_ports therm_pcore]

set_input_delay -clock clk -max 8.0 [get_ports therm_ecore]
set_input_delay -clock clk -min 1.0 [get_ports therm_ecore]

set_input_delay -clock clk -max 2.0 [get_ports rst]
set_input_delay -clock clk -min 0.5 [get_ports rst]

# ── 5. OUTPUT DELAYS ─────────────────────────────────────────
set_output_delay -clock clk -max 6.0 [get_ports pd_pcore_en]
set_output_delay -clock clk -min 0.5 [get_ports pd_pcore_en]

set_output_delay -clock clk -max 6.0 [get_ports pd_ecore_en]
set_output_delay -clock clk -min 0.5 [get_ports pd_ecore_en]

set_output_delay -clock clk -max 6.0 [get_ports pd_l2_retain]
set_output_delay -clock clk -min 0.5 [get_ports pd_l2_retain]

set_output_delay -clock clk -max 6.0 [get_ports pd_aes_en]
set_output_delay -clock clk -min 0.5 [get_ports pd_aes_en]

set_output_delay -clock clk -max 6.0 [get_ports {migration_state[0]}]
set_output_delay -clock clk -min 0.5 [get_ports {migration_state[0]}]
set_output_delay -clock clk -max 6.0 [get_ports {migration_state[1]}]
set_output_delay -clock clk -min 0.5 [get_ports {migration_state[1]}]

# ── 6. INPUT DRIVE STRENGTH ──────────────────────────────────
set_driving_cell -lib_cell sky130_fd_sc_hd__buf_2 \
                 -pin X \
                 [get_ports {therm_pcore therm_ecore rst}]

# ── 7. OUTPUT LOAD ───────────────────────────────────────────
set_load 0.01 [get_ports pd_pcore_en]
set_load 0.01 [get_ports pd_ecore_en]
set_load 0.01 [get_ports pd_l2_retain]
set_load 0.01 [get_ports pd_aes_en]
set_load 0.01 [get_ports {migration_state[0]}]
set_load 0.01 [get_ports {migration_state[1]}]

# ── 8. FALSE PATHS ───────────────────────────────────────────
# Async reset — no setup/hold analysis needed
set_false_path -from [get_ports rst]

# pd_aes_en is hardwired 1 — combinational constant, no timing path
set_false_path -to [get_ports pd_aes_en]

# ── END OF SDC ───────────────────────────────────────────────
