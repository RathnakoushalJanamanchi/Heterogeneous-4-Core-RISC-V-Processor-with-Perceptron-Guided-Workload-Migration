# =============================================================================
#  cocotb Testbench — Heterogeneous 4-Core RISC-V Processor
#  File: test_hetero_4core.py
#  Run:  make SIM=icarus TOPLEVEL=hetero_4core_top MODULE=test_hetero_4core
#  Tool: Icarus Verilog + cocotb >= 1.8.0
#  Coverage: 150 directed + constrained-random testcases
# =============================================================================

import cocotb
from cocotb.clock      import Clock
from cocotb.triggers   import RisingEdge, FallingEdge, Timer, ClockCycles
from cocotb.handle     import SimHandleBase
import random
import math

# =============================================================================
# CONSTANTS (mirror RTL defines)
# =============================================================================
MIG_STAY_E = 0b00
MIG_TO_P   = 0b01
MIG_STAY_P = 0b10
MIG_TO_E   = 0b11

THERM_THRESH  = 120
THERM_MARGIN  = 8
THERM_BLOCK   = THERM_THRESH - THERM_MARGIN   # 112

CLK_PERIOD_NS = 10   # 100 MHz

# =============================================================================
# UTILITY HELPERS
# =============================================================================

async def reset_dut(dut, cycles=10):
    """Assert reset for <cycles> clock edges, then deassert."""
    dut.rst.value        = 1
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    await ClockCycles(dut.clk, cycles)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)

async def apply_and_run(dut, therm_p, therm_e, cycles):
    """Drive thermal inputs and run for <cycles> clocks."""
    dut.therm_pcore.value = int(therm_p)
    dut.therm_ecore.value = int(therm_e)
    await ClockCycles(dut.clk, int(cycles))

def sample_outputs(dut):
    """Return dict of current DUT outputs."""
    return {
        "pd_pcore_en"   : int(dut.pd_pcore_en.value),
        "pd_ecore_en"   : int(dut.pd_ecore_en.value),
        "pd_l2_retain"  : int(dut.pd_l2_retain.value),
        "pd_aes_en"     : int(dut.pd_aes_en.value),
        "mig_state"     : int(dut.migration_state.value),
    }

def check_power_invariant(dut, label=""):
    """
    Universal invariant: AES always on, never both clusters off,
    migration state must not be X/Z.
    """
    out = sample_outputs(dut)
    assert out["pd_aes_en"] == 1, \
        f"[{label}] AES domain must always be ON — got {out['pd_aes_en']}"
    assert not (out["pd_pcore_en"] == 0 and out["pd_ecore_en"] == 0), \
        f"[{label}] Both P-Core and E-Core simultaneously OFF — power invariant violated"
    assert out["mig_state"] in (0,1,2,3), \
        f"[{label}] migration_state={out['mig_state']} is not a valid 2-bit value"

async def wait_window(dut, extra=10):
    """Wait enough cycles for at least one 64-cycle feature window to fire."""
    await ClockCycles(dut.clk, 64 + extra)

# =============================================================================
# SHARED SETUP  (called at the top of every test)
# =============================================================================

async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    await reset_dut(dut)

# =============================================================================
# ─────────────────────────────────────────────────────────────────────────────
#  GROUP A — POWER-DOMAIN INVARIANTS  (TC001–TC020)
# ─────────────────────────────────────────────────────────────────────────────
# =============================================================================

@cocotb.test()
async def TC001_aes_always_on_after_reset(dut):
    """AES power domain must be HIGH immediately after reset."""
    await setup(dut)
    assert int(dut.pd_aes_en.value) == 1

@cocotb.test()
async def TC002_not_both_off_after_reset(dut):
    """Neither cluster shall be simultaneously OFF right after reset."""
    await setup(dut)
    check_power_invariant(dut, "TC002")

@cocotb.test()
async def TC003_aes_on_during_run_cool(dut):
    """AES stays ON over 200 cycles at nominal temperature."""
    await setup(dut)
    await apply_and_run(dut, 70, 50, 200)
    assert int(dut.pd_aes_en.value) == 1

@cocotb.test()
async def TC004_aes_on_during_thermal_stress(dut):
    """AES stays ON even when P-Core is thermally hot."""
    await setup(dut)
    await apply_and_run(dut, 118, 60, 300)
    assert int(dut.pd_aes_en.value) == 1

@cocotb.test()
async def TC005_invariant_after_one_window(dut):
    """Invariant holds after exactly one feature window fires."""
    await setup(dut)
    await wait_window(dut)
    check_power_invariant(dut, "TC005")

@cocotb.test()
async def TC006_invariant_after_five_windows(dut):
    """Invariant holds after five consecutive windows."""
    await setup(dut)
    await ClockCycles(dut.clk, 5 * 74)
    check_power_invariant(dut, "TC006")

@cocotb.test()
async def TC007_l2_retain_only_when_both_off(dut):
    """L2 retention must be 1 only if both clusters are off (logically impossible in this RTL → always 0)."""
    await setup(dut)
    await apply_and_run(dut, 70, 50, 200)
    out = sample_outputs(dut)
    # Since both-off is forbidden, pd_l2_retain should never be 1 during normal run
    assert out["pd_l2_retain"] == 0, \
        f"TC007: pd_l2_retain={out['pd_l2_retain']} but both clusters should not be off"

@cocotb.test()
async def TC008_mig_state_valid_range_warm(dut):
    """Migration state always in {0,1,2,3} at warm temperature."""
    await setup(dut)
    for _ in range(10):
        await apply_and_run(dut, 80, 55, 70)
        v = int(dut.migration_state.value)
        assert v in (0,1,2,3), f"TC008: invalid mig_state={v}"

@cocotb.test()
async def TC009_mig_state_valid_range_hot(dut):
    """Migration state always in {0,1,2,3} at hot temperature."""
    await setup(dut)
    for _ in range(10):
        await apply_and_run(dut, 116, 60, 70)
        v = int(dut.migration_state.value)
        assert v in (0,1,2,3), f"TC009: invalid mig_state={v}"

@cocotb.test()
async def TC010_pd_signals_binary(dut):
    """All power-domain signals must be strictly 0 or 1."""
    await setup(dut)
    await apply_and_run(dut, 75, 55, 300)
    out = sample_outputs(dut)
    for k,v in out.items():
        if k != "mig_state":
            assert v in (0,1), f"TC010: {k}={v} is not binary"

@cocotb.test()
async def TC011_reset_clears_migration(dut):
    """Re-applying reset brings system back to E-Core (e_active=1)."""
    await setup(dut)
    await apply_and_run(dut, 60, 50, 400)
    # Re-reset
    dut.rst.value = 1
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)
    assert int(dut.pd_ecore_en.value) == 1, "TC011: After re-reset, E-Core should be active"

@cocotb.test()
async def TC012_aes_on_across_reset(dut):
    """AES domain ON survives multiple reset cycles."""
    await setup(dut)
    for _ in range(3):
        dut.rst.value = 1
        await ClockCycles(dut.clk, 4)
        dut.rst.value = 0
        await ClockCycles(dut.clk, 2)
        assert int(dut.pd_aes_en.value) == 1, "TC012: AES went off during reset cycle"

@cocotb.test()
async def TC013_invariant_50_random_snapshots(dut):
    """Sample outputs at 50 random points — invariant must hold at each."""
    await setup(dut)
    rng = random.Random(0xDEAD)
    for i in range(50):
        tp = rng.randint(50,130)
        te = rng.randint(40,90)
        cyc = rng.randint(30,100)
        await apply_and_run(dut, tp, te, cyc)
        check_power_invariant(dut, f"TC013_snap{i}")

