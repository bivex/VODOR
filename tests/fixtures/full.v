// Full Verilog construct coverage test fixture
module full_constructs(
  input wire clk,
  input wire rst_n,
  input wire [7:0] data_in,
  output reg [7:0] result,
  output reg ready
);
  reg [7:0] accumulator;

  // Tier 1: Core always block with if/else, case, assignments
  always @(posedge clk) begin
    if (!rst_n) begin
      result <= 8'h00;
      accumulator <= 8'h00;
      ready <= 1'b0;
    end
    else begin
      case (data_in[3:0])
        4'h0: begin
          result <= data_in;
          ready <= 1'b1;
        end
        4'h1: begin
          accumulator <= accumulator + data_in;
          result <= accumulator;
        end
        default: begin
          result <= 8'hXX;
        end
      endcase
    end
  end

  // Tier 2: forever + disable, for loop
  initial begin
    forever begin
      accumulator <= accumulator + 1;
      if (accumulator == 8'hFF) begin
        disable forever;
      end
    end

    for (i = 0; i < 8; i = i + 1) begin
      result <= result << 1;
    end
  end

  // Tier 3: while, repeat, fork/join, delay, event wait, wait condition
  initial begin
    while (accumulator != 0) begin
      accumulator <= accumulator - 1;
    end

    repeat (4) begin
      result <= result + 1;
    end

    fork
      result <= data_in;
      accumulator <= 0;
    join

    #10 result <= 8'hAA;

    @(posedge clk) result <= data_in;

    wait (ready == 1'b1) accumulator <= accumulator + 1;
  end

  // casez variant
  initial begin
    casez (data_in)
      8'b1???_????: result <= 8'hFF;
      8'b01??_????: result <= 8'h0F;
      default: result <= 8'h00;
    endcase
  end

  // casex variant
  initial begin
    casex (data_in)
      8'b1xxx_xxxx: result <= 8'hFE;
      default: result <= 8'h00;
    endcase
  end

  // Single-statement always (no begin/end)
  always @(posedge clk) result <= data_in;

  // Named begin block
  initial begin : processing_block
    result <= accumulator;
    disable processing_block;
    result <= 8'h00;
  end

  // Comments inside procedural body
  initial begin
    // This is a comment
    result <= data_in; /* inline block comment */
    accumulator <= accumulator + 1;
  end
endmodule
