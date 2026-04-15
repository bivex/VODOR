// ============================================================
// Behavioral Verilog generated from source code
// Source: tests/fixtures/full.v
// ============================================================
`timescale 1ns / 1ps

// Function: always_block
module always_block (
    input  [31:0] in0,
    output reg [31:0] result
);
    initial begin
        result<=8'h00;
        accumulator<=8'h00;
        ready<=1'b0;
        result<=data_in;
        ready<=1'b1;
        accumulator<=accumulator+data_in;
        result<=accumulator;
        result<=8'hXX;
    end
endmodule


// Function: always_block
module always_block (
    input  [31:0] in0,
    output reg [31:0] result
);
    initial begin
        result<=data_in;
    end
endmodule
