// ============================================================
// Behavioral Verilog generated from source code
// Source: tests/fixtures/simple.v
// ============================================================
`timescale 1ns / 1ps

// Function: always_block
module always_block (
    input  [31:0] in0,
    output reg [31:0] result
);
    initial begin
        done<=1'b0;
        result<=4'b0;
        counter<=4'b0;
        temp<=4'b0;
        accumulator<=4'b0;
        temp<=data&mask;
        accumulator<=temp;
        result<=result+temp;
        accumulator<=accumulator<<1;
        result<=result&mask;
        counter<=counter-1;
        temp<=temp^counter;
        accumulator<=accumulator+temp;
        result<=4'b0000;
        done<=1'b1;
        result<=accumulator;
        done<=~done;
        result<=result|temp;
        done<=1'b1;
        result<=~result;
        done<=1'b0;
        accumulator<=accumulator+1;
        result<=accumulator;
        result<=4'b1111;
        done<=1'b1;
    end
endmodule