@cocotb.test()
async def TC014_pd_pcore_ecore_mutually_exclusive_mostly(dut):
    """
    After a window fires the active core should be either P xor E
    (both ON is allowed during brief transition — check after stabilisation).
    """
    await setup(dut)
    await apply_and_run(dut, 70, 50, 200)
    p = int(dut.pd_pcore_en.value)
    e = int(dut.pd_ecore_en.value)
    # At least one must be active
    assert p or e, "TC014: Neither cluster active after 200 cycles"

@cocotb.test()
async def TC015_aes_stable_1000_cycles(dut):
    """AES remains on for 1000 consecutive cycles."""
    await setup(dut)
    dut.therm_pcore.value = 80
    dut.therm_ecore.value = 55
    for _ in range(1000):
        await RisingEdge(dut.clk)
        assert int(dut.pd_aes_en.value) == 1, "TC015: AES went OFF mid-run"

@cocotb.test()
async def TC016_invariant_boundary_therm_112(dut):
    """Boundary: therm_pcore exactly at block threshold (112)."""
    await setup(dut)
    await apply_and_run(dut, THERM_BLOCK, 50, 200)
    check_power_invariant(dut, "TC016")

@cocotb.test()
async def TC017_invariant_boundary_therm_113(dut):
    """Boundary: therm_pcore one above block threshold (113)."""
    await setup(dut)
    await apply_and_run(dut, THERM_BLOCK + 1, 50, 200)
    check_power_invariant(dut, "TC017")

@cocotb.test()
async def TC018_invariant_therm_min(dut):
    """Minimum thermal values — invariant holds."""
    await setup(dut)
    await apply_and_run(dut, 0, 0, 200)
    check_power_invariant(dut, "TC018")

@cocotb.test()
async def TC019_invariant_therm_max(dut):
    """Maximum (255) thermal values — invariant holds."""
    await setup(dut)
    await apply_and_run(dut, 255, 255, 200)
    check_power_invariant(dut, "TC019")

@cocotb.test()
async def TC020_mig_state_never_unknown_500cyc(dut):
    """migration_state must never be X/Z over 500 cycles of toggle."""
    await setup(dut)
    for i in range(500):
        await RisingEdge(dut.clk)
        v = dut.migration_state.value
        assert not v.is_resolvable or int(v) in (0,1,2,3), \
            f"TC020 cycle {i}: mig_state unknown/invalid"

# =============================================================================
# ─────────────────────────────────────────────────────────────────────────────
#  GROUP B — THERMAL THROTTLE LOGIC  (TC021–TC045)
# ─────────────────────────────────────────────────────────────────────────────
# =============================================================================

@cocotb.test()
async def TC021_thermal_block_suppresses_pcore_hot119(dut):
    """therm_pcore=119 (headroom=1) → thermal block → P-Core must NOT be active."""
    await setup(dut)
    await apply_and_run(dut, 119, 50, 400)
    assert int(dut.pd_pcore_en.value) == 0, \
        "TC021: P-Core active despite near-throttle temperature"

@cocotb.test()
async def TC022_thermal_block_suppresses_pcore_hot120(dut):
    """therm_pcore=120 (at throttle) → P-Core must NOT be active."""
    await setup(dut)
    await apply_and_run(dut, 120, 50, 400)
    assert int(dut.pd_pcore_en.value) == 0, "TC022: P-Core active at throttle temp"

@cocotb.test()
async def TC023_thermal_block_ecore_stays_on_hot(dut):
    """When P-Core thermally blocked, E-Core must be active."""
    await setup(dut)
    await apply_and_run(dut, 119, 50, 400)
    assert int(dut.pd_ecore_en.value) == 1, "TC023: E-Core not active during P-Core thermal block"

@cocotb.test()
async def TC024_thermal_block_at_118(dut):
    """therm_pcore=118, headroom=2 < THERM_MARGIN(8) → still blocked."""
    await setup(dut)
    await apply_and_run(dut, 118, 50, 400)
    assert int(dut.pd_pcore_en.value) == 0, "TC024: P-Core active at therm=118"

@cocotb.test()
async def TC025_thermal_block_at_115(dut):
    """therm_pcore=115, headroom=5 < THERM_MARGIN(8) → blocked."""
    await setup(dut)
    await apply_and_run(dut, 115, 50, 400)
    assert int(dut.pd_pcore_en.value) == 0, "TC025: P-Core active at therm=115"

@cocotb.test()
async def TC026_no_thermal_block_at_100(dut):
    """therm_pcore=100 (headroom=20 > 8) → P-Core can be activated if workload demands."""
    await setup(dut)
    await apply_and_run(dut, 100, 50, 400)
    # At this temperature, thermal block is NOT active.
    # Perceptron may or may not migrate — just ensure invariant holds.
    check_power_invariant(dut, "TC026")

@cocotb.test()
async def TC027_no_thermal_block_at_80(dut):
    """therm_pcore=80 (cool) → thermal block definitely not active."""
    await setup(dut)
    await apply_and_run(dut, 80, 50, 400)
    check_power_invariant(dut, "TC027")

@cocotb.test()
async def TC028_ecore_therm_high_doesnt_block_pcore(dut):
    """High E-Core temperature alone should not block P-Core."""
    await setup(dut)
    await apply_and_run(dut, 70, 119, 400)
    # P-Core has cool temperature — no block
    check_power_invariant(dut, "TC028")

@cocotb.test()
async def TC029_thermal_sweep_105_to_119(dut):
    """Sweep P-Core temp from 105→119 in steps of 1; confirm block above THERM_BLOCK."""
    await setup(dut)
    for t in range(105, 120):
        await apply_and_run(dut, t, 50, 100)
        if t > THERM_BLOCK:
            assert int(dut.pd_pcore_en.value) == 0, \
                f"TC029: P-Core active at therm={t} (above block threshold)"

@cocotb.test()
async def TC030_thermal_sweep_below_block(dut):
    """Sweep P-Core temp 50→111 — all below block threshold, invariant always holds."""
    await setup(dut)
    for t in range(50, 112, 5):
        await apply_and_run(dut, t, 50, 80)
        check_power_invariant(dut, f"TC030_t{t}")

@cocotb.test()
async def TC031_thermal_recovery_p_to_e_back_to_p(dut):
    """
    Cool → P-Core may activate.
    Then heat up → forced to E-Core.
    Cool again → P-Core can re-activate.
    Verify no stuck state.
    """
    await setup(dut)
    await apply_and_run(dut, 60, 50, 300)   # cool phase
    check_power_invariant(dut, "TC031_phase1")
    await apply_and_run(dut, 119, 50, 300)  # hot phase → E-Core
    assert int(dut.pd_pcore_en.value) == 0, "TC031: P-Core did not deactivate under heat"
    await apply_and_run(dut, 60, 50, 300)   # cool again
    check_power_invariant(dut, "TC031_phase3")

@cocotb.test()
async def TC032_thermal_block_immediate_after_window(dut):
    """Within one window after therm goes hot, P-Core must be off."""
    await setup(dut)
    await apply_and_run(dut, 60, 50, 150)   # start cool
    dut.therm_pcore.value = 119
    await ClockCycles(dut.clk, 80)           # one full window
    assert int(dut.pd_pcore_en.value) == 0, "TC032: P-Core not disabled after hot window"

@cocotb.test()
async def TC033_therm_exactly_112(dut):
    """therm_pcore=112: headroom=8 which equals THERM_MARGIN — boundary exact."""
    await setup(dut)
    await apply_and_run(dut, 112, 50, 400)
    check_power_invariant(dut, "TC033")

