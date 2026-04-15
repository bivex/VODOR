module structural_demo #(
  parameter WIDTH = 8,
  parameter DEPTH = 16
)(
  input  wire             clk,
  input  wire             rst_n,
  input  wire [WIDTH-1:0] data_in,
  output reg  [WIDTH-1:0] data_out,
  output wire             valid
);

  wire [WIDTH-1:0] intermediate;
  localparam MAX_VAL = 8'hFF;
  reg [WIDTH-1:0] buffer [0:DEPTH-1];
  integer count;

  // Continuous assignments
  assign intermediate = data_in & {WIDTH{rst_n}};
  assign valid = (count > 0);

  // Module instantiation
  alu #(.WIDTH(WIDTH)) u_alu (
    .a(data_in),
    .b(intermediate),
    .result(data_out)
  );

  // Generate block (for-generate)
  genvar i;
  generate
    for (i = 0; i < DEPTH; i = i + 1) begin : gen_buffer
      dff #(.WIDTH(WIDTH)) u_dff (
        .clk(clk),
        .rst_n(rst_n),
        .d(buffer[i]),
        .q(buffer[(i+1) % DEPTH])
      );
    end
  endgenerate

  // Procedural block
  always @(posedge clk) begin
    if (!rst_n) begin
      data_out <= {WIDTH{1'b0}};
      count <= 0;
    end else begin
      data_out <= intermediate;
      count <= count + 1;
    end
  end
endmodule
