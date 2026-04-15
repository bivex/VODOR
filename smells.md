# Verilog Code Smell Detectors

Static analysis detectors that operate on the extracted control flow model to flag common RTL design errors.

## Architecture

Detectors run **after extraction** on the `ControlFlowDiagram` domain model — no re-parsing required. Each detector is a pure function `(FunctionControlFlow) -> list[Smell]`. A `SmellService` orchestrates all detectors and produces a `SmellReport` per file.

## Domain types

```
SmellSeverity: ERROR | WARNING | INFO
SmellKind:     enum of smell identifiers
SmellLocation: block_name + step_label (for human-readable pinpointing)
Smell:         kind + severity + message + location
SmellReport:   source_location + tuple[Smell, ...]
```

## Tier 1 — Synthetic bugs ( correctness )

These produce silicon bugs if missed in review.

### S1: Blocking assignment in sequential block

| Field    | Value |
|----------|-------|
| Kind     | `blocking_in_sequential` |
| Severity | ERROR |
| Trigger  | `ActionKind.ASSIGNMENT_BLOCKING` inside an `always @(posedge ...)` block |

Sequential logic must use nonblocking `<=` to prevent simulation/synthesis mismatch. Blocking `=` in a clocked block causes race conditions in simulation and may synthesize incorrectly.

```
// BAD
always @(posedge clk)
    count = count + 1;     // blocking

// GOOD
always @(posedge clk)
    count <= count + 1;    // nonblocking
```

**Detector**: walk all steps in a function; if `sensitivity` contains `posedge` or `negedge` and any `ActionFlowStep` has `action_kind == ASSIGNMENT_BLOCKING`, flag it.

### S2: Nonblocking assignment in combinational block

| Field    | Value |
|----------|-------|
| Kind     | `nonblocking_in_combinational` |
| Severity | WARNING |
| Trigger  | `ActionKind.ASSIGNMENT_NONBLOCKING` inside an `always @*` / `always @(*)` block |

Combinational logic should use blocking `=`. Nonblocking `<=` adds a delta-cycle delay that can cause simulation mismatches and makes intent unclear.

```
// BAD
always @*
    result <= a & b;       // nonblocking

// GOOD
always @*
    result = a & b;        // blocking
```

**Detector**: if `sensitivity` is `*` (or contains no edge keywords) and any `ActionFlowStep` has `action_kind == ASSIGNMENT_NONBLOCKING`, flag it.

### S3: Latch risk — incomplete if in combinational block

| Field    | Value |
|----------|-------|
| Kind     | `latch_risk_incomplete_if` |
| Severity | WARNING |
| Trigger  | `IfFlowStep` with empty `else_steps` inside a combinational block |

An `if` without `else` in combinational logic infers a latch — the signal holds its previous value when the condition is false. This is almost always unintended.

```
// BAD — infers latch
always @*
    if (en)
        result = data;

// GOOD — all paths assigned
always @*
    if (en)
        result = data;
    else
        result = 1'b0;
```

**Detector**: walk steps recursively; if any `IfFlowStep` has empty `else_steps` inside a combinational block, flag it.

### S4: Missing default in case

| Field    | Value |
|----------|-------|
| Kind     | `case_missing_default` |
| Severity | WARNING |
| Trigger  | `SwitchFlowStep` with no case whose `label == "default"` |

A `case` without `default` in combinational logic infers a latch for unhandled values. Even in sequential logic, missing `default` hides unintended state transitions.

```
// BAD — no default
always @* case (sel)
    2'b00: out = a;
    2'b01: out = b;
endcase

// GOOD
always @* case (sel)
    2'b00: out = a;
    2'b01: out = b;
    default: out = 1'b0;
endcase
```

**Detector**: walk steps recursively; if any `SwitchFlowStep` has no case with `label == "default"`, flag it.

### S5: casex usage

| Field    | Value |
|----------|-------|
| Kind     | `casex_usage` |
| Severity | INFO |
| Trigger  | `SwitchFlowStep` whose `expression` starts with `casex` |

`casex` treats both `x` and `z` as don't-care, which can mask simulation mismatches and hide bugs. `casez` (treats only `z` as don't-care) or explicit equality checks are preferred.

```
// AVOID
casex (data) ...

// PREFER
casez (data) ...
// or explicit:
case (data === 8'b1xxx_xxxx) ...
```

**Detector**: walk steps; flag any `SwitchFlowStep` where the source used `casex`. The expression field starts with `casex` — detectable from the model.

## Tier 2 — RTL hygiene (future)

| # | Kind | Severity | Description |
|---|------|----------|-------------|
| S6 | `mixed_blocking_nonblocking` | ERROR | Same signal assigned with both `=` and `<=` in the same always block |
| S7 | `multi_driver_signal` | WARNING | Same signal driven from multiple always blocks |
| S8 | `unsized_literal` | INFO | Bare numeric like `1` instead of `1'b1` or `8'hFF` |
| S9 | `inferred_latch_case` | WARNING | case without default in combinational block (variant of S4, case-specific) |
| S10 | `blocking_in_function` | INFO | Functions should use blocking `=` for return value — flag `<=` |

## Tier 3 — Structural issues (future)

| # | Kind | Severity | Description |
|---|------|----------|-------------|
| S11 | `multiple_always_same_edge` | WARNING | Multiple always blocks on same edge may indicate merged intent |
| S12 | `nested_case_depth` | INFO | case nesting > 2 levels — FSM decomposition candidate |
| S13 | `large_fanin_mux` | INFO | case with > 16 branches — consider priority encoding review |
| S14 | `generate_without_parameter` | WARNING | for-generate without a parameter bound — unbounded elaboration risk |

## Integration points

### CLI

```
vodor smell-file path/to/module.v
vodor smell-dir path/to/project
```

Output: JSON with source location + list of smells (kind, severity, message, location).

### Nassi rendering

Smells can be annotated directly on the diagram:
- Action nodes with smells get a colored border/glow
- If/case nodes with smells get a warning icon
- A smell summary bar appears above the diagram

### Batch reporting

`smell-dir` produces an aggregate summary:
- Files with most smells
- Smell kind distribution
- Per-file breakdown