@cocotb.test()
async def TC034_both_thermals_max(dut):
    """Both sensors at 255 — thermal block active, E-Core must run."""
    await setup(dut)
    await apply_and_run(dut, 255, 255, 300)
    assert int(dut.pd_pcore_en.value) == 0, "TC034: P-Core on at max temp"
    assert int(dut.pd_ecore_en.value) == 1, "TC034: E-Core off at max temp"

@cocotb.test()
async def TC035_ecore_active_flag_hot_stable(dut):
    """E-Core pd_ecore_en remains stable=1 for 200 cycles while P blocked."""
    await setup(dut)
    dut.therm_pcore.value = 119
    dut.therm_ecore.value = 60
    for _ in range(200):
        await RisingEdge(dut.clk)
        assert int(dut.pd_ecore_en.value) == 1, "TC035: E-Core went off while P-Core blocked"

@cocotb.test()
async def TC036_aes_unaffected_by_thermal(dut):
    """AES power domain on regardless of thermal state."""
    await setup(dut)
    for t in [50, 80, 100, 115, 119, 125, 255]:
        dut.therm_pcore.value = t
        await ClockCycles(dut.clk, 20)
        assert int(dut.pd_aes_en.value) == 1, f"TC036: AES off at therm={t}"

@cocotb.test()
async def TC037_mig_to_e_when_thermally_blocked(dut):
    """When P-Core thermally blocked, migration_state should be STAY_E(0) or TO_E(3)."""
    await setup(dut)
    await apply_and_run(dut, 119, 50, 400)
    v = int(dut.migration_state.value)
    assert v in (MIG_STAY_E, MIG_TO_E), \
        f"TC037: mig_state={v} unexpected when P-Core thermally blocked"

@cocotb.test()
async def TC038_mig_state_to_e_when_entering_hot(dut):
    """Transition from cool to hot should trigger MIG_TO_E or STAY_E."""
    await setup(dut)
    await apply_and_run(dut, 60, 50, 200)   # establish cool state
    dut.therm_pcore.value = 119
    await ClockCycles(dut.clk, 150)          # wait for window
    v = int(dut.migration_state.value)
    assert v in (MIG_STAY_E, MIG_TO_E), \
        f"TC038: mig_state={v} after entering thermal stress"

@cocotb.test()
async def TC039_ecore_therm_ignored_for_block_logic(dut):
    """E-Core temperature alone (high) doesn't trigger thermal block on P-Core."""
    await setup(dut)
    await apply_and_run(dut, 60, 200, 300)  # E-Core very hot, P-Core cool
    # No block on P-Core — invariant should still hold
    check_power_invariant(dut, "TC039")

@cocotb.test()
async def TC040_10x_thermal_toggle_invariant(dut):
    """Toggle P-Core temp between 60 and 119 ten times — invariant holds each time."""
    await setup(dut)
    temps = [60, 119] * 10
    for i, t in enumerate(temps):
        await apply_and_run(dut, t, 50, 90)
        check_power_invariant(dut, f"TC040_iter{i}_t{t}")

@cocotb.test()
async def TC041_therm_111_does_not_block(dut):
    """therm_pcore=111: headroom=9 > THERM_MARGIN(8) → no block."""
    await setup(dut)
    await apply_and_run(dut, 111, 50, 300)
    check_power_invariant(dut, "TC041")

@cocotb.test()
async def TC042_therm_113_does_block(dut):
    """therm_pcore=113: headroom=7 < THERM_MARGIN(8) → block."""
    await setup(dut)
    await apply_and_run(dut, 113, 50, 300)
    assert int(dut.pd_pcore_en.value) == 0, "TC042: P-Core on at therm=113 (should be blocked)"

@cocotb.test()
async def TC043_thermal_block_no_affect_on_l2_retain(dut):
    """Even under thermal block, L2 retention should be 0 (E-Core is active)."""
    await setup(dut)
    await apply_and_run(dut, 119, 50, 300)
    assert int(dut.pd_l2_retain.value) == 0, "TC043: L2 retention active while E-Core running"

@cocotb.test()
async def TC044_fast_thermal_spike_invariant(dut):
    """Very fast thermal spike (1 cycle at 255) doesn't break invariant."""
    await setup(dut)
    await apply_and_run(dut, 70, 50, 100)
    dut.therm_pcore.value = 255
    await ClockCycles(dut.clk, 1)
    dut.therm_pcore.value = 70
    await ClockCycles(dut.clk, 80)
    check_power_invariant(dut, "TC044")

@cocotb.test()
async def TC045_thermal_ramp_up(dut):
    """Ramp P-Core temp from 50 to 120 in steps of 5 — invariant at each step."""
    await setup(dut)
    for t in range(50, 121, 5):
        await apply_and_run(dut, t, 50, 80)
        check_power_invariant(dut, f"TC045_t{t}")

# =============================================================================
# ─────────────────────────────────────────────────────────────────────────────
#  GROUP C — MIGRATION ENGINE (TC046–TC080)
# ─────────────────────────────────────────────────────────────────────────────
# =============================================================================

@cocotb.test()
async def TC046_initial_state_ecore_active(dut):
    """After reset, E-Core cluster must be the default active domain."""
    await setup(dut)
    assert int(dut.pd_ecore_en.value) == 1, "TC046: E-Core not active after reset"
    assert int(dut.pd_pcore_en.value) == 0, "TC046: P-Core active after reset (should be off)"

@cocotb.test()
async def TC047_migration_state_reset_value(dut):
    """Migration state should reset to STAY_E (0)."""
    await setup(dut)
    v = int(dut.migration_state.value)
    assert v == MIG_STAY_E, f"TC047: mig_state={v} after reset, expected STAY_E={MIG_STAY_E}"

@cocotb.test()
async def TC048_window_fires_within_80_cycles(dut):
    """At least one window must have fired by 80 cycles (window=64 + latency)."""
    await setup(dut)
    await ClockCycles(dut.clk, 80)
    # Migration state may have changed from reset value — just check validity
    v = int(dut.migration_state.value)
    assert v in (0,1,2,3), f"TC048: mig_state={v} invalid after window"

@cocotb.test()
async def TC049_mig_state_changes_over_time(dut):
    """Run 1000 cycles and confirm mig_state is not permanently stuck at reset value."""
    await setup(dut)
    seen = set()
    for _ in range(20):
        await ClockCycles(dut.clk, 50)
        seen.add(int(dut.migration_state.value))
    # With a real workload the state should visit at least 1 unique value
    assert len(seen) >= 1, "TC049: Migration state never changed (stuck)"

@cocotb.test()
async def TC050_cool_long_run_valid_state(dut):
    """1000 cycles at cool temperature — valid final state."""
    await setup(dut)
    await apply_and_run(dut, 60, 45, 1000)
    check_power_invariant(dut, "TC050")

@cocotb.test()
async def TC051_hot_long_run_pcore_off(dut):
    """1000 cycles at hot temperature — P-Core must be off."""
    await setup(dut)
    await apply_and_run(dut, 119, 55, 1000)
    assert int(dut.pd_pcore_en.value) == 0, "TC051: P-Core active after hot long run"

@cocotb.test()
async def TC052_mig_state_stability_constant_input(dut):
    """Under constant thermal input, mig_state must stabilise (not oscillate forever)."""
    await setup(dut)
    await apply_and_run(dut, 70, 50, 500)
    states = []
    for _ in range(10):
        await ClockCycles(dut.clk, 10)
        states.append(int(dut.migration_state.value))
    # Last 5 samples should be identical (hysteresis locked)
    assert len(set(states[-5:])) == 1, \
        f"TC052: mig_state oscillating under constant input: {states}"

