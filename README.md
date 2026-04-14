# Swifta

Swifta is a simple, scalable monolith for parsing Verilog source code through ANTLR while keeping the architecture clean enough for future semantic analysis, indexing, and export pipelines.

The project starts from the domain, not from the framework:

* business goal: convert Verilog source into a stable structural model for downstream tooling
* architectural style: DDD-inspired layered monolith with hexagonal boundaries
* parser engine: ANTLR4 with the public Verilog grammar from `antlr/grammars-v4`
* current delivery channel: CLI that parses a file or a directory and returns versioned JSON

## What the system does

Today the system supports:

* **Parsing Verilog code**
  * parsing one Verilog file
  * parsing a directory of Verilog files
  * extracting a lightweight structural model: modules and procedural blocks
  * reporting syntax diagnostics as part of the contract

* **Control flow extraction**
  * extracting procedural flow from `always` and `initial` blocks
  * mapping basic constructs into diagram steps (`if`, `while`, `for`, `case`, action statements)

* **Nassi-Shneiderman diagrams**
  * building a Nassi-Shneiderman HTML diagram for one Verilog file
  * building diagram bundles for entire directories with index page
  * HTML output suitable for local viewing and sharing

* **Architecture**
  * keeping parser infrastructure behind ports so the application layer stays independent from ANTLR, filesystem, and CLI details

## Architecture

The codebase is split into four explicit layers:

* `domain`: domain model, invariants, ports, and domain events
* `application`: use cases and DTOs
* `infrastructure`: ANTLR adapter, filesystem adapters, rendering, event publishing
* `presentation`: CLI contract

See the full design docs in `docs/`.

## Quick Start

1. Install dependencies:

```bash
uv sync --extra dev
```

2. Generate the Verilog parser from grammar files:

```bash
uv run python scripts/generate_verilog_parser.py
```

3. Parse a single file:

```bash
uv run swifta parse-file path/to/module.v
```

4. Parse a directory:

```bash
uv run swifta parse-dir path/to/project
```

5. Build a Nassi-Shneiderman diagram for a Verilog file:

```bash
uv run swifta nassi-file path/to/module.v --out output/module.nassi.html
```

6. Build Nassi-Shneiderman diagrams for an entire directory:

```bash
uv run swifta nassi-dir path/to/project --out output/nassi-bundle
```

## Action/Step Support Matrix

Below is the current state against the control-flow step dictionary (`ControlFlowStep` model in `src/swifta/domain/control_flow.py`).

| Step / Action | Status now | Notes |
| --- | --- | --- |
| `ActionFlowStep` | Supported | Any non-recognized procedural line becomes action text. |
| `IfFlowStep` | Supported | `if (...)` with nested `then`/`else` bodies fully parsed structurally. |
| `WhileFlowStep` | Supported | `while (...)` with nested body fully parsed. |
| `ForInFlowStep` | Supported | Verilog `for (...)` with nested body fully parsed. |
| `SwitchFlowStep` | Partially supported | `case (...)` recognized and case items parsed into `SwitchCaseFlow`, but nested structures within cases may need refinement. |
| `GuardFlowStep` | Not implemented | Swift-only concept; no direct Verilog mapping yet. |
| `RepeatWhileFlowStep` | Supported | Equivalent `repeat (...)` with nested body fully parsed. |
| `DoCatchFlowStep` | Not implemented | Swift-only concept; keep unsupported for Verilog flow. |
| `DeferFlowStep` | Not implemented | Swift-only concept; keep unsupported for Verilog flow. |

### What should be added next

1. Refine `SwitchFlowStep` case parsing to handle nested control flow within case bodies.
2. Add support for more complex Verilog constructs (e.g., disable, wait, event triggers).
3. Consider language-specific refinements or splitting Swift-only step types into separate schemas.
4. Add support for Verilog-specific control flow patterns not covered by current steps.

## Constraints and honesty

The current ANTLR grammar is sourced from `antlr/grammars-v4/verilog/verilog`. Like any community grammar, it can lag behind vendor-specific dialects and unusual macro-heavy codebases. Swifta surfaces grammar version and diagnostics in runtime reports so downstream consumers can make informed integration decisions.

## Migration Note

The project is migrated to Verilog input (`.v`) across parser, repository, CLI, and tests.  
Some symbol names still include legacy "Swift" aliases for temporary backward compatibility in imports only.

## Next Steps

Useful future extensions:

* richer Verilog/SystemVerilog-aware control flow extraction
* symbol graph export
* semantic passes on top of the structural model
* integration adapters for external analysis tools
* incremental parsing and caching
* interactive HTML diagrams with collapsible nodes
* export to other diagram formats (SVG, PNG, Mermaid)
