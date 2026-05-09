#!/usr/bin/env python3
"""
show_lines.py
Run this first:  python3 show_lines.py
It prints lines 440-490 so you can see exactly what Icarus is choking on,
then rewrites the perceptron_engine module in-place.

Usage:
    cd /home/ubuntu/OpenLane/designs/hetero_4core/rtl
    python3 /tmp/show_lines.py
"""

import re, shutil, sys

RTL = "/home/ubuntu/OpenLane/designs/hetero_4core/rtl/hetero_4core.v"

# ── 1. Show the offending lines ──────────────────────────────────────────────
with open(RTL) as f:
    lines = f.readlines()

print("=== Lines 430-500 of hetero_4core.v ===")
for i, l in enumerate(lines[429:500], start=430):
    print(f"{i:4d}: {l}", end="")
print("\n" + "="*50)

# ── 2. Locate module boundaries ──────────────────────────────────────────────
def find_module(lines, name):
    """Return (start_idx, end_idx) inclusive, 0-based."""
    start = None
    depth = 0
    for i, l in enumerate(lines):
        if start is None:
            if re.search(r'\bmodule\s+' + name + r'\b', l):
                start = i
                depth = 1
        else:
            if re.search(r'\bmodule\b', l) and not re.search(r'\bendmodule\b', l):
                depth += 1
            if re.search(r'\bendmodule\b', l):
                depth -= 1
                if depth == 0:
                    return start, i
    return None, None

ps, pe = find_module(lines, "perceptron_engine")
fs, fe = find_module(lines, "feature_extractor")
print(f"perceptron_engine : lines {ps+1}–{pe+1}")
print(f"feature_extractor : lines {fs+1}–{fe+1}")

# ── 3. Replacement text ───────────────────────────────────────────────────────
PERC = r"""
module perceptron_engine (
    input  wire        clk,
    input  wire        rst,
    input  wire [7:0]  feat_instr_mix,
    input  wire [7:0]  feat_mem_stride,
    input  wire [7:0]  feat_branch_den,
    input  wire [7:0]  feat_therm_delta,
    input  wire        window_valid,
    output reg  [1:0]  migration_rec,
    output reg         strong_signal,
    input  wire [1:0]  current_core_type
);
    // ---- signed weights (localparam avoids Icarus 'parameter signed' bug) ----
    localparam [15:0] W0_RAW    = 16'd80;
    localparam [15:0] W1_RAW    = 16'd40;   // applied as subtraction below
    localparam [15:0] W2_RAW    = 16'd60;
    localparam [15:0] W3_RAW    = 16'd50;   // applied as subtraction below
    localparam [15:0] BIAS_RAW  = 16'd30;   // applied as subtraction below
    localparam [15:0] STH       = 16'd2000; // strong-signal threshold

    // ---- zero-extend inputs to 16-bit for arithmetic -------------------------
    wire [15:0] f0 = {8'd0, feat_instr_mix};
    wire [15:0] f1 = {8'd0, feat_mem_stride};
    wire [15:0] f2 = {8'd0, feat_branch_den};
    wire [15:0] f3 = {8'd0, feat_therm_delta};

    // ---- score = -BIAS + W0*f0 - W1*f1 + W2*f2 - W3*f3 ---------------------
    // Use 32-bit unsigned arithmetic then interpret as signed via [31] bit
    wire [31:0] pos_terms = (W0_RAW * f0) + (W2_RAW * f2);
    wire [31:0] neg_terms = BIAS_RAW + (W1_RAW * f1) + (W3_RAW * f3);

    // score_signed > 0 means pos_terms > neg_terms
    wire        p_indicated  = (pos_terms > neg_terms);
    wire [31:0] score_mag    = (pos_terms > neg_terms) ?
                                (pos_terms - neg_terms) :
                                (neg_terms - pos_terms);
    wire        strong       = (score_mag > {16'd0, STH});

    // ---- thermal block: headroom to throttle < THERM_MARGIN(8) --------------
    wire        therm_block  = (feat_therm_delta < 8'd9);

    // ---- hysteresis state ----------------------------------------------------
    reg [7:0]   hyst_cnt;
    reg         locked;
    reg [1:0]   locked_rec;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            migration_rec <= 2'b00;
            strong_signal <= 1'b0;
            hyst_cnt      <= 8'd0;
            locked        <= 1'b0;
            locked_rec    <= 2'b00;
        end else if (window_valid) begin
            strong_signal <= strong;

            if (locked == 1'b1 && strong == 1'b0) begin
                // ---- hysteresis hold ----------------------------------------
                migration_rec <= locked_rec;
                if (hyst_cnt >= 8'd254) begin
                    locked   <= 1'b0;
                    hyst_cnt <= 8'd0;
                end else begin
                    hyst_cnt <= hyst_cnt + 8'd1;
                end

            end else begin
                // ---- new recommendation ------------------------------------
                hyst_cnt   <= 8'd0;
                locked     <= (strong == 1'b0) ? 1'b1 : 1'b0;
                locked_rec <= migration_rec;   // latch current before update

                if (therm_block == 1'b1) begin
                    if (current_core_type == 2'd1)
                        migration_rec <= 2'b11;   // TO_E
                    else
                        migration_rec <= 2'b00;   // STAY_E
                end else if (p_indicated == 1'b1) begin
                    if (current_core_type == 2'd1)
                        migration_rec <= 2'b10;   // STAY_P
                    else
                        migration_rec <= 2'b01;   // TO_P
                end else begin
                    if (current_core_type == 2'd0)
                        migration_rec <= 2'b00;   // STAY_E
                    else
                        migration_rec <= 2'b11;   // TO_E
                end
            end
        end
    end
endmodule
""".strip() + "\n"