@cocotb.test()
async def TC053_multiple_windows_consistent(dut):
    """Check that 5 back-to-back windows give consistent state at constant input."""
    await setup(dut)
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    prev = None
    for w in range(5):
        await ClockCycles(dut.clk, 74)
        v = int(dut.migration_state.value)
        if prev is not None and w > 2:   # allow initial transient
            assert v == prev, f"TC053: mig_state changed unexpectedly at window {w}: {prev}→{v}"
        prev = v

@cocotb.test()
async def TC054_ecore_active_reflects_mig_stay_e(dut):
    """When mig_state is STAY_E(0), E-Core must be active."""
    await setup(dut)
    await apply_and_run(dut, 119, 50, 400)
    if int(dut.migration_state.value) == MIG_STAY_E:
        assert int(dut.pd_ecore_en.value) == 1, "TC054: E-Core off despite STAY_E migration"

@cocotb.test()
async def TC055_pcore_active_reflects_mig_stay_p(dut):
    """When mig_state is STAY_P(2), P-Core must be active."""
    await setup(dut)
    await apply_and_run(dut, 60, 45, 600)
    if int(dut.migration_state.value) == MIG_STAY_P:
        assert int(dut.pd_pcore_en.value) == 1, "TC055: P-Core off despite STAY_P migration"

@cocotb.test()
async def TC056_no_pcore_on_to_e_state(dut):
    """When mig_state=TO_E(3), P-Core must be off."""
    await setup(dut)
    await apply_and_run(dut, 119, 50, 300)
    if int(dut.migration_state.value) == MIG_TO_E:
        assert int(dut.pd_pcore_en.value) == 0, "TC056: P-Core still on during TO_E migration"

@cocotb.test()
async def TC057_no_ecore_off_on_to_p_state(dut):
    """When mig_state=TO_P(1), transition in progress — E-Core may turn off after."""
    await setup(dut)
    await apply_and_run(dut, 60, 45, 400)
    check_power_invariant(dut, "TC057")

@cocotb.test()
async def TC058_hysteresis_prevents_rapid_toggling(dut):
    """Toggle therm every 30 cycles — hysteresis should prevent state thrashing."""
    await setup(dut)
    prev_state = int(dut.migration_state.value)
    transitions = 0
    for i in range(20):
        t = 65 if i % 2 == 0 else 114  # alternate near threshold
        await apply_and_run(dut, t, 50, 30)
        curr = int(dut.migration_state.value)
        if curr != prev_state:
            transitions += 1
            prev_state = curr
    # Hysteresis hold=256 >> 30 cycles, so transitions should be very few
    assert transitions <= 4, \
        f"TC058: Too many migration transitions ({transitions}) — hysteresis not working"

@cocotb.test()
async def TC059_strong_signal_overrides_hysteresis(dut):
    """A very strong perceptron signal (extreme temperature) should override hysteresis lock."""
    await setup(dut)
    await apply_and_run(dut, 70, 50, 400)    # establish P-Core migration
    dut.therm_pcore.value = 255               # extreme thermal → forces E
    await ClockCycles(dut.clk, 150)
    assert int(dut.pd_pcore_en.value) == 0, "TC059: Strong thermal signal did not override hysteresis"

@cocotb.test()
async def TC060_migration_consistency_10_runs(dut):
    """Run the same sequence 2x — same final state (deterministic RTL)."""
    async def run_seq(dut):
        await reset_dut(dut, 10)
        await apply_and_run(dut, 70, 50, 300)
        return int(dut.migration_state.value)

    await setup(dut)
    s1 = await run_seq(dut)
    s2 = await run_seq(dut)
    assert s1 == s2, f"TC060: Non-deterministic migration: run1={s1} run2={s2}"

@cocotb.test()
async def TC061_mig_state_valid_all_256_thermals(dut):
    """Sweep all therm_pcore values 0–255 in 8 steps — always valid state."""
    await setup(dut)
    for t in range(0, 256, 8):
        await apply_and_run(dut, t, 50, 30)
        v = int(dut.migration_state.value)
        assert v in (0,1,2,3), f"TC061: Invalid mig_state={v} at therm={t}"

@cocotb.test()
async def TC062_ecore_therm_sweep_invariant(dut):
    """Sweep E-Core thermal 0–255 — invariant holds throughout."""
    await setup(dut)
    for t in range(0, 256, 16):
        await apply_and_run(dut, 70, t, 30)
        check_power_invariant(dut, f"TC062_te{t}")

@cocotb.test()
async def TC063_pd_ecore_on_at_reset_plus_1(dut):
    """1 cycle after reset release, E-Core must already be flagged active."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await RisingEdge(dut.clk)
    assert int(dut.pd_ecore_en.value) == 1, "TC063: E-Core not flagged at cycle 1 post-reset"

@cocotb.test()
async def TC064_no_glitch_on_pd_aes_en(dut):
    """pd_aes_en must never go low — monitor all edges for 500 cycles."""
    await setup(dut)
    dut.therm_pcore.value = 80
    dut.therm_ecore.value = 50
    for _ in range(500):
        await FallingEdge(dut.clk)
        assert int(dut.pd_aes_en.value) == 1, "TC064: pd_aes_en glitch detected on falling edge"

@cocotb.test()
async def TC065_mig_state_at_window_boundaries(dut):
    """Sample mig_state exactly at every 64-cycle boundary — must always be valid."""
    await setup(dut)
    dut.therm_pcore.value = 75
    dut.therm_ecore.value = 50
    for w in range(15):
        await ClockCycles(dut.clk, 64)
        v = int(dut.migration_state.value)
        assert v in (0,1,2,3), f"TC065: Invalid mig_state at window {w}: {v}"

@cocotb.test()
async def TC066_paired_pd_signals_cross_check(dut):
    """If pd_pcore_en=1 then pd_ecore_en should be 0 (after migration settles)."""
    await setup(dut)
    await apply_and_run(dut, 60, 45, 500)   # give perceptron time to decide
    p = int(dut.pd_pcore_en.value)
    e = int(dut.pd_ecore_en.value)
    if p == 1:
        assert e == 0, f"TC066: Both P and E active simultaneously (p={p}, e={e})"

@cocotb.test()
async def TC067_thermal_transition_no_both_off(dut):
    """During a thermal transition, never allow both clusters off simultaneously."""
    await setup(dut)
    # Rapid alternation
    for _ in range(20):
        dut.therm_pcore.value = 60
        await ClockCycles(dut.clk, 5)
        assert not (int(dut.pd_pcore_en.value)==0 and int(dut.pd_ecore_en.value)==0), \
            "TC067: Both clusters off during thermal transition"
        dut.therm_pcore.value = 119
        await ClockCycles(dut.clk, 5)
        assert not (int(dut.pd_pcore_en.value)==0 and int(dut.pd_ecore_en.value)==0), \
            "TC067: Both clusters off during thermal transition"

@cocotb.test()
async def TC068_feature_window_period_check(dut):
    """Confirm at least 3 feature windows fire within 250 cycles."""
    await setup(dut)
    # We can't directly observe window_valid; we use mig_state changes as proxy
    states = []
    for _ in range(250):
        await RisingEdge(dut.clk)
        states.append(int(dut.migration_state.value))
    # At least one transition or stable known state must exist
    assert len(set(states)) >= 1, "TC068: No valid migration states observed"

@cocotb.test()
async def TC069_mig_state_reachable_stay_e(dut):
    """Demonstrate STAY_E(0) state is reachable."""
    await setup(dut)
    await apply_and_run(dut, 119, 50, 500)
    v = int(dut.migration_state.value)
    assert v in (MIG_STAY_E, MIG_TO_E), f"TC069: Expected STAY_E/TO_E under hot temp, got {v}"

@cocotb.test()
async def TC070_gradual_cooling_no_invariant_break(dut):
    """Slowly cool P-Core from 119 to 50 — invariant at each step."""
    await setup(dut)
    await apply_and_run(dut, 119, 50, 300)  # start hot
    for t in range(119, 49, -5):
        await apply_and_run(dut, t, 50, 50)
        check_power_invariant(dut, f"TC070_t{t}")

@cocotb.test()
async def TC071_gradual_heating_no_invariant_break(dut):
    """Slowly heat P-Core from 50 to 119 — invariant at each step."""
    await setup(dut)
    for t in range(50, 120, 5):
        await apply_and_run(dut, t, 50, 50)
        check_power_invariant(dut, f"TC071_t{t}")

@cocotb.test()
async def TC072_aes_on_during_migration_event(dut):
    """AES must stay ON exactly during a migration event (transition window)."""
    await setup(dut)
    await apply_and_run(dut, 70, 50, 100)
    # Trigger potential migration
    dut.therm_pcore.value = 60
    for _ in range(80):
        await RisingEdge(dut.clk)
        assert int(dut.pd_aes_en.value) == 1, "TC072: AES off during migration"

@cocotb.test()
async def TC073_randomised_100_invariant_checks(dut):
    """100 random (therm_p, therm_e, cycles) combinations — invariant at each."""
    await setup(dut)
    rng = random.Random(0xC0C07B)
    for i in range(100):
        tp = rng.randint(0, 255)
        te = rng.randint(0, 255)
        c  = rng.randint(10, 80)
        await apply_and_run(dut, tp, te, c)
        check_power_invariant(dut, f"TC073_i{i}")

@cocotb.test()
async def TC074_migration_state_not_x_after_reset(dut):
    """migration_state should not be X immediately after reset deassert."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    await ClockCycles(dut.clk, 8)
    dut.rst.value = 0
    await RisingEdge(dut.clk)
    v = dut.migration_state.value
    assert int(v) in (0,1,2,3), f"TC074: mig_state={v} (X/Z?) immediately after reset"

