// ============================================================
// Behavioral Verilog generated from source code
// Source: tests/fixtures/complex.v
// ============================================================
`timescale 1ns / 1ps

// Function: loop_block
module loop_block (
    input  [31:0] in0,
    output reg [31:0] result
);
    initial begin
        foreverbeginaccumulator<=accumulator+1;if(accumulator==8'hFF)begindisableforever;endend;
        accumulator<=accumulator+1;
        temp_a<=result;
        temp_b<=accumulator;
        result<=temp_a-temp_b;
        result<=temp_b-temp_a;
        result<=8'h00;
        ready<=1'b1;
    end
endmodule
