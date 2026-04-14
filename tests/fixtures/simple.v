module simple(input wire clk, input wire rst_n, input wire [3:0] data, input wire [3:0] mask, output reg [3:0] result, output reg done);
  reg [3:0] counter;
  reg [3:0] temp;
  reg [3:0] accumulator;

  always @(posedge clk) begin
    if (!rst_n) begin
      done <= 1'b0;
      result <= 4'b0;
      counter <= 4'b0;
      temp <= 4'b0;
      accumulator <= 4'b0;
    end else begin
      // Action: Initialize temp register
      temp <= data & mask;

      // Action: Set accumulator to temp value
      accumulator <= temp;

      // For loop example with actions
      for (counter = 0; counter < 4; counter = counter + 1) begin
        // Action: Accumulate result
        result <= result + temp;
        // Action: Shift accumulator
        accumulator <= accumulator << 1;
      end

      // Action: Apply mask to result
      result <= result & mask;

      // While loop example with actions
      while (counter > 0) begin
        // Action: Decrement counter
        counter <= counter - 1;
        // Action: XOR operation
        temp <= temp ^ counter;
      end

      // Action: Final calculation
      accumulator <= accumulator + temp;

      // Case statement example with actions
      case (data)
        4'b0000: begin
          // Action: Clear result
          result <= 4'b0000;
          // Action: Set done
          done <= 1'b1;
        end
        4'b0001: begin
          // Action: Set result to accumulator
          result <= accumulator;
          // Action: Toggle done
          done <= ~done;
        end
        4'b0010: begin
          // Action: Bitwise OR
          result <= result | temp;
          // Action: Set done
          done <= 1'b1;
        end
        default: begin
          // Action: Complement result
          result <= ~result;
          // Action: Set done
          done <= 1'b0;
        end
      endcase

      // Forever loop example (would run infinitely if not disabled)
      forever begin
        // Action: Increment accumulator in infinite loop
        accumulator <= accumulator + 1;
        // Action: Check condition to break
        if (accumulator > 15) begin
          // Action: Disable the forever loop
          disable forever;
        end
      end

      // Disable statement example (disable named block)
      begin : named_block
        // Action: Set result in named block
        result <= accumulator;
        // Action: Disable this named block
        disable named_block;
        // This action would never execute due to disable above
        result <= 4'b1111;
      end

      // Final action: Update done status
      done <= 1'b1;
    end
  end
endmodule
