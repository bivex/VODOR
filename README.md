# VODOR

Verilog-Oriented Diagrammatic Output & Rendering. Parses Verilog source code and produces Nassi-Shneiderman control flow diagrams.

## What it does

* **Parsing** — Parses Verilog files and directories via ANTLR4, extracts a structural model of modules and procedural blocks.
* **Control flow extraction** — Extracts procedural flow from `always` and `initial` blocks, mapping constructs into structured steps: `if`/`else`, `for`, `while`, `case`, `forever`, `disable`, and action statements.
* **Nassi-Shneiderman diagrams** — Renders control flow as standalone dark-themed HTML with classic NS diagram layout (SVG triangle caps for if/else, grid columns for switch/case, nested loops). Supports single-file and batch directory output.
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
uv run swifta parse-file path/to/module.v

# Generate Nassi-Shneiderman HTML
uv run swifta nassi-file path/to/module.v
uv run swifta nassi-file path/to/module.v --out output.html

# Batch diagrams for a directory
uv run swifta nassi-dir path/to/project --out output/

# Export behavioral Verilog
uv run swifta verilog-file path/to/module.v
uv run swifta verilog-dir path/to/project --out output/
```

## Verilog Procedural Construct Support

How the pipeline handles each construct found inside `always` and `initial` blocks.

### Tier 1 — Core RTL (every design)

Every synchronous block uses these. Fully supported.

| Construct | Extracted | Rendered | Notes |
|-----------|:---------:|:--------:|-------|
| `if` / `else` / `else if` | yes | yes | Nested arbitrarily deep |
| `case` / `casez` / `casex` | yes | yes | Multi-column grid, nested bodies |
| Nonblocking `<=` | yes | yes | Sequential logic assignments |
| Blocking `=` | yes | yes | Combinational logic assignments |
| `begin` / `end` | yes | yes | Flattened into parent sequence |
| Named `begin : label` | yes | yes | Recognized and flattened |

### Tier 2 — Common patterns (most designs)

Used in state machines, testbenches, parameterized logic.

| Construct | Extracted | Rendered | Notes |
|-----------|:---------:|:--------:|-------|
| `for` loop | yes | yes | Header + body |
| `forever` loop | yes | yes | Clock generation, infinite processes |
| `disable` | yes | yes | Break out of named blocks / loops |
| `while` loop | yes | yes | Condition + body |
| `repeat` loop | yes | yes | Count + body |
| `$display`, `$monitor`, etc. | flat | yes | Preserved as action text |
| Task / function calls | flat | yes | Preserved as action text |

### Tier 3 — Testbench constructs

Timing and concurrency constructs. Structurally extracted with dedicated diagram nodes.

| Construct | Extracted | Rendered | Notes |
|-----------|:---------:|:--------:|-------|
| `fork` / `join` / `join_any` / `join_none` | yes | yes | Fork body + join type footer |
| `#` delay control | yes | yes | Delay value + body |
| `@` event control | yes | yes | Event expression + body |
| `wait (expr)` | yes | yes | Condition + body |
| `->` event trigger | flat | yes | Preserved as text |
| `assign`/`force`/`release` | flat | yes | Procedural continuous assignments |

### Structural blocks

| Construct | Handled | Notes |
|-----------|:-------:|-------|
| `always @(event)` | yes | Extracted as function panel with sensitivity list |
| `initial begin` | yes | Extracted as function panel |
| Single-statement `always` | yes | No `begin`/`end` wrapper required |
| `function` / `task` bodies | no | Only always/initial scanned |
| `generate` blocks | no | Elaboration-time, not procedural |

### Comments

Comments inside procedural bodies are stripped before extraction — no spurious action nodes.

### Known limitations

- **Multi-line statements** may not parse correctly — extractor works line-by-line.
- **`function`/`task` bodies** are not yet extracted — only `always`/`initial` blocks are scanned.
- **`generate` blocks** are elaboration-time and not treated as procedural flow.

## Constraints

The ANTLR grammar is sourced from `antlr/grammars-v4/verilog`. Community grammars may lag behind vendor dialects and macro-heavy codebases. Grammar version and diagnostics are included in parse reports.
