module xs_bugcase_tb (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        req_read,
    input  logic        req_write,
    input  logic [7:0]  req_addr,
    input  logic [15:0] req_wdata,
    output logic [15:0] resp_data
);
    GatedSram dut (
        .clock(clk),
        .reset(!rst_n),
        .io_req_read(req_read),
        .io_req_write(req_write),
        .io_req_addr(req_addr),
        .io_req_wdata(req_wdata),
        .io_resp_data(resp_data)
    );
endmodule
