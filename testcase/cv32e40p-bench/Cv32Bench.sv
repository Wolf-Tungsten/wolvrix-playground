// Shared RTL for both simulators. RAM stays inside the simulated design.
module Cv32Bench (
    input logic clk_i,
    input logic rst_ni,
    input logic load_en_i,
    input logic [21:0] load_addr_i,
    input logic [31:0] load_data_i,
    output logic uart_valid_o,
    output logic [7:0] uart_data_o,
    output logic exit_valid_o,
    output logic [31:0] exit_code_o,
    output logic fault_o,
    output logic obs_ireq_o,
    output logic [31:0] obs_iaddr_o,
    output logic obs_dreq_o,
    output logic obs_dwe_o,
    output logic [3:0] obs_dbe_o,
    output logic [31:0] obs_daddr_o,
    output logic [31:0] obs_dwdata_o
);
    localparam integer RAM_BYTES = 4 * 1024 * 1024;
    logic [7:0] ram [0:RAM_BYTES-1];
    initial ram = '{default:8'h00};

    logic [31:0] instr_rdata, data_rdata;
    logic instr_rvalid, data_rvalid;
    logic [31:0] ticks;
    wire [21:0] ia = {obs_iaddr_o[21:2], 2'b00};
    wire [21:0] da = {obs_daddr_o[21:2], 2'b00};

    cv32e40p_top #(
        .COREV_PULP(0), .COREV_CLUSTER(0), .FPU(0), .ZFINX(0),
        .NUM_MHPMCOUNTERS(1)
    ) core (
        .clk_i(clk_i), .rst_ni(rst_ni), .pulp_clock_en_i(1'b1), .scan_cg_en_i(1'b0),
        .boot_addr_i(32'h180), .mtvec_addr_i(32'h0), .hart_id_i(32'h0),
        .dm_halt_addr_i(32'h1a110800), .dm_exception_addr_i(32'h0),
        .instr_req_o(obs_ireq_o), .instr_gnt_i(obs_ireq_o),
        .instr_addr_o(obs_iaddr_o), .instr_rvalid_i(instr_rvalid), .instr_rdata_i(instr_rdata),
        .data_req_o(obs_dreq_o), .data_gnt_i(obs_dreq_o), .data_addr_o(obs_daddr_o),
        .data_we_o(obs_dwe_o), .data_be_o(obs_dbe_o), .data_wdata_o(obs_dwdata_o),
        .data_rvalid_i(data_rvalid), .data_rdata_i(data_rdata),
        .irq_i(32'h0), .irq_ack_o(), .irq_id_o(), .debug_req_i(1'b0),
        .debug_havereset_o(), .debug_running_o(), .debug_halted_o(),
        .fetch_enable_i(1'b1), .core_sleep_o()
    );

    // Grant requests immediately; return each response after its accepting edge.
    // Reads observe pre-edge memory, including simultaneous instruction/data access.
    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            instr_rvalid <= 0;
            data_rvalid <= 0;
            instr_rdata <= 0;
            data_rdata <= 0;
            uart_valid_o <= 0;
            uart_data_o <= 0;
            exit_valid_o <= 0;
            exit_code_o <= 0;
            fault_o <= 0;
            ticks <= 0;
        end else begin
            ticks <= ticks + 1;
            instr_rvalid <= obs_ireq_o;
            data_rvalid <= obs_dreq_o;
            uart_valid_o <= 0;
            if (obs_ireq_o) begin
                instr_rdata <= {ram[ia+3], ram[ia+2], ram[ia+1], ram[ia]};
                if (obs_iaddr_o >= RAM_BYTES) fault_o <= 1;
            end
            if (obs_dreq_o) begin
                if (obs_daddr_o < RAM_BYTES) begin
                    data_rdata <= {ram[da+3], ram[da+2], ram[da+1], ram[da]};
                end else if (!obs_dwe_o && obs_daddr_o == 32'h15001004) begin
                    data_rdata <= ticks;
                end else if (obs_dwe_o && obs_daddr_o == 32'h10000000) begin
                    uart_valid_o <= 1;
                    uart_data_o <= obs_dwdata_o[7:0];
                end else if (obs_dwe_o && obs_daddr_o == 32'h20000004) begin
                    exit_valid_o <= 1;
                    exit_code_o <= obs_dwdata_o;
                end else begin
                    fault_o <= 1;
                end
            end
        end
    end

    // No RAM reset: firmware initializes BSS and the initial image covers all bytes.
    always @(posedge clk_i) begin
        if (load_en_i) begin
            ram[load_addr_i]   <= load_data_i[7:0];
            ram[load_addr_i+1] <= load_data_i[15:8];
            ram[load_addr_i+2] <= load_data_i[23:16];
            ram[load_addr_i+3] <= load_data_i[31:24];
        end else if (rst_ni && obs_dreq_o && obs_dwe_o && obs_daddr_o < RAM_BYTES) begin
            if (obs_dbe_o[0]) ram[da]   <= obs_dwdata_o[7:0];
            if (obs_dbe_o[1]) ram[da+1] <= obs_dwdata_o[15:8];
            if (obs_dbe_o[2]) ram[da+2] <= obs_dwdata_o[23:16];
            if (obs_dbe_o[3]) ram[da+3] <= obs_dwdata_o[31:24];
        end
    end
endmodule