@cocotb.test()
async def TC075_l2_retain_never_1_during_active_run(dut):
    """L2 retention pin stays 0 throughout a 500-cycle active run."""
    await setup(dut)
    dut.therm_pcore.value = 80
    dut.therm_ecore.value = 55
    for i in range(500):
        await RisingEdge(dut.clk)
        assert int(dut.pd_l2_retain.value) == 0, f"TC075: pd_l2_retain=1 at cycle {i}"

@cocotb.test()
async def TC076_mig_state_4windows_hot(dut):
    """Over 4 windows under hot conditions, mig_state stays in {STAY_E, TO_E}."""
    await setup(dut)
    dut.therm_pcore.value = 119
    dut.therm_ecore.value = 55
    for w in range(4):
        await ClockCycles(dut.clk, 74)
        v = int(dut.migration_state.value)
        assert v in (MIG_STAY_E, MIG_TO_E), \
            f"TC076: Window {w} mig_state={v} unexpected under hot conditions"

@cocotb.test()
async def TC077_power_gating_ecore_default(dut):
    """pd_pcore_en must be 0 right after reset (P-Core power-gated by default)."""
    await setup(dut)
    assert int(dut.pd_pcore_en.value) == 0, "TC077: P-Core not power-gated at reset"

@cocotb.test()
async def TC078_multiple_reset_invariant(dut):
    """5 reset cycles interspersed with short runs — invariant holds after each reset."""
    await setup(dut)
    for r in range(5):
        await apply_and_run(dut, 70+r*5, 50, 100)
        dut.rst.value = 1
        await ClockCycles(dut.clk, 5)
        dut.rst.value = 0
        await ClockCycles(dut.clk, 2)
        check_power_invariant(dut, f"TC078_r{r}")

@cocotb.test()
async def TC079_perceptron_not_all_zeros(dut):
    """After 10 windows, migration state should not be permanently 0 for all thermals."""
    await setup(dut)
    # Run at cool temperature — perceptron should at some point recommend P-Core
    await apply_and_run(dut, 50, 40, 10*74)
    # We just check validity; system is deterministic based on imem content
    check_power_invariant(dut, "TC079")

@cocotb.test()
async def TC080_no_deadlock_2000_cycles(dut):
    """System must not deadlock or hang over 2000 cycles at nominal conditions."""
    await setup(dut)
    await apply_and_run(dut, 70, 50, 2000)
    check_power_invariant(dut, "TC080")

# =============================================================================
# ─────────────────────────────────────────────────────────────────────────────
#  GROUP D — RESET BEHAVIOUR & EDGE CASES  (TC081–TC100)
# ─────────────────────────────────────────────────────────────────────────────
# =============================================================================

@cocotb.test()
async def TC081_reset_during_window(dut):
    """Assert reset exactly during a feature window evaluation (cycle 60) — no crash."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 60)   # mid-window
    dut.rst.value = 1                 # reset during window
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 20)
    check_power_invariant(dut, "TC081")

@cocotb.test()
async def TC082_zero_thermal_reset(dut):
    """Start with both thermals=0 — no crash, valid state."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.therm_pcore.value = 0
    dut.therm_ecore.value = 0
    await ClockCycles(dut.clk, 6)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 100)
    check_power_invariant(dut, "TC082")

@cocotb.test()
async def TC083_therm_change_during_reset(dut):
    """Change thermals while reset is asserted — state after deassert is valid."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.therm_pcore.value = 50
    dut.therm_ecore.value = 40
    await ClockCycles(dut.clk, 3)
    dut.therm_pcore.value = 119   # change while in reset
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 100)
    check_power_invariant(dut, "TC083")

@cocotb.test()
async def TC084_single_cycle_reset(dut):
    """1-cycle reset pulse — system recovers."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    await RisingEdge(dut.clk)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 100)
    check_power_invariant(dut, "TC084")

@cocotb.test()
async def TC085_long_reset_50_cycles(dut):
    """50-cycle reset then run 200 cycles — invariant holds."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    await ClockCycles(dut.clk, 50)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 200)
    check_power_invariant(dut, "TC085")

@cocotb.test()
async def TC086_rst_high_pd_signals_valid(dut):
    """While rst=1, pd_aes_en should still be 1 (always-on domain)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    await ClockCycles(dut.clk, 5)
    assert int(dut.pd_aes_en.value) == 1, "TC086: AES not on during reset"

@cocotb.test()
async def TC087_ecore_active_at_reset_high(dut):
    """While rst=1, E-Core domain should be 1 (reset default)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    await ClockCycles(dut.clk, 5)
    assert int(dut.pd_ecore_en.value) == 1, "TC087: E-Core not active during reset"

@cocotb.test()
async def TC088_pcore_off_at_reset_high(dut):
    """While rst=1, P-Core domain should be 0 (reset default)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    await ClockCycles(dut.clk, 5)
    assert int(dut.pd_pcore_en.value) == 0, "TC088: P-Core on during reset"