FEAT = r"""
module feature_extractor (
    input  wire        clk,
    input  wire        rst,
    input  wire [31:0] instr,
    input  wire        instr_valid,
    input  wire [7:0]  therm_reading,
    output reg  [7:0]  feat_instr_mix,
    output reg  [7:0]  feat_mem_stride,
    output reg  [7:0]  feat_branch_den,
    output reg  [7:0]  feat_therm_delta,
    output reg         window_valid
);
    wire [6:0] opcode = instr[6:0];
    wire [6:0] funct7 = instr[31:25];

    wire is_mul    = (opcode == 7'b0110011) && (funct7 == 7'b0000001);
    wire is_branch = (opcode == 7'b1100011);

    // Thermal headroom (saturating subtract)
    wire [7:0] therm_delta =
        (therm_reading >= 8'd120) ? 8'd0 :
        (8'd120 - therm_reading);

    reg [6:0] cycle_cnt;
    reg [7:0] mul_cnt;
    reg [7:0] br_cnt;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            cycle_cnt        <= 7'd0;
            mul_cnt          <= 8'd0;
            br_cnt           <= 8'd0;
            window_valid     <= 1'b0;
            feat_instr_mix   <= 8'd0;
            feat_mem_stride  <= 8'd128;
            feat_branch_den  <= 8'd0;
            feat_therm_delta <= 8'd50;
        end else begin
            window_valid <= 1'b0;
            if (instr_valid == 1'b1) begin
                if (is_mul == 1'b1 && mul_cnt < 8'd255)
                    mul_cnt <= mul_cnt + 8'd1;
                if (is_branch == 1'b1 && br_cnt < 8'd255)
                    br_cnt  <= br_cnt  + 8'd1;

                if (cycle_cnt == 7'd63) begin
                    feat_instr_mix   <= (mul_cnt[7:6] != 2'b00) ? 8'd255
                                        : {mul_cnt[5:0], 2'b00};
                    feat_mem_stride  <= 8'd128;
                    feat_branch_den  <= (br_cnt[7:6]  != 2'b00) ? 8'd255
                                        : {br_cnt[5:0],  2'b00};
                    feat_therm_delta <= therm_delta;
                    window_valid     <= 1'b1;
                    cycle_cnt        <= 7'd0;
                    mul_cnt          <= 8'd0;
                    br_cnt           <= 8'd0;
                end else begin
                    cycle_cnt <= cycle_cnt + 7'd1;
                end
            end
        end
    end
endmodule
""".strip() + "\n"

# ── 4. Patch the file ─────────────────────────────────────────────────────────
if ps is None or pe is None:
    print("ERROR: could not locate perceptron_engine in file")
    sys.exit(1)
if fs is None or fe is None:
    print("ERROR: could not locate feature_extractor in file")
    sys.exit(1)

# Determine the contiguous block to replace (perceptron first, then feature_extractor)
# They should be adjacent; replace from start of perceptron to end of feature_extractor
block_start = min(ps, fs)
block_end   = max(pe, fe)

shutil.copy(RTL, RTL + ".bak")   # backup first
new_lines = lines[:block_start] + [PERC + "\n", FEAT + "\n"] + lines[block_end+1:]

with open(RTL, "w") as f:
    f.writelines(new_lines)

print(f"\nPatched lines {block_start+1}–{block_end+1} successfully.")
print(f"Backup saved as {RTL}.bak")
print("\nNow run:  iverilog -g2012 -tnull /home/ubuntu/OpenLane/designs/hetero_4core/rtl/hetero_4core.v")
