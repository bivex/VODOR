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

**Detector**: walk steps; flag any `SwitchFlowStep` where the source used `casex`. The `case_keyword` field stores `"casex"`, `"casez"`, or `"case"`.

## Tier 2 — RTL hygiene (implemented)

### S6: Mixed blocking/nonblocking assignment

| Field    | Value |
|----------|-------|
| Kind     | `mixed_blocking_nonblocking` |
| Severity | ERROR |
| Trigger  | Same variable receives both `=` and `<=` in the same always block |

```
// BAD — synthesis/simulation mismatch
always @(posedge clk) begin
    if (rst) count = 0;       // blocking
    else     count <= count + 1; // nonblocking
end

// GOOD — consistently nonblocking
always @(posedge clk) begin
    if (rst) count <= 0;
    else     count <= count + 1;
end
```

**Detector**: first pass collects all blocking and nonblocking LHS variables. Flags any variable appearing in both sets.

### S7: Missing reset in sequential block

| Field    | Value |
|----------|-------|
| Kind     | `missing_reset` |
| Severity | INFO |
| Trigger  | `always @(posedge clk)` with no if condition referencing `rst`/`reset`/`arst` |

Many FPGA designs require explicit reset for deterministic power-up behavior. Not all blocks need reset — INFO severity reflects this.

**Detector**: walk all if conditions in the block. If none contain reset signal keywords (`rst`, `reset`, `arst`, `rst_n`, `reset_n`, `async_rst`), flag.

### S8: Unsized literal

| Field    | Value |
|----------|-------|
| Kind     | `unsized_literal` |
| Severity | INFO |
| Trigger  | Assignment with bare decimal on RHS, e.g. `count <= 0` instead of `count <= 8'h00` |

```
// FLAGGED
count <= 0;      // unsized
result = 255;    // unsized

// NOT FLAGGED
count <= 8'h00;  // sized
result = 1'b1;   // sized
```

**Detector**: check action labels for `<= N` or `= N` where N is only decimal digits.

### S9: Delay in synthesizable block

| Field    | Value |
|----------|-------|
| Kind     | `delay_in_synthesizable` |
| Severity | WARNING |
| Trigger  | `#delay` inside `always @(posedge clk)` |

`#delay` is ignored by synthesis tools — it only affects simulation timing. Finding it in a clocked always block suggests copy-paste from a testbench.

**Detector**: flag any `DelayFlowStep` inside a sequential block.

### S10: Procedural continuous assignment

| Field    | Value |
|----------|-------|
| Kind     | `procedural_continuous_usage` |
| Severity | WARNING |
| Trigger  | `assign`/`force`/`deassign`/`release` inside an always block |

Procedural continuous assignments are problematic for synthesis and make intent unclear. Prefer proper register assignments.

**Detector**: flag any `ActionFlowStep` with `action_kind == PROCEDURAL_CONTINUOUS`.

### S11: Empty case branch

| Field    | Value |
|----------|-------|
| Kind     | `empty_case_branch` |
| Severity | INFO |
| Trigger  | Case label with no statements in its body |

May be intentional (state with no action) or an oversight.

**Detector**: flag any `SwitchCaseFlow` with `steps == ()`.

### S12: Deep nesting

| Field    | Value |
|----------|-------|
| Kind     | `deep_nesting` |
| Severity | INFO |
| Trigger  | if/case nesting depth >= 4 |

Deep nesting makes control flow hard to follow and often indicates a candidate for FSM decomposition or helper functions.

**Detector**: track nesting depth during walk; flag when entering if/case at depth >= 3 (the 4th level).

### S13: Large case statement

| Field    | Value |
|----------|-------|
| Kind     | `large_case` |
| Severity | INFO |
| Trigger  | case with > 16 branches |

Very large case statements may indicate a need for priority encoding review or table-driven design.

**Detector**: flag `SwitchFlowStep` with `len(cases) > 16`.

## Tier 3 — Cross-function analysis (implemented)

### S14: Multi-driver signal

| Field    | Value |
|----------|-------|
| Kind     | `multi_driver_signal` |
| Severity | ERROR |
| Trigger  | Same variable assigned in multiple always/initial blocks |

Multiple drivers on a signal cause undefined behavior in synthesis and race conditions in simulation.

**Detector**: `detect_module_smells()` — collect assigned variables per function, flag any variable appearing in more than one function.

### S15: Incomplete sensitivity list

| Field    | Value |
|----------|-------|
| Kind     | `incomplete_sensitivity` |
| Severity | WARNING |
| Trigger  | Explicit `@(a or b)` sensitivity missing signals read in the body |

```
// BAD — missing 'b' in sensitivity
always @(a)
    result = a + b;

// GOOD
always @*
    result = a + b;
```

Only checked for explicit sensitivity lists (not `@*` or edge-triggered).

**Detector**: parse signal names from sensitivity list, extract identifiers from body, flag if body reads signals not in the list.

### S16: Duplicate case label

| Field    | Value |
|----------|-------|
| Kind     | `duplicate_case_label` |
| Severity | ERROR |
| Trigger  | Two case branches with the same label value |

Duplicate labels cause the first match to always win — the second is dead code.

**Detector**: count label occurrences in each `SwitchFlowStep`, flag any appearing more than once.

### S17: Forever without disable

| Field    | Value |
|----------|-------|
| Kind     | `forever_without_disable` |
| Severity | WARNING |
| Trigger  | `forever` loop with no `disable` statement in its body |

A `forever` loop without any `disable` has no escape path. In testbenches this is common (clock generation), in RTL it's suspicious.

**Detector**: flag `ForeverFlowStep` whose body subtree contains no `DisableFlowStep`.

## False positive suppression

### Intermediate variables in sequential blocks

Blocking assignments to temporary variables that feed into nonblocking RHS are a valid pattern:

```verilog
always @(posedge clk) begin
    temp = a + b;      // intermediate — NOT flagged
    result <= temp;     // nonblocking — register assignment
end
```

**Detection**: if a variable gets only blocking assignments AND appears in the RHS of a nonblocking assignment, it's treated as intermediate.

### Default assignments above if

An `if` without `else` in combinational logic is NOT a latch risk if the variable already has a default assignment above:

```verilog
always @* begin
    result = 0;          // default — suppresses latch risk
    if (en)
        result = data;   // no else needed
end
```

**Detection**: track assigned variables linearly; only flag if then-assigned vars are not already covered by a preceding default.

## Future detectors

| # | Kind | Severity | Description |
|---|------|----------|-------------|
| S18 | `width_mismatch` | WARNING | Literal width doesn't match target signal width |
| S19 | `blocking_in_function` | INFO | Functions should use blocking `=` for return value |
| S20 | `multiple_always_same_edge` | WARNING | Multiple always blocks on same edge may indicate merged intent |
| S21 | `generate_without_parameter` | WARNING | for-generate without a parameter bound — unbounded elaboration risk |

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
