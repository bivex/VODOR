module simple(input wire clk, input wire rst_n, input wire [3:0] data, output reg [3:0] result, output reg done);
  reg [3:0] counter;

  always @(posedge clk) begin
    if (!rst_n) begin
      done <= 1'b0;
      result <= 4'b0;
      counter <= 4'b0;
    end else begin
      // For loop example
      for (counter = 0; counter < 4; counter = counter + 1) begin
        result <= result + data;
      end

      // While loop example
      while (counter > 0) begin
        counter <= counter - 1;
      end

      // Case statement example
      case (data)
        4'b0000: result <= 4'b0001;
        4'b0001: result <= 4'b0010;
        4'b0010: result <= 4'b0100;
        default: result <= 4'b1000;
      endcase

      done <= 1'b1;
    end
  end
endmodule