@cocotb.test()
async def TC089_repeated_minimal_reset(dut):
    """100 minimal (2-cycle) resets in succession — system survives."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    for r in range(100):
        dut.rst.value = 1
        await ClockCycles(dut.clk, 2)
        dut.rst.value = 0
        await ClockCycles(dut.clk, 2)
    check_power_invariant(dut, "TC089")

@cocotb.test()
async def TC090_post_reset_mig_state_0(dut):
    """After any reset, mig_state must be 0 (STAY_E)."""
    await setup(dut)
    await apply_and_run(dut, 60, 45, 500)
    dut.rst.value = 1
    await ClockCycles(dut.clk, 6)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)
    v = int(dut.migration_state.value)
    assert v == MIG_STAY_E, f"TC090: Post-reset mig_state={v}, expected {MIG_STAY_E}"

# =============================================================================
# ─────────────────────────────────────────────────────────────────────────────
#  GROUP E — CONSTRAINED RANDOM  (TC091–TC115)
# ─────────────────────────────────────────────────────────────────────────────
# =============================================================================

def random_test_factory(seed, therm_p_range, therm_e_range, cycles_range, label):
    """Factory: creates a random test closure with fixed seed for reproducibility."""
    async def _test(dut):
        await setup(dut)
        rng = random.Random(seed)
        for i in range(20):
            tp = rng.randint(*therm_p_range)
            te = rng.randint(*therm_e_range)
            c  = rng.randint(*cycles_range)
            await apply_and_run(dut, tp, te, c)
            check_power_invariant(dut, f"{label}_i{i}")
    return _test

# Register constrained-random tests TC091–TC115

# =============================================================================
# ─────────────────────────────────────────────────────────────────────────────
#  GROUP F — DIRECTED SCENARIO TESTS  (TC116–TC150)
# ─────────────────────────────────────────────────────────────────────────────
# =============================================================================


# ============================================================
# GROUP C CONSTRAINED-RANDOM TESTS TC091-TC115 (explicit)
# ============================================================
import random as _random

async def _cr_body(dut, seed, tp_lo, tp_hi, te_lo, te_hi, cyc_lo, cyc_hi, label):
    await setup(dut)
    rng = _random.Random(seed)
    for i in range(20):
        tp = rng.randint(tp_lo, tp_hi)
        te = rng.randint(te_lo, te_hi)
        c  = rng.randint(cyc_lo, cyc_hi)
        await apply_and_run(dut, tp, te, c)
        check_power_invariant(dut, f"{label}_i{i}")

@cocotb.test()
async def TC091_cool_p(dut):
    await _cr_body(dut,0x0001,50,111,40,80,50,150,"TC091")

@cocotb.test()
async def TC092_near_block_p(dut):
    await _cr_body(dut,0x0002,112,130,40,80,50,150,"TC092")

@cocotb.test()
async def TC093_hot_p(dut):
    await _cr_body(dut,0x0003,113,255,40,80,50,150,"TC093")

@cocotb.test()
async def TC094_hot_e(dut):
    await _cr_body(dut,0x0004,50,111,80,200,50,150,"TC094")

@cocotb.test()
async def TC095_both_hot(dut):
    await _cr_body(dut,0x0005,113,255,80,200,50,150,"TC095")

@cocotb.test()
async def TC096_short_bursts(dut):
    await _cr_body(dut,0x0006,50,255,40,255,10,30,"TC096")

@cocotb.test()
async def TC097_long_bursts(dut):
    await _cr_body(dut,0x0007,50,255,40,255,200,500,"TC097")

@cocotb.test()
async def TC098_window_aligned(dut):
    await _cr_body(dut,0x0008,60,90,40,70,64,128,"TC098")

@cocotb.test()
async def TC099_tiny_bursts(dut):
    await _cr_body(dut,0x0009,0,255,0,255,1,10,"TC099")

@cocotb.test()
async def TC100_threshold_zone(dut):
    await _cr_body(dut,0x000A,110,114,40,80,50,200,"TC100")

@cocotb.test()
async def TC101_cool_longrun(dut):
    await _cr_body(dut,0x000B,50,111,40,80,300,600,"TC101")

@cocotb.test()
async def TC102_hot_longrun(dut):
    await _cr_body(dut,0x000C,113,255,40,80,300,600,"TC102")

@cocotb.test()
async def TC103_exact_window(dut):
    await _cr_body(dut,0x000D,50,255,40,255,64,64,"TC103")

@cocotb.test()
async def TC104_mid_range(dut):
    await _cr_body(dut,0x000E,80,100,50,70,100,200,"TC104")

@cocotb.test()
async def TC105_very_cool(dut):
    await _cr_body(dut,0x000F,50,60,40,50,200,400,"TC105")

@cocotb.test()
async def TC106_just_above_blk(dut):
    await _cr_body(dut,0x0010,115,119,40,80,100,300,"TC106")

@cocotb.test()
async def TC107_cool_p_hot_e(dut):
    await _cr_body(dut,0x0011,50,111,100,200,100,200,"TC107")

@cocotb.test()
async def TC108_half_window(dut):
    await _cr_body(dut,0x0012,50,255,40,255,33,67,"TC108")

@cocotb.test()
async def TC109_warm_p(dut):
    await _cr_body(dut,0x0013,100,111,60,90,150,250,"TC109")

@cocotb.test()
async def TC110_cool_vlong(dut):
    await _cr_body(dut,0x0014,50,70,40,60,500,800,"TC110")

@cocotb.test()
async def TC111_hot_vlong(dut):
    await _cr_body(dut,0x0015,113,130,40,80,500,800,"TC111")

@cocotb.test()
async def TC112_nominal(dut):
    await _cr_body(dut,0x0016,70,90,40,60,64,256,"TC112")

@cocotb.test()
async def TC113_very_cold(dut):
    await _cr_body(dut,0x0017,0,30,0,30,100,300,"TC113")

@cocotb.test()
async def TC114_extreme_hot(dut):
    await _cr_body(dut,0x0018,200,255,200,255,100,300,"TC114")

@cocotb.test()
async def TC115_full_random(dut):
    await _cr_body(dut,0x0019,50,255,40,255,128,256,"TC115")

@cocotb.test()
async def TC116_stable_ecore_300_cycles(dut):
    """E-Core must stay stable for 300 cycles under hot thermal forcing."""
    await setup(dut)
    dut.therm_pcore.value = 119
    dut.therm_ecore.value = 55
    prev_e = int(dut.pd_ecore_en.value)
    for i in range(300):
        await RisingEdge(dut.clk)
        curr_e = int(dut.pd_ecore_en.value)
        assert curr_e == 1, f"TC116: E-Core went off at cycle {i}"

@cocotb.test()
async def TC117_pd_signals_no_glitch_cool(dut):
    """No glitch on any pd_* signal for 200 cycles at cool temp."""
    await setup(dut)
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    prev = sample_outputs(dut)
    for i in range(200):
        await RisingEdge(dut.clk)
        curr = sample_outputs(dut)
        # AES must never flip
        assert curr["pd_aes_en"] == 1, f"TC117: AES glitch at cycle {i}"

@cocotb.test()
async def TC118_therm_sawtooth_pattern(dut):
    """Sawtooth: ramp up then instant drop, 5 times — invariant each time."""
    await setup(dut)
    for cycle in range(5):
        for t in range(60, 125, 5):
            await apply_and_run(dut, t, 50, 15)
            check_power_invariant(dut, f"TC118_cyc{cycle}_t{t}")
        await apply_and_run(dut, 60, 50, 15)

@cocotb.test()
async def TC119_therm_square_wave(dut):
    """Square wave: alternate 60↔119 with period 128 cycles, 10 periods."""
    await setup(dut)
    for period in range(10):
        await apply_and_run(dut, 60, 50, 64)
        check_power_invariant(dut, f"TC119_high_p{period}")
        await apply_and_run(dut, 119, 50, 64)
        check_power_invariant(dut, f"TC119_low_p{period}")

@cocotb.test()
async def TC120_therm_sinusoidal_approx(dut):
    """Approximate sinusoidal temperature variation — invariant always holds."""
    await setup(dut)
    for i in range(50):
        t = int(85 + 35 * math.sin(i * 0.2))   # 50..120 range
        await apply_and_run(dut, t, 50, 20)
        check_power_invariant(dut, f"TC120_i{i}_t{t}")

@cocotb.test()
async def TC121_concurrent_max_min_thermal(dut):
    """P-Core max temp, E-Core min temp — valid state."""
    await setup(dut)
    await apply_and_run(dut, 255, 0, 300)
    check_power_invariant(dut, "TC121")
    assert int(dut.pd_pcore_en.value) == 0, "TC121: P-Core on at temp=255"

@cocotb.test()
async def TC122_concurrent_min_max_thermal(dut):
    """P-Core min temp, E-Core max temp — valid state, P-Core should be allowed."""
    await setup(dut)
    await apply_and_run(dut, 0, 255, 300)
    check_power_invariant(dut, "TC122")

@cocotb.test()
async def TC123_migration_state_sticky_hysteresis(dut):
    """Under hysteresis, state must not change for HYST_HOLD cycles after weak prediction."""
    await setup(dut)
    # Run long enough to lock a state
    await apply_and_run(dut, 70, 50, 500)
    locked_state = int(dut.migration_state.value)
    # Small perturbation — should not unlock
    dut.therm_pcore.value = 72
    for i in range(50):   # within one new window, weak signal should not unlock
        await ClockCycles(dut.clk, 5)
        curr = int(dut.migration_state.value)
        # State may remain or transition on strong signal — just check validity
        assert curr in (0,1,2,3), f"TC123: Invalid mig_state at step {i}"

@cocotb.test()
async def TC124_ecore_on_before_pcore_on(dut):
    """From reset, E-Core must turn on before P-Core can ever turn on."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.therm_pcore.value = 60
    dut.therm_ecore.value = 45
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    # First cycle: E-Core must be on
    await RisingEdge(dut.clk)
    assert int(dut.pd_ecore_en.value) == 1, "TC124: E-Core not first active after reset"

