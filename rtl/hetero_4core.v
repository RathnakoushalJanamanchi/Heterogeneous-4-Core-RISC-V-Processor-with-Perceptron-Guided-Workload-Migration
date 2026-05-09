`timescale 1ns/1ps

// ============================================================
// PARAMETERS
// ============================================================
`define XLEN        32
`define REG_COUNT   32
`define IMEM_DEPTH  1024
`define DMEM_DEPTH  1024
`define L2_DEPTH    4096
`define CACHE_LINES 16
`define TAG_BITS    20
`define THERM_THRESH 120
`define THERM_MARGIN 8

// Opcodes
`define OP_LUI    7'b0110111
`define OP_AUIPC  7'b0010111
`define OP_JAL    7'b1101111
`define OP_JALR   7'b1100111
`define OP_BRANCH 7'b1100011
`define OP_LOAD   7'b0000011
`define OP_STORE  7'b0100011
`define OP_ALUI   7'b0010011
`define OP_ALUR   7'b0110011
`define OP_FENCE  7'b0001111

// MESI
`define MESI_I 2'b00
`define MESI_S 2'b01
`define MESI_E 2'b10
`define MESI_M 2'b11

// Migration
`define MIG_STAY_E 2'b00
`define MIG_TO_P   2'b01
`define MIG_STAY_P 2'b10
`define MIG_TO_E   2'b11

