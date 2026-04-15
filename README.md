# VODOR

Verilog-Oriented Diagrammatic Output & Rendering. Parses Verilog source code and produces Nassi-Shneiderman control flow diagrams.

## What it does

* **Parsing** — Parses Verilog files and directories via ANTLR4, extracts a structural model of modules and procedural blocks.
* **Control flow extraction** — Extracts procedural flow from `always`, `initial`, `function`, and `task` blocks, mapping constructs into structured steps: `if`/`else`, `for`, `while`, `case`/`casez`/`casex`, `forever`, `disable`, `fork`/`join`, `#delay`, `@event`, `wait`, and action statements.
* **Nassi-Shneiderman diagrams** — Renders control flow as standalone dark-themed HTML with classic NS diagram layout (SVG triangle caps for if/else, grid columns for switch/case, nested loops, dedicated nodes for fork/delay/event/wait). Function panels show sensitivity badges and block type tags.
* **Verilog export** — Re-exports behavioral Verilog from the extracted control flow model.

## Architecture

DDD-inspired layered monolith with hexagonal boundaries:

* `domain` — model, invariants, ports
* `application` — use cases, DTOs
* `infrastructure` — ANTLR adapter, filesystem, rendering, regex-based control flow extractor
* `presentation` — CLI

## Quick Start

```bash
# Install
uv sync --extra dev

# Generate parser from grammar
uv run python scripts/generate_verilog_parser.py

# Parse a file
uv run vodor parse-file path/to/module.v

# Generate Nassi-Shneiderman HTML
uv run vodor nassi-file path/to/module.v
uv run vodor nassi-file path/to/module.v --out output.html

# Batch diagrams for a directory
uv run vodor nassi-dir path/to/project --out output/

# Export behavioral Verilog
uv run vodor verilog-file path/to/module.v
uv run vodor verilog-dir path/to/project --out output/
```

## Verilog Construct Support

### Procedural constructs

How the pipeline handles each construct found inside `always`, `initial`, `function`, and `task` blocks.

#### Tier 1 — Core RTL (every design)

| Construct | Extracted | Rendered | Notes |
|-----------|:---------:|:--------:|-------|
| `if` / `else` / `else if` | yes | yes | Nested arbitrarily deep, SVG triangle caps |
| `case` / `casez` / `casex` | yes | yes | Multi-column grid, nested bodies |
| Nonblocking `<=` | yes | yes | Sequential logic assignments |
| Blocking `=` | yes | yes | Combinational logic assignments |
| `begin` / `end` | yes | yes | Flattened into parent sequence |
| Named `begin : label` | yes | yes | Recognized and flattened |

#### Tier 2 — Common patterns (most designs)

| Construct | Extracted | Rendered | Notes |
|-----------|:---------:|:--------:|-------|
| `for` loop | yes | yes | Header + body |
| `forever` loop | yes | yes | Clock generation, infinite processes |
| `disable` | yes | yes | Break out of named blocks / loops |
| `while` loop | yes | yes | Condition + body |
| `repeat` loop | yes | yes | Count + body, repeat-while footer |
| `$display`, `$monitor`, etc. | flat | yes | Preserved as action text |
| Task / function calls | flat | yes | Preserved as action text |

#### Tier 3 — Testbench constructs

| Construct | Extracted | Rendered | Notes |
|-----------|:---------:|:--------:|-------|
| `fork` / `join` / `join_any` / `join_none` | yes | yes | Fork header + join type footer |
| `#` delay control | yes | yes | Delay value + body |
| `@` event control | yes | yes | Event expression + body |
| `wait (expr)` | yes | yes | Condition + body |
| `->` event trigger | flat | yes | Preserved as text |
| `assign` / `force` / `release` | flat | yes | Procedural continuous assignments |

### Structural blocks

| Construct | Handled | Notes |
|-----------|:-------:|-------|
| `always @(event)` | yes | Extracted as function panel with sensitivity badge |
| `always @*` | yes | Combinational sensitivity |
| `initial begin` | yes | Extracted as function panel |
| Single-statement `always` | yes | No `begin`/`end` wrapper required |
| `function` ... `endfunction` | yes | Name + signature from header, body extracted |
| `task` ... `endtask` | yes | Name + signature from header, body extracted |
| `generate` blocks | no | Elaboration-time, not procedural |

### HTML rendering features

| Feature | Description |
|---------|-------------|
| Sensitivity badge | `@(posedge clk)` shown as a colored tag in the function panel header |
| Block type tag | `ALWAYS`, `INITIAL`, `FUNCTION`, `TASK` badges per panel |
| SVG triangle caps | Classic NS diagram if/else with Yes/No labels |
| Grid columns | Switch/case rendered as side-by-side columns |
| Depth-coded colors | Nested if/else triangles cycle through blue/green/purple/teal/amber |
| Dark theme | Editor-first dark palette with accent stripes per construct type |

### Comments

Comments (`//` line and `/* block */`) inside procedural bodies are stripped before extraction — no spurious action nodes.

### Known limitations

- **Multi-line statements** may not parse correctly — extractor works line-by-line.
- **`generate` blocks** are elaboration-time and not treated as procedural flow.
- **SystemVerilog** constructs (`always_comb`, `always_ff`, `final`, `class`) are not recognized.