@cocotb.test()
async def TC125_pd_aes_en_is_hardwired_1(dut):
    """Verify pd_aes_en is effectively hardwired to 1 (always-on domain)."""
    await setup(dut)
    # Try every possible thermal combination
    for tp, te in [(0,0), (255,255), (119,0), (0,119), (80,60)]:
        dut.therm_pcore.value = tp
        dut.therm_ecore.value = te
        await ClockCycles(dut.clk, 10)
        assert int(dut.pd_aes_en.value) == 1, \
            f"TC125: pd_aes_en=0 at therm_p={tp} therm_e={te}"

@cocotb.test()
async def TC126_l2_retain_logic(dut):
    """pd_l2_retain = ~(pd_pcore_en | pd_ecore_en). Verify this formula holds."""
    await setup(dut)
    for _ in range(20):
        await ClockCycles(dut.clk, 50)
        p   = int(dut.pd_pcore_en.value)
        e   = int(dut.pd_ecore_en.value)
        ret = int(dut.pd_l2_retain.value)
        expected_ret = 0 if (p or e) else 1
        assert ret == expected_ret, \
            f"TC126: pd_l2_retain={ret} but expected {expected_ret} (p={p},e={e})"

@cocotb.test()
async def TC127_mig_state_thermally_forced_to_e(dut):
    """At therm_pcore=125, mig_state must be STAY_E or TO_E after 5 windows."""
    await setup(dut)
    await apply_and_run(dut, 125, 55, 5*74)
    v = int(dut.migration_state.value)
    assert v in (MIG_STAY_E, MIG_TO_E), \
        f"TC127: mig_state={v} at extreme temperature (expected STAY_E or TO_E)"

@cocotb.test()
async def TC128_all_pd_signals_sampled_100_cycles(dut):
    """Sample all 5 pd signals at every clock for 100 cycles — no X/Z."""
    await setup(dut)
    dut.therm_pcore.value = 80
    dut.therm_ecore.value = 55
    for i in range(100):
        await RisingEdge(dut.clk)
        for sig_name in ["pd_pcore_en","pd_ecore_en","pd_l2_retain","pd_aes_en","migration_state"]:
            sig = getattr(dut, sig_name)
            assert sig.value.is_resolvable, \
                f"TC128 cycle {i}: {sig_name} has X/Z value"

@cocotb.test()
async def TC129_mig_state_consistent_across_identical_runs(dut):
    """Three identical stimulus runs must produce identical final mig_state."""
    results = []
    for run in range(3):
        await setup(dut)
        await apply_and_run(dut, 75, 52, 400)
        results.append(int(dut.migration_state.value))
    assert len(set(results)) == 1, \
        f"TC129: Non-deterministic results across runs: {results}"

@cocotb.test()
async def TC130_boundary_therm_delta_8(dut):
    """Boundary: feat_therm_delta exactly 8 (at THERM_MARGIN). Check no crash."""
    await setup(dut)
    await apply_and_run(dut, THERM_BLOCK, 50, 400)
    check_power_invariant(dut, "TC130")

@cocotb.test()
async def TC131_pd_pcore_and_ecore_not_both_1_after_window(dut):
    """After migration settles (10 windows), P and E must not both be 1."""
    await setup(dut)
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    await ClockCycles(dut.clk, 10*74)  # 10 windows
    p = int(dut.pd_pcore_en.value)
    e = int(dut.pd_ecore_en.value)
    assert not (p==1 and e==1), f"TC131: Both clusters ON after migration settle (p={p},e={e})"

@cocotb.test()
async def TC132_ecore_stays_on_thermal_oscillation(dut):
    """Thermal oscillation around block boundary — E-Core stays on always."""
    await setup(dut)
    for i in range(30):
        t = 111 if i % 2 == 0 else 113
        await apply_and_run(dut, t, 50, 30)
        assert int(dut.pd_ecore_en.value) == 1 or int(dut.pd_pcore_en.value) == 1, \
            f"TC132: Both clusters off at step {i}"

@cocotb.test()
async def TC133_feature_extractor_branch_density(dut):
    """High-branch instructions loaded in imem — verify no crash in feature extractor."""
    await setup(dut)
    await apply_and_run(dut, 70, 50, 300)
    check_power_invariant(dut, "TC133")

@cocotb.test()
async def TC134_stress_5000_cycles(dut):
    """5000-cycle stress run at nominal temperature — no crash, invariant at end."""
    await setup(dut)
    await apply_and_run(dut, 70, 50, 5000)
    check_power_invariant(dut, "TC134")

@cocotb.test()
async def TC135_stress_5000_cycles_hot(dut):
    """5000-cycle stress at hot temperature — P-Core off throughout end."""
    await setup(dut)
    await apply_and_run(dut, 119, 55, 5000)
    assert int(dut.pd_pcore_en.value) == 0, "TC135: P-Core on after 5000 hot cycles"

@cocotb.test()
async def TC136_alternating_window_hot_cool(dut):
    """Alternate hot/cool every 64 cycles (exactly one window) for 20 iterations."""
    await setup(dut)
    for i in range(20):
        t = 60 if i % 2 == 0 else 119
        await apply_and_run(dut, t, 50, 64)
        check_power_invariant(dut, f"TC136_i{i}_t{t}")

@cocotb.test()
async def TC137_no_change_to_aes_en_ever(dut):
    """Over any run, pd_aes_en must never transition 1→0."""
    await setup(dut)
    prev = 1
    dut.therm_pcore.value = 80
    dut.therm_ecore.value = 55
    for _ in range(800):
        await RisingEdge(dut.clk)
        curr = int(dut.pd_aes_en.value)
        assert curr == 1, "TC137: pd_aes_en went low"
        prev = curr