// ============================================================
// SECTION 2: REGISTER FILE
// ============================================================
module regfile (
    input  wire        clk, rst,
    input  wire [4:0]  rs1, rs2, rd,
    input  wire        we,
    input  wire [31:0] wdata,
    output wire [31:0] rdata1, rdata2
);
    reg [31:0] regs [0:31];
    integer i;
    always @(posedge clk or posedge rst)
        if (rst) for (i=0;i<32;i=i+1) regs[i] <= 32'd0;
        else if (we && (rd != 5'd0)) regs[rd] <= wdata;
    assign rdata1 = (rs1 == 5'd0) ? 32'd0 : regs[rs1];
    assign rdata2 = (rs2 == 5'd0) ? 32'd0 : regs[rs2];
endmodule

// ============================================================
// SECTION 3: ALU
// ============================================================
module alu (
    input  wire [31:0] a, b,
    input  wire [3:0]  op,
    output reg  [31:0] result,
    output wire        zero
);
    wire signed [31:0] sa = a;
    wire signed [31:0] sb = b;
    always @(*) begin
        case (op)
            4'd0:  result = a + b;
            4'd1:  result = a - b;
            4'd2:  result = a & b;
            4'd3:  result = a | b;
            4'd4:  result = a ^ b;
            4'd5:  result = a << b[4:0];
            4'd6:  result = a >> b[4:0];
            4'd7:  result = $signed(a) >>> b[4:0];
            4'd8:  result = ($signed(a) < $signed(b)) ? 32'd1 : 32'd0;
            4'd9:  result = (a < b) ? 32'd1 : 32'd0;
            4'd10: result = a * b;
            4'd11: result = (a * b) >> 16;
            4'd12: result = (b == 32'd0) ? 32'hFFFFFFFF : $signed(a) / $signed(b);
            4'd13: result = (b == 32'd0) ? 32'hFFFFFFFF : a / b;
            default: result = 32'd0;
        endcase
    end
    assign zero = (result == 32'd0);
endmodule

// ============================================================
// SECTION 4: BRANCH PREDICTOR
// ============================================================
module branch_predictor (
    input  wire        clk, rst,
    input  wire [31:0] pc,
    input  wire        branch_taken,
    input  wire        branch_valid,
    input  wire [31:0] branch_pc,
    output wire        predict_taken
);
    reg [1:0] bht [0:15];
    wire [3:0] idx     = pc[5:2];
    wire [3:0] upd_idx = branch_pc[5:2];
    integer i;
    always @(posedge clk or posedge rst) begin
        if (rst) for (i=0;i<16;i=i+1) bht[i] <= 2'b01;
        else if (branch_valid) begin
            if (branch_taken)
                bht[upd_idx] <= (bht[upd_idx] == 2'b11) ? 2'b11 : bht[upd_idx] + 2'd1;
            else
                bht[upd_idx] <= (bht[upd_idx] == 2'b00) ? 2'b00 : bht[upd_idx] - 2'd1;
        end
    end
    assign predict_taken = bht[idx][1];
endmodule

// ============================================================
// SECTION 5: INSTRUCTION MEMORY
// ============================================================
module imem (
    input  wire [31:0] addr,
    output wire [31:0] instr
);
    reg [31:0] mem [0:1023];
    integer i;
    initial begin
        for (i=0;i<1024;i=i+1) mem[i] = 32'h00000013;
        mem[0] = 32'h00500093; // addi x1,x0,5
        mem[1] = 32'h00300113; // addi x2,x0,3
        mem[2] = 32'h02208133; // mul  x3,x1,x2
        mem[3] = 32'h00208233; // add  x4,x1,x2
        mem[4] = 32'h00302023; // sw   x3,0(x0)
        mem[5] = 32'h00002283; // lw   x5,0(x0)
        mem[6] = 32'h00208463; // beq  x1,x2,+8
        mem[7] = 32'h02418333; // mul  x6,x3,x4
        mem[8] = 32'h026283B3; // mul  x7,x5,x6
        mem[9] = 32'h0000006F; // jal  x0,0
    end
    assign instr = mem[addr[11:2]];
endmodule

// ============================================================
// SECTION 6: L1 CACHE (MESI)
// ============================================================
module l1_cache (
    input  wire        clk, rst,
    input  wire        mem_read, mem_write,
    input  wire [31:0] addr, wdata,
    output reg  [31:0] rdata,
    output reg         hit,
    output reg         bus_req,
    input  wire        bus_grant,
    output reg  [31:0] bus_addr,
    output reg  [1:0]  bus_cmd,
    input  wire [31:0] snoop_addr,
    input  wire [1:0]  snoop_cmd,
    input  wire        snoop_valid,
    output reg         l2_req,
    output reg  [31:0] l2_addr,
    input  wire [31:0] l2_rdata,
    input  wire        l2_ack
);
    reg [31:0] data  [0:15];
    reg [19:0] tags  [0:15];
    reg [1:0]  mesi  [0:15];
    reg        valid [0:15];

    wire [3:0]  idx   = addr[5:2];
    wire [19:0] tag   = addr[31:12];
    wire        match = valid[idx] && (tags[idx] == tag);
    integer k;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            hit <= 1'b0; rdata <= 32'd0;
            bus_req <= 1'b0; l2_req <= 1'b0;
            for (k=0;k<16;k=k+1) begin
                data[k]<=32'd0; tags[k]<=20'd0;
                mesi[k]<=`MESI_I; valid[k]<=1'b0;
            end
        end else begin
            bus_req <= 1'b0; l2_req <= 1'b0;
            if (snoop_valid && (snoop_cmd == 2'b11)) begin
                if (valid[snoop_addr[5:2]] &&
                    (tags[snoop_addr[5:2]] == snoop_addr[31:12]))
                    mesi[snoop_addr[5:2]] <= `MESI_I;
            end
            if (mem_read) begin
                if (match && (mesi[idx] != `MESI_I)) begin
                    rdata <= data[idx]; hit <= 1'b1;
                end else begin
                    hit <= 1'b0; l2_req <= 1'b1; l2_addr <= addr;
                    if (l2_ack) begin
                        data[idx]  <= l2_rdata; tags[idx]  <= tag;
                        mesi[idx]  <= `MESI_S;  valid[idx] <= 1'b1;
                        rdata      <= l2_rdata;
                    end
                end
            end
            if (mem_write) begin
                data[idx]  <= wdata; tags[idx] <= tag;
                mesi[idx]  <= `MESI_M; valid[idx] <= 1'b1;
                bus_req    <= 1'b1;   bus_addr  <= addr;
                bus_cmd    <= 2'b11;
            end
        end
    end
endmodule

// ============================================================
// SECTION 7: L2 CACHE
// ============================================================
module l2_cache (
    input  wire        clk, rst,
    input  wire        retention_mode,
    input  wire        req0, wr0,
    input  wire [31:0] addr0, wdata0,
    output reg  [31:0] rdata0,
    output reg         ack0,
    input  wire        req1, wr1,
    input  wire [31:0] addr1, wdata1,
    output reg  [31:0] rdata1,
    output reg         ack1
);
    reg [31:0] mem [0:4095];
    integer i;
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            ack0<=1'b0; ack1<=1'b0;
            for(i=0;i<4096;i=i+1) mem[i]<=32'hDEADBEEF;
        end else if (retention_mode) begin
            ack0<=1'b0; ack1<=1'b0;
        end else begin
            ack0<=1'b0; ack1<=1'b0;
            if (req0) begin
                if (wr0) mem[addr0[13:2]] <= wdata0;
                else     rdata0 <= mem[addr0[13:2]];
                ack0 <= 1'b1;
            end
            if (req1) begin
                if (wr1) mem[addr1[13:2]] <= wdata1;
                else     rdata1 <= mem[addr1[13:2]];
                ack1 <= 1'b1;
            end
        end
    end
endmodule

// ============================================================
// SECTION 8: AES ACCELERATOR
// ============================================================
module aes_accelerator (
    input  wire        clk, rst,
    input  wire        cs, we,
    input  wire [3:0]  reg_addr,
    input  wire [31:0] wdata,
    output reg  [31:0] rdata,
    input  wire        sem_grant,
    output reg         sem_req,
    output reg         done
);
    reg [31:0] key   [0:3];
    reg [31:0] plain [0:3];
    reg [31:0] ciph  [0:3];
    reg        go_bit;
    reg [3:0]  cnt;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            go_bit<=1'b0; done<=1'b0; cnt<=4'd0; sem_req<=1'b0;
            ciph[0]<=32'd0; ciph[1]<=32'd0; ciph[2]<=32'd0; ciph[3]<=32'd0;
        end else begin
            if (cs && we) begin
                case (reg_addr)
                    4'd0: key[0]   <= wdata;
                    4'd1: key[1]   <= wdata;
                    4'd2: key[2]   <= wdata;
                    4'd3: key[3]   <= wdata;
                    4'd4: plain[0] <= wdata;
                    4'd5: plain[1] <= wdata;
                    4'd6: plain[2] <= wdata;
                    4'd7: plain[3] <= wdata;
                    4'd8: begin go_bit<=wdata[0]; sem_req<=wdata[0]; end
                    default:;
                endcase
            end
            if (cs && !we) begin
                case (reg_addr)
                    4'd9:  rdata <= ciph[0];
                    4'd10: rdata <= ciph[1];
                    4'd11: rdata <= ciph[2];
                    4'd12: rdata <= ciph[3];
                    4'd13: rdata <= {31'd0, done};
                    default: rdata <= 32'd0;
                endcase
            end
            if (go_bit && sem_grant) begin
                cnt <= cnt + 4'd1;
                if (cnt < 4'd10) begin
                    ciph[0] <= plain[0] ^ key[0] ^ {28'd0, cnt};
                    ciph[1] <= plain[1] ^ key[1] ^ {28'd0, cnt};
                    ciph[2] <= plain[2] ^ key[2] ^ {28'd0, cnt};
                    ciph[3] <= plain[3] ^ key[3] ^ {28'd0, cnt};
                end else begin
                    done<=1'b1; go_bit<=1'b0; cnt<=4'd0; sem_req<=1'b0;
                end
            end
        end
    end
endmodule

// ============================================================
// SECTION 9: HARDWARE SEMAPHORE
// ============================================================
module hw_semaphore (
    input  wire       clk, rst,
    input  wire [3:0] req,
    output reg  [3:0] grant
);
    reg [3:0] owner;
    integer j;
    always @(posedge clk or posedge rst) begin
        if (rst) begin grant<=4'd0; owner<=4'd0; end
        else begin
            grant <= 4'd0;
            if (owner == 4'd0) begin
                for (j=3;j>=0;j=j-1)
                    if (req[j]) owner <= (4'd1 << j);
            end else begin
                if ((req & owner) == 4'd0) owner <= 4'd0;
                else grant <= owner;
            end
        end
    end
endmodule

// ============================================================
// SECTION 10: PERCEPTRON MIGRATION ENGINE
// ============================================================
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
    localparam [15:0] W0   = 16'd80;
    localparam [15:0] W1   = 16'd40;
    localparam [15:0] W2   = 16'd60;
    localparam [15:0] W3   = 16'd50;
    localparam [15:0] BIAS = 16'd30;
    localparam [31:0] STH  = 32'd2000;
    reg [31:0] pt, nt, sm;
    reg        pi, sg, tb;
    reg [7:0]  hc;
    reg        lk;
    reg [1:0]  lr;
    always @(*) begin
        pt = ({16'd0,W0} * {24'd0,feat_instr_mix})
           + ({16'd0,W2} * {24'd0,feat_branch_den});
        nt = {16'd0,BIAS}
           + ({16'd0,W1} * {24'd0,feat_mem_stride})
           + ({16'd0,W3} * {24'd0,feat_therm_delta});
        pi = (pt > nt) ? 1'b1 : 1'b0;
        if (pt > nt) sm = pt - nt;
        else         sm = nt - pt;
        sg = (sm > STH) ? 1'b1 : 1'b0;
        tb = (feat_therm_delta < 8'd9) ? 1'b1 : 1'b0;
    end
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            migration_rec <= 2'b00; strong_signal <= 1'b0;
            hc <= 8'd0; lk <= 1'b0; lr <= 2'b00;
        end else if (window_valid == 1'b1) begin
            strong_signal <= sg;
            if ((lk == 1'b1) && (sg == 1'b0)) begin
                migration_rec <= lr;
                if (hc >= 8'd254) begin lk <= 1'b0; hc <= 8'd0; end
                else hc <= hc + 8'd1;
            end else begin
                hc <= 8'd0;
                lk <= (sg == 1'b0) ? 1'b1 : 1'b0;
                lr <= migration_rec;
                if (tb == 1'b1) begin
                    if (current_core_type == 2'd1) migration_rec <= 2'b11;
                    else                           migration_rec <= 2'b00;
                end else if (pi == 1'b1) begin
                    if (current_core_type == 2'd1) migration_rec <= 2'b10;
                    else                           migration_rec <= 2'b01;
                end else begin
                    if (current_core_type == 2'd0) migration_rec <= 2'b00;
                    else                           migration_rec <= 2'b11;
                end
            end
        end
    end
endmodule

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
    reg [6:0] cyc;
    reg [7:0] mc, bc;
    reg [6:0] opc;
    reg [6:0] fn7;
    reg       im, ib;
    reg [7:0] td;
    always @(*) begin
        opc = instr[6:0];
        fn7 = instr[31:25];
        im = ((opc == 7'b0110011) && (fn7 == 7'b0000001)) ? 1'b1 : 1'b0;
        ib = (opc == 7'b1100011) ? 1'b1 : 1'b0;
        if (therm_reading >= 8'd120) td = 8'd0;
        else td = 8'd120 - therm_reading;
    end
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            cyc<=7'd0; mc<=8'd0; bc<=8'd0;
            window_valid<=1'b0;
            feat_instr_mix<=8'd0; feat_mem_stride<=8'd128;
            feat_branch_den<=8'd0; feat_therm_delta<=8'd50;
        end else begin
            window_valid <= 1'b0;
            if (instr_valid == 1'b1) begin
                if ((im == 1'b1) && (mc < 8'd255)) mc <= mc + 8'd1;
                if ((ib == 1'b1) && (bc < 8'd255)) bc <= bc + 8'd1;
                if (cyc == 7'd63) begin
                    if (mc > 8'd63) feat_instr_mix  <= 8'd252;
                    else            feat_instr_mix  <= {mc[5:0], 2'b00};
                    feat_mem_stride  <= 8'd128;
                    if (bc > 8'd63) feat_branch_den <= 8'd252;
                    else            feat_branch_den <= {bc[5:0], 2'b00};
                    feat_therm_delta <= td;
                    window_valid     <= 1'b1;
                    cyc<=7'd0; mc<=8'd0; bc<=8'd0;
                end else begin
                    cyc <= cyc + 7'd1;
                end
            end
        end
    end
endmodule

// ============================================================
// SECTION 12: E-CORE (single-cycle RV32IM)
// ============================================================
module ecore (
    input  wire        clk, rst,
    input  wire        active,
    output wire        dmem_read, dmem_write,
    output wire [31:0] dmem_addr, dmem_wdata,
    input  wire [31:0] dmem_rdata,
    output wire [31:0] current_instr,
    output wire        instr_valid_out,
    output wire        aes_cs, aes_we,
    output wire [3:0]  aes_reg,
    output wire [31:0] aes_wdata
);
    reg  [31:0] pc;
    wire [31:0] instr;
    wire [6:0]  opcode = instr[6:0];
    wire [4:0]  rd     = instr[11:7];
    wire [2:0]  funct3 = instr[14:12];
    wire [4:0]  rs1    = instr[19:15];
    wire [4:0]  rs2    = instr[24:20];
    wire [6:0]  funct7 = instr[31:25];
    wire [31:0] imm_i  = {{20{instr[31]}}, instr[31:20]};
    wire [31:0] imm_s  = {{20{instr[31]}}, instr[31:25], instr[11:7]};
    wire [31:0] imm_b  = {{19{instr[31]}}, instr[31], instr[7],
                           instr[30:25], instr[11:8], 1'b0};
    wire [31:0] imm_u  = {instr[31:12], 12'd0};
    wire [31:0] imm_j  = {{11{instr[31]}}, instr[31], instr[19:12],
                           instr[20], instr[30:21], 1'b0};

    wire [31:0] rdata1, rdata2;
    reg  [31:0] reg_wdata;
    reg  [4:0]  reg_rd;
    reg         reg_we;

    imem IMEM (.addr(pc), .instr(instr));
    regfile RF (.clk(clk), .rst(rst), .rs1(rs1), .rs2(rs2),
                .rd(reg_rd), .we(reg_we & active),
                .wdata(reg_wdata), .rdata1(rdata1), .rdata2(rdata2));

    reg [3:0] alu_ctrl;
    always @(*) begin
        alu_ctrl = 4'd0;
        if (opcode == `OP_ALUR) begin
            if (funct7 == 7'b0000001) begin
                alu_ctrl = 4'd10; // MUL
            end else begin
                case ({funct7[5], funct3})
                    4'b0000: alu_ctrl = 4'd0;
                    4'b1000: alu_ctrl = 4'd1;
                    4'b0001: alu_ctrl = 4'd5;
                    4'b0010: alu_ctrl = 4'd8;
                    4'b0011: alu_ctrl = 4'd9;
                    4'b0100: alu_ctrl = 4'd4;
                    4'b0101: alu_ctrl = 4'd6;
                    4'b1101: alu_ctrl = 4'd7;
                    4'b0110: alu_ctrl = 4'd3;
                    4'b0111: alu_ctrl = 4'd2;
                    default: alu_ctrl = 4'd0;
                endcase
            end
        end else if (opcode == `OP_ALUI) begin
            case (funct3)
                3'd0: alu_ctrl = 4'd0;
                3'd1: alu_ctrl = 4'd5;
                3'd2: alu_ctrl = 4'd8;
                3'd3: alu_ctrl = 4'd9;
                3'd4: alu_ctrl = 4'd4;
                3'd5: alu_ctrl = funct7[5] ? 4'd7 : 4'd6;
                3'd6: alu_ctrl = 4'd3;
                3'd7: alu_ctrl = 4'd2;
                default: alu_ctrl = 4'd0;
            endcase
        end
    end

    wire [31:0] alu_b      = (opcode == `OP_ALUR) ? rdata2 : imm_i;
    wire [31:0] alu_result;
    wire        alu_zero;
    alu ALU (.a(rdata1), .b(alu_b), .op(alu_ctrl),
             .result(alu_result), .zero(alu_zero));

    wire [31:0] eff_addr   = rdata1 + ((opcode == `OP_STORE) ? imm_s : imm_i);
    assign dmem_read  = ((opcode == `OP_LOAD)  && active) ? 1'b1 : 1'b0;
    assign dmem_write = ((opcode == `OP_STORE) && active) ? 1'b1 : 1'b0;
    assign dmem_addr  = eff_addr;
    assign dmem_wdata = rdata2;

    assign aes_cs    = (eff_addr[31:16] == 16'hFFFF) ? 1'b1 : 1'b0;
    assign aes_we    = (dmem_write && aes_cs) ? 1'b1 : 1'b0;
    assign aes_reg   = eff_addr[5:2];
    assign aes_wdata = rdata2;

    assign current_instr   = instr;
    assign instr_valid_out = active;

    always @(posedge clk or posedge rst) begin
        if (rst) begin
            pc <= 32'd0; reg_we <= 1'b0;
            reg_rd <= 5'd0; reg_wdata <= 32'd0;
        end else if (active) begin
            reg_we <= 1'b0;
            reg_rd <= rd;
            case (opcode)
                `OP_ALUR, `OP_ALUI: begin
                    reg_wdata <= alu_result; reg_we <= 1'b1; pc <= pc + 32'd4; end
                `OP_LUI: begin
                    reg_wdata <= imm_u; reg_we <= 1'b1; pc <= pc + 32'd4; end
                `OP_AUIPC: begin
                    reg_wdata <= pc + imm_u; reg_we <= 1'b1; pc <= pc + 32'd4; end
                `OP_JAL: begin
                    reg_wdata <= pc + 32'd4; reg_we <= 1'b1; pc <= pc + imm_j; end
                `OP_JALR: begin
                    reg_wdata <= pc + 32'd4; reg_we <= 1'b1;
                    pc <= (rdata1 + imm_i) & 32'hFFFFFFFE; end
                `OP_LOAD: begin
                    reg_wdata <= dmem_rdata; reg_we <= 1'b1; pc <= pc + 32'd4; end
                `OP_STORE: begin
                    pc <= pc + 32'd4; end
                `OP_BRANCH: begin
                    case (funct3)
                        3'd0: pc <= alu_zero     ? pc+imm_b : pc+32'd4;
                        3'd1: pc <= (!alu_zero)  ? pc+imm_b : pc+32'd4;
                        3'd4: pc <= alu_result[0]? pc+imm_b : pc+32'd4;
                        3'd5: pc <= (!alu_result[0])? pc+imm_b : pc+32'd4;
                        default: pc <= pc + 32'd4;
                    endcase
                end
                default: pc <= pc + 32'd4;
            endcase
        end
    end
endmodule

// ============================================================
// SECTION 13: P-CORE (5-stage pipeline)
// ============================================================
module pcore (
    input  wire        clk, rst,
    input  wire        active,
    output wire        dmem_read, dmem_write,
    output wire [31:0] dmem_addr, dmem_wdata,
    input  wire [31:0] dmem_rdata,
    output wire [31:0] current_instr,
    output wire        instr_valid_out
);
    // IF
    reg  [31:0] IF_pc;
    wire [31:0] IF_instr;
    imem IMEM (.addr(IF_pc), .instr(IF_instr));

    // IF/ID
    reg [31:0] ID_pc, ID_instr;
    reg        ID_valid;

    wire [6:0] ID_op  = ID_instr[6:0];
    wire [4:0] ID_rd  = ID_instr[11:7];
    wire [2:0] ID_f3  = ID_instr[14:12];
    wire [4:0] ID_rs1 = ID_instr[19:15];
    wire [4:0] ID_rs2 = ID_instr[24:20];
    wire [6:0] ID_f7  = ID_instr[31:25];
    wire [31:0] ID_imm_i = {{20{ID_instr[31]}}, ID_instr[31:20]};
    wire [31:0] ID_imm_s = {{20{ID_instr[31]}}, ID_instr[31:25], ID_instr[11:7]};
    wire [31:0] ID_imm_b = {{19{ID_instr[31]}}, ID_instr[31], ID_instr[7],
                             ID_instr[30:25], ID_instr[11:8], 1'b0};
    wire [31:0] ID_imm_u = {ID_instr[31:12], 12'd0};
    wire [31:0] ID_imm_j = {{11{ID_instr[31]}}, ID_instr[31], ID_instr[19:12],
                             ID_instr[20], ID_instr[30:21], 1'b0};

    wire [31:0] RF_rdata1, RF_rdata2;
    reg  [31:0] WB_wdata;
    reg  [4:0]  WB_rd;
    reg         WB_we;

    regfile RF (.clk(clk), .rst(rst), .rs1(ID_rs1), .rs2(ID_rs2),
                .rd(WB_rd), .we(WB_we & active),
                .wdata(WB_wdata), .rdata1(RF_rdata1), .rdata2(RF_rdata2));

    // ID/EX
    reg [31:0] EX_pc, EX_r1, EX_r2;
    reg [31:0] EX_imm_i, EX_imm_s, EX_imm_b, EX_imm_u, EX_imm_j;
    reg [4:0]  EX_rs1, EX_rs2, EX_rd;
    reg [6:0]  EX_op;
    reg [2:0]  EX_f3;
    reg [6:0]  EX_f7;
    reg        EX_valid;

    // EX
    reg  [3:0]  EX_alu_ctrl;
    reg  [31:0] EX_alu_a, EX_alu_b;
    wire [31:0] EX_alu_result;
    wire        EX_alu_zero;

    always @(*) begin
        EX_alu_ctrl = 4'd0;
        EX_alu_a    = EX_r1;
        EX_alu_b    = EX_r2;
        if (EX_op == `OP_ALUR) begin
            if (EX_f7 == 7'b0000001) begin
                EX_alu_ctrl = 4'd10;
            end else begin
                case ({EX_f7[5], EX_f3})
                    4'b0000: EX_alu_ctrl=4'd0;
                    4'b1000: EX_alu_ctrl=4'd1;
                    4'b0001: EX_alu_ctrl=4'd5;
                    4'b0010: EX_alu_ctrl=4'd8;
                    4'b0011: EX_alu_ctrl=4'd9;
                    4'b0100: EX_alu_ctrl=4'd4;
                    4'b0101: EX_alu_ctrl=4'd6;
                    4'b1101: EX_alu_ctrl=4'd7;
                    4'b0110: EX_alu_ctrl=4'd3;
                    4'b0111: EX_alu_ctrl=4'd2;
                    default: EX_alu_ctrl=4'd0;
                endcase
            end
        end else if (EX_op == `OP_ALUI) begin
            EX_alu_b = EX_imm_i;
            case (EX_f3)
                3'd0: EX_alu_ctrl=4'd0;
                3'd1: EX_alu_ctrl=4'd5;
                3'd2: EX_alu_ctrl=4'd8;
                3'd3: EX_alu_ctrl=4'd9;
                3'd4: EX_alu_ctrl=4'd4;
                3'd5: EX_alu_ctrl = EX_f7[5] ? 4'd7 : 4'd6;
                3'd6: EX_alu_ctrl=4'd3;
                3'd7: EX_alu_ctrl=4'd2;
                default: EX_alu_ctrl=4'd0;
            endcase
        end else if (EX_op == `OP_LOAD || EX_op == `OP_JALR) begin
            EX_alu_b = EX_imm_i;
        end else if (EX_op == `OP_STORE) begin
            EX_alu_b = EX_imm_s;
        end else if (EX_op == `OP_LUI) begin
            EX_alu_a = 32'd0; EX_alu_b = EX_imm_u;
        end else if (EX_op == `OP_AUIPC) begin
            EX_alu_a = EX_pc; EX_alu_b = EX_imm_u;
        end
    end

    alu EX_ALU (.a(EX_alu_a), .b(EX_alu_b), .op(EX_alu_ctrl),
                .result(EX_alu_result), .zero(EX_alu_zero));

    wire EX_br_taken = ((EX_op == `OP_BRANCH) && (
        ((EX_f3==3'd0) && EX_alu_zero) ||
        ((EX_f3==3'd1) && (!EX_alu_zero)) ||
        ((EX_f3==3'd4) && EX_alu_result[0]) ||
        ((EX_f3==3'd5) && (!EX_alu_result[0])))) ? 1'b1 : 1'b0;

    wire [31:0] EX_br_target = EX_pc + EX_imm_b;

    // EX/MEM
    reg [31:0] MEM_alu, MEM_r2, MEM_pc;
    reg [4:0]  MEM_rd;
    reg [6:0]  MEM_op;
    reg [2:0]  MEM_f3;
    reg        MEM_valid;

    assign dmem_read  = ((MEM_op==`OP_LOAD)  && MEM_valid && active) ? 1'b1 : 1'b0;
    assign dmem_write = ((MEM_op==`OP_STORE) && MEM_valid && active) ? 1'b1 : 1'b0;
    assign dmem_addr  = MEM_alu;
    assign dmem_wdata = MEM_r2;

    // MEM/WB
    reg [31:0] WB_alu, WB_mem, WB_pc4;
    reg [6:0]  WB_op;
    reg        WB_valid;

    always @(*) begin
        WB_we    = 1'b0;
        WB_wdata = WB_alu;
        if (WB_valid) begin
            case (WB_op)
                `OP_ALUR,`OP_ALUI,`OP_LUI,`OP_AUIPC:
                    begin WB_wdata=WB_alu; WB_we=1'b1; end
                `OP_LOAD:
                    begin WB_wdata=WB_mem; WB_we=1'b1; end
                `OP_JAL,`OP_JALR:
                    begin WB_wdata=WB_pc4; WB_we=1'b1; end
                default: WB_we=1'b0;
            endcase
        end
    end

    wire bp_predict;
    branch_predictor BP (
        .clk(clk), .rst(rst), .pc(IF_pc),
        .branch_taken(EX_br_taken),
        .branch_valid(EX_valid && (EX_op==`OP_BRANCH)),
        .branch_pc(EX_pc), .predict_taken(bp_predict)
    );

    reg branch_flush;

    always @(posedge clk or posedge rst) begin
        if (rst || !active) begin
            IF_pc<=32'd0; branch_flush<=1'b0;
            ID_pc<=32'd0; ID_instr<=32'h13; ID_valid<=1'b0;
            EX_pc<=32'd0; EX_r1<=32'd0; EX_r2<=32'd0;
            EX_imm_i<=32'd0; EX_imm_s<=32'd0; EX_imm_b<=32'd0;
            EX_imm_u<=32'd0; EX_imm_j<=32'd0;
            EX_rs1<=5'd0; EX_rs2<=5'd0; EX_rd<=5'd0;
            EX_op<=`OP_FENCE; EX_f3<=3'd0; EX_f7<=7'd0; EX_valid<=1'b0;
            MEM_alu<=32'd0; MEM_r2<=32'd0; MEM_pc<=32'd0;
            MEM_rd<=5'd0; MEM_op<=`OP_FENCE; MEM_f3<=3'd0; MEM_valid<=1'b0;
            WB_alu<=32'd0; WB_mem<=32'd0; WB_pc4<=32'd0;
            WB_op<=`OP_FENCE; WB_valid<=1'b0;
        end else begin
            branch_flush <= 1'b0;
            // PC update
            if (EX_valid && (EX_op==`OP_BRANCH) && EX_br_taken) begin
                IF_pc <= EX_br_target; branch_flush <= 1'b1;
            end else if (EX_valid && (EX_op==`OP_JAL)) begin
                IF_pc <= EX_pc + EX_imm_j;
            end else if (EX_valid && (EX_op==`OP_JALR)) begin
                IF_pc <= (EX_r1 + EX_imm_i) & 32'hFFFFFFFE;
            end else begin
                IF_pc <= IF_pc + 32'd4;
            end
            // IF->ID
            if (branch_flush) begin
                ID_instr<=32'h00000013; ID_valid<=1'b0;
            end else begin
                ID_instr<=IF_instr; ID_pc<=IF_pc; ID_valid<=1'b1;
            end
            // ID->EX
            EX_pc<=ID_pc; EX_r1<=RF_rdata1; EX_r2<=RF_rdata2;
            EX_imm_i<=ID_imm_i; EX_imm_s<=ID_imm_s;
            EX_imm_b<=ID_imm_b; EX_imm_u<=ID_imm_u;
            EX_imm_j<=ID_imm_j; EX_rs1<=ID_rs1; EX_rs2<=ID_rs2;
            EX_rd<=ID_rd; EX_op<=ID_op; EX_f3<=ID_f3;
            EX_f7<=ID_f7; EX_valid<=ID_valid && (!branch_flush);
            // EX->MEM
            MEM_alu<=EX_alu_result; MEM_r2<=EX_r2;
            MEM_rd<=EX_rd; MEM_op<=EX_op; MEM_f3<=EX_f3;
            MEM_pc<=EX_pc; MEM_valid<=EX_valid;
            // MEM->WB
            WB_alu<=MEM_alu; WB_mem<=dmem_rdata;
            WB_pc4<=MEM_pc+32'd4;
            WB_op<=MEM_op; WB_valid<=MEM_valid;
        end
    end

    assign current_instr   = IF_instr;
    assign instr_valid_out = active;
endmodule

// ============================================================
// SECTION 14: TOP-LEVEL
// ============================================================
module hetero_4core_top (
    input  wire        clk, rst,
    input  wire [7:0]  therm_pcore,
    input  wire [7:0]  therm_ecore,
    output wire        pd_pcore_en,
    output wire        pd_ecore_en,
    output wire        pd_l2_retain,
    output wire        pd_aes_en,
    output wire [1:0]  migration_state
);
    reg  p_active, e_active;
    wire [1:0] cur_type = p_active ? 2'd1 : 2'd0;

    // Feature / perceptron wires
    wire [7:0] feat_mix, feat_stride, feat_branch, feat_therm;
    wire       win_valid;
    wire [1:0] mig_rec;
    wire       mig_strong;

    // DM wires
    wire        dm_r0,dm_w0,dm_r1,dm_w1,dm_r2,dm_w2,dm_r3,dm_w3;
    wire [31:0] dm_a0,dm_d0,dm_q0;
    wire [31:0] dm_a1,dm_d1,dm_q1;
    wire [31:0] dm_a2,dm_d2,dm_q2;
    wire [31:0] dm_a3,dm_d3,dm_q3;

    // L2 wires
    wire        l2_req0,l2_req1;
    wire [31:0] l2_a0,l2_a1,l2_q0,l2_q1;
    wire        l2_ack0,l2_ack1;

    // Snoop bus (P-Core 0 broadcasts)
    wire [31:0] snoop_addr  = dm_a0;
    wire [1:0]  snoop_cmd   = 2'b11;
    wire        snoop_valid = dm_w0 & p_active;

    // Instr wires
    wire [31:0] pc0_instr, pc1_instr, ec0_instr, ec1_instr;
    wire        pv0, pv1, ev0, ev1;

    // AES wires
    wire        aes_cs2,aes_we2,aes_cs3,aes_we3;
    wire [3:0]  aes_reg2, aes_reg3;
    wire [31:0] aes_wd2, aes_wd3, aes_rd;

    // ---- L1 caches ----
    l1_cache L1C0 (.clk(clk),.rst(rst),
        .mem_read(dm_r0),.mem_write(dm_w0),
        .addr(dm_a0),.wdata(dm_d0),.rdata(dm_q0),.hit(),
        .bus_req(),.bus_grant(1'b1),.bus_addr(),.bus_cmd(),
        .snoop_addr(snoop_addr),.snoop_cmd(snoop_cmd),.snoop_valid(snoop_valid),
        .l2_req(l2_req0),.l2_addr(l2_a0),.l2_rdata(l2_q0),.l2_ack(l2_ack0));

    l1_cache L1C1 (.clk(clk),.rst(rst),
        .mem_read(dm_r1),.mem_write(dm_w1),
        .addr(dm_a1),.wdata(dm_d1),.rdata(dm_q1),.hit(),
        .bus_req(),.bus_grant(1'b1),.bus_addr(),.bus_cmd(),
        .snoop_addr(snoop_addr),.snoop_cmd(snoop_cmd),.snoop_valid(snoop_valid),
        .l2_req(l2_req1),.l2_addr(l2_a1),.l2_rdata(l2_q1),.l2_ack(l2_ack1));

    l1_cache L1C2 (.clk(clk),.rst(rst),
        .mem_read(dm_r2),.mem_write(dm_w2),
        .addr(dm_a2),.wdata(dm_d2),.rdata(dm_q2),.hit(),
        .bus_req(),.bus_grant(1'b1),.bus_addr(),.bus_cmd(),
        .snoop_addr(snoop_addr),.snoop_cmd(snoop_cmd),.snoop_valid(snoop_valid),
        .l2_req(),.l2_addr(),.l2_rdata(l2_q0),.l2_ack(l2_ack0));

    l1_cache L1C3 (.clk(clk),.rst(rst),
        .mem_read(dm_r3),.mem_write(dm_w3),
        .addr(dm_a3),.wdata(dm_d3),.rdata(dm_q3),.hit(),
        .bus_req(),.bus_grant(1'b1),.bus_addr(),.bus_cmd(),
        .snoop_addr(snoop_addr),.snoop_cmd(snoop_cmd),.snoop_valid(snoop_valid),
        .l2_req(),.l2_addr(),.l2_rdata(l2_q1),.l2_ack(l2_ack1));

    // ---- L2 ----
    l2_cache L2 (.clk(clk),.rst(rst),.retention_mode(pd_l2_retain),
        .req0(l2_req0),.wr0(dm_w0),.addr0(l2_a0),.wdata0(dm_d0),
        .rdata0(l2_q0),.ack0(l2_ack0),
        .req1(l2_req1),.wr1(dm_w1),.addr1(l2_a1),.wdata1(dm_d1),
        .rdata1(l2_q1),.ack1(l2_ack1));

    // ---- P-Cores ----
    pcore PC0 (.clk(clk),.rst(rst),.active(p_active),
        .dmem_read(dm_r0),.dmem_write(dm_w0),
        .dmem_addr(dm_a0),.dmem_wdata(dm_d0),.dmem_rdata(dm_q0),
        .current_instr(pc0_instr),.instr_valid_out(pv0));

    pcore PC1 (.clk(clk),.rst(rst),.active(p_active),
        .dmem_read(dm_r1),.dmem_write(dm_w1),
        .dmem_addr(dm_a1),.dmem_wdata(dm_d1),.dmem_rdata(dm_q1),
        .current_instr(pc1_instr),.instr_valid_out(pv1));

    // ---- E-Cores ----
    ecore EC0 (.clk(clk),.rst(rst),.active(e_active),
        .dmem_read(dm_r2),.dmem_write(dm_w2),
        .dmem_addr(dm_a2),.dmem_wdata(dm_d2),.dmem_rdata(dm_q2),
        .current_instr(ec0_instr),.instr_valid_out(ev0),
        .aes_cs(aes_cs2),.aes_we(aes_we2),.aes_reg(aes_reg2),.aes_wdata(aes_wd2));

    ecore EC1 (.clk(clk),.rst(rst),.active(e_active),
        .dmem_read(dm_r3),.dmem_write(dm_w3),
        .dmem_addr(dm_a3),.dmem_wdata(dm_d3),.dmem_rdata(dm_q3),
        .current_instr(ec1_instr),.instr_valid_out(ev1),
        .aes_cs(aes_cs3),.aes_we(aes_we3),.aes_reg(aes_reg3),.aes_wdata(aes_wd3));

    // ---- Semaphore ----
    wire [3:0] sem_req_v  = {2'b00, aes_cs3, aes_cs2};
    wire [3:0] sem_grant_v;
    hw_semaphore SEM (.clk(clk),.rst(rst),.req(sem_req_v),.grant(sem_grant_v));

    // ---- AES ----
    aes_accelerator AES (.clk(clk),.rst(rst),
        .cs(aes_cs2 | aes_cs3),
        .we(aes_we2 | aes_we3),
        .reg_addr(aes_cs2 ? aes_reg2 : aes_reg3),
        .wdata(aes_cs2    ? aes_wd2  : aes_wd3),
        .rdata(aes_rd),
        .sem_grant(|sem_grant_v),
        .sem_req(),.done());

    // ---- Feature extractor ----
    wire [31:0] act_instr = p_active ? pc0_instr : ec0_instr;
    wire        act_valid = p_active ? pv0        : ev0;

    feature_extractor FE (.clk(clk),.rst(rst),
        .instr(act_instr),.instr_valid(act_valid),
        .therm_reading(p_active ? therm_pcore : therm_ecore),
        .feat_instr_mix(feat_mix),.feat_mem_stride(feat_stride),
        .feat_branch_den(feat_branch),.feat_therm_delta(feat_therm),
        .window_valid(win_valid));

    // ---- Perceptron ----
    perceptron_engine PE (.clk(clk),.rst(rst),
        .feat_instr_mix(feat_mix),.feat_mem_stride(feat_stride),
        .feat_branch_den(feat_branch),.feat_therm_delta(feat_therm),
        .window_valid(win_valid),
        .migration_rec(mig_rec),.strong_signal(mig_strong),
        .current_core_type(cur_type));

    // ---- Migration controller ----
    always @(posedge clk or posedge rst) begin
        if (rst) begin p_active<=1'b0; e_active<=1'b1; end
        else if (win_valid) begin
            case (mig_rec)
                `MIG_TO_P,`MIG_STAY_P: begin p_active<=1'b1; e_active<=1'b0; end
                `MIG_TO_E,`MIG_STAY_E: begin p_active<=1'b0; e_active<=1'b1; end
                default: begin p_active<=p_active; e_active<=e_active; end
            endcase
        end
    end

    // ---- UPF outputs ----
    assign pd_pcore_en    = p_active;
    assign pd_ecore_en    = e_active;
    assign pd_l2_retain   = (~p_active) & (~e_active);
    assign pd_aes_en      = 1'b1;
    assign migration_state = mig_rec;

endmodule
