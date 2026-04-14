module simple(input wire clk, input wire rst_n, output reg done);
  always @(posedge clk) begin
    if (!rst_n) begin
      done <= 1'b0;
    end else begin
      done <= 1'b1;
    end
  end
endmodule
