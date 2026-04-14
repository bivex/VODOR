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

## Supported Control Flow

| Construct | Step type | Notes |
| --- | --- | --- |
| Assignments | `ActionFlowStep` | Blocking (`=`) and nonblocking (`<=`) |
| `if` / `else` | `IfFlowStep` | Nested then/else with `else if` chains |
| `for` | `ForInFlowStep` | Full header + body |
| `while` | `WhileFlowStep` | Condition + body |
| `repeat` | `RepeatWhileFlowStep` | Count + body |
| `forever` | `ForeverFlowStep` | Infinite loop body |
| `case` / `casez` / `casex` | `SwitchFlowStep` | Multi-column case grid with nested bodies |
| `disable` | `DisableFlowStep` | Named block/loop break |

## Constraints

The ANTLR grammar is sourced from `antlr/grammars-v4/verilog`. Community grammars may lag behind vendor dialects and macro-heavy codebases. Grammar version and diagnostics are included in parse reports.