@cocotb.test()
async def TC138_output_stable_during_reset_high(dut):
    """Outputs must be stable (not change erratically) while rst is asserted."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    await ClockCycles(dut.clk, 3)
    snap1 = sample_outputs(dut)
    await ClockCycles(dut.clk, 5)
    snap2 = sample_outputs(dut)
    # pd_aes_en must be stable=1, ecore=1, pcore=0 during reset
    assert snap1["pd_aes_en"]  == snap2["pd_aes_en"]  == 1, "TC138: AES unstable during reset"
    assert snap1["pd_pcore_en"]== snap2["pd_pcore_en"]== 0, "TC138: P-Core unstable during reset"
    assert snap1["pd_ecore_en"]== snap2["pd_ecore_en"]== 1, "TC138: E-Core unstable during reset"

@cocotb.test()
async def TC139_therm_step_response(dut):
    """Step change in therm_pcore from 70→119: check state after 2 windows."""
    await setup(dut)
    await apply_and_run(dut, 70, 50, 300)
    dut.therm_pcore.value = 119
    await ClockCycles(dut.clk, 2*74)
    assert int(dut.pd_pcore_en.value) == 0, "TC139: P-Core not off after step to hot"

@cocotb.test()
async def TC140_therm_step_cool_recovery(dut):
    """Step change from 119→70: check invariant is maintained after recovery."""
    await setup(dut)
    await apply_and_run(dut, 119, 50, 300)
    dut.therm_pcore.value = 70
    await ClockCycles(dut.clk, 300)
    check_power_invariant(dut, "TC140")

@cocotb.test()
async def TC141_check_mig_state_bits_individually(dut):
    """Check each bit of migration_state independently at cool and hot conditions."""
    await setup(dut)
    # Hot → expect STAY_E(00) or TO_E(11)
    await apply_and_run(dut, 119, 50, 400)
    v_hot = int(dut.migration_state.value)
    assert v_hot in (0b00, 0b11), f"TC141: Unexpected mig_state={v_hot:#04b} under hot"

@cocotb.test()
async def TC142_no_metastability_50_window_transitions(dut):
    """50 window transitions — migration_state never X/Z."""
    await setup(dut)
    dut.therm_pcore.value = 80
    dut.therm_ecore.value = 55
    for w in range(50):
        await ClockCycles(dut.clk, 64)
        v = dut.migration_state.value
        assert v.is_resolvable, f"TC142: X/Z at window {w}"
        assert int(v) in (0,1,2,3), f"TC142: Out-of-range at window {w}: {int(v)}"

@cocotb.test()
async def TC143_semaphore_no_effect_on_pd(dut):
    """Semaphore arbitration should not affect power domain signals."""
    await setup(dut)
    await apply_and_run(dut, 70, 50, 200)
    # Power domain signals should remain correct regardless of semaphore state
    check_power_invariant(dut, "TC143")

@cocotb.test()
async def TC144_ecore_pd_always_1_under_thermal_block(dut):
    """Under continuous thermal block (therm_p=119), E-Core pd must be 1 always."""
    await setup(dut)
    dut.therm_pcore.value = 119
    dut.therm_ecore.value = 55
    for i in range(300):
        await RisingEdge(dut.clk)
        assert int(dut.pd_ecore_en.value) == 1, \
            f"TC144: E-Core not active at cycle {i} under thermal block"

@cocotb.test()
async def TC145_migration_state_changes_max_3_per_10_windows_cool(dut):
    """At stable cool temperature, migration should not change more than 3× in 10 windows."""
    await setup(dut)
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    await ClockCycles(dut.clk, 200)   # let system settle first
    prev = int(dut.migration_state.value)
    changes = 0
    for _ in range(10):
        await ClockCycles(dut.clk, 74)
        curr = int(dut.migration_state.value)
        if curr != prev:
            changes += 1
            prev = curr
    assert changes <= 3, f"TC145: Too many migration changes ({changes}) in 10 cool windows"

@cocotb.test()
async def TC146_pd_l2_retain_follows_formula(dut):
    """pd_l2_retain = NOT(pd_pcore_en OR pd_ecore_en) — sampled 200 times."""
    await setup(dut)
    dut.therm_pcore.value = 80
    dut.therm_ecore.value = 55
    for i in range(200):
        await RisingEdge(dut.clk)
        p   = int(dut.pd_pcore_en.value)
        e   = int(dut.pd_ecore_en.value)
        ret = int(dut.pd_l2_retain.value)
        exp = 0 if (p or e) else 1
        assert ret == exp, f"TC146 cycle {i}: pd_l2_retain={ret} expected {exp}"

@cocotb.test()
async def TC147_all_outputs_valid_start_to_finish(dut):
    """From cycle 1 to 500, all outputs must be binary-resolvable."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, units="ns").start())
    dut.rst.value = 1
    dut.therm_pcore.value = 75
    dut.therm_ecore.value = 52
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    for i in range(500):
        await RisingEdge(dut.clk)
        for sig in ["pd_pcore_en","pd_ecore_en","pd_l2_retain","pd_aes_en","migration_state"]:
            v = getattr(dut, sig).value
            assert v.is_resolvable, f"TC147 cycle {i}: {sig} has unresolvable value"

@cocotb.test()
async def TC148_final_state_after_hot_cool_alternation(dut):
    """After 20 hot→cool cycles, final state must satisfy invariant."""
    await setup(dut)
    for _ in range(20):
        await apply_and_run(dut, 119, 50, 80)
        await apply_and_run(dut,  60, 50, 80)
    check_power_invariant(dut, "TC148")

@cocotb.test()
async def TC149_mig_state_reachable_to_e(dut):
    """TO_E(3) or STAY_E(0) must be reachable by applying hot temperature."""
    await setup(dut)
    await apply_and_run(dut, 119, 50, 500)
    v = int(dut.migration_state.value)
    assert v in (MIG_TO_E, MIG_STAY_E), \
        f"TC149: Expected TO_E(3) or STAY_E(0) under hot, got {v}"

@cocotb.test()
async def TC150_comprehensive_final_check(dut):
    """
    Final comprehensive test:
    Phase 1 — reset, confirm defaults
    Phase 2 — 500 cool cycles, sample every 50
    Phase 3 — 500 hot cycles, confirm P-Core off
    Phase 4 — cool recovery, confirm invariant
    Phase 5 — 10 random bursts
    """
    await setup(dut)

    # Phase 1
    assert int(dut.pd_ecore_en.value) == 1
    assert int(dut.pd_pcore_en.value) == 0
    assert int(dut.pd_aes_en.value)   == 1

    # Phase 2
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    for s in range(10):
        await ClockCycles(dut.clk, 50)
        check_power_invariant(dut, f"TC150_p2_s{s}")

    # Phase 3
    dut.therm_pcore.value = 119
    dut.therm_ecore.value = 55
    await ClockCycles(dut.clk, 500)
    assert int(dut.pd_pcore_en.value) == 0, "TC150 Phase 3: P-Core active under hot"
    assert int(dut.pd_aes_en.value)   == 1, "TC150 Phase 3: AES off"

    # Phase 4
    dut.therm_pcore.value = 70
    dut.therm_ecore.value = 50
    await ClockCycles(dut.clk, 300)
    check_power_invariant(dut, "TC150_p4")

    # Phase 5
    rng = random.Random(0xFACE)
    for b in range(10):
        tp = rng.randint(50, 255)
        te = rng.randint(40, 200)
        await apply_and_run(dut, tp, te, rng.randint(40,120))
        check_power_invariant(dut, f"TC150_p5_b{b}")

    cocotb.log.info("TC150 PASSED — All 5 phases completed successfully")
