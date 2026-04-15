"""Verilog code smell detectors operating on the extracted control flow model."""

from __future__ import annotations

import re

from vodor.domain.control_flow import (
    ActionFlowStep,
    ActionKind,
    ControlFlowDiagram,
    ControlFlowStep,
    DelayFlowStep,
    DisableFlowStep,
    ForeverFlowStep,
    FunctionControlFlow,
    IfFlowStep,
    Smell,
    SmellKind,
    SmellLocation,
    SmellSeverity,
    SwitchFlowStep,
)

_VERILOG_KEYWORDS = frozenset({
    "if", "else", "begin", "end", "case", "casez", "casex", "endcase",
    "for", "while", "repeat", "forever", "fork", "join", "join_any", "join_none",
    "posedge", "negedge", "or", "and", "not", "xor", "nand", "nor", "xnor",
    "always", "initial", "wire", "reg", "integer", "parameter", "localparam",
    "input", "output", "inout", "assign", "deassign", "force", "release",
    "module", "endmodule", "function", "endfunction", "task", "endtask",
    "generate", "endgenerate", "genvar", "default", "disable",
})


# ── Public API ──


def detect_smells(function: FunctionControlFlow) -> list[Smell]:
    """Run all per-function smell detectors on a single procedural block."""
    smells: list[Smell] = []
    is_comb = _is_combinational(function.sensitivity)
    is_seq = _is_sequential(function.sensitivity)
    is_explicit = _is_explicit_sensitivity(function.sensitivity)

    # First pass: collect assignment info for S1 intermediate-var fix + S6
    blocking_vars: dict[str, list[str]] = {}
    nb_vars: dict[str, list[str]] = {}
    nb_rhs_text: list[str] = []
    _collect_assignment_info(function.steps, blocking_vars, nb_vars, nb_rhs_text)
    nb_targets = set(nb_vars.keys())

    # S6: Mixed blocking/nonblocking on same variable
    for var in sorted(set(blocking_vars) & set(nb_vars)):
        for label in blocking_vars[var]:
            smells.append(
                Smell(
                    kind=SmellKind.MIXED_BLOCKING_NONBLOCKING,
                    severity=SmellSeverity.ERROR,
                    message=f"Variable '{var}' assigned with both = and <= in same block",
                    location=SmellLocation(block_name=function.name, step_label=label),
                )
            )

    # S7: Missing reset in sequential block
    if is_seq and not _has_reset_condition(function.steps):
        smells.append(
            Smell(
                kind=SmellKind.MISSING_RESET,
                severity=SmellSeverity.INFO,
                message=f"Sequential block '{function.name}' has no reset condition",
                location=SmellLocation(block_name=function.name, step_label=""),
            )
        )

    # S15: Incomplete sensitivity (explicit non-edge, non-wildcard list)
    if is_explicit:
        sens_signals = _parse_sensitivity_signals(function.sensitivity)
        body_signals = _extract_body_signals(function.steps)
        missing = body_signals - sens_signals
        if missing:
            smells.append(
                Smell(
                    kind=SmellKind.INCOMPLETE_SENSITIVITY,
                    severity=SmellSeverity.WARNING,
                    message=f"Sensitivity list missing signals: {', '.join(sorted(missing))}",
                    location=SmellLocation(block_name=function.name, step_label=function.sensitivity or ""),
                )
            )

    # Walk for per-step smells
    _walk_steps(
        function.steps,
        function.name,
        is_comb,
        is_seq,
        smells,
        nb_targets,
        nb_rhs_text,
        frozenset(),
        0,
    )
    return smells


def detect_module_smells(diagram: ControlFlowDiagram) -> list[Smell]:
    """Cross-function smell detection (e.g. multi-driver signals)."""
    smells: list[Smell] = []

    # S14: Multi-driver signal
    # Exclude initial blocks — they don't create hardware drivers, only simulation init values
    var_to_functions: dict[str, list[str]] = {}
    for func in diagram.functions:
        if func.name.startswith("initial"):
            continue
        assigned = _collect_assigned_vars(func.steps)
        for var in assigned:
            var_to_functions.setdefault(var, []).append(func.name)

    for var, func_names in sorted(var_to_functions.items()):
        if len(func_names) > 1:
            smells.append(
                Smell(
                    kind=SmellKind.MULTI_DRIVER_SIGNAL,
                    severity=SmellSeverity.ERROR,
                    message=f"Signal '{var}' driven by multiple blocks: {', '.join(func_names)}",
                    location=SmellLocation(block_name=", ".join(func_names), step_label=var),
                )
            )

    return smells


# ── Walk ──


def _walk_steps(
    steps: tuple[ControlFlowStep, ...],
    block_name: str,
    is_comb: bool,
    is_seq: bool,
    smells: list[Smell],
    nb_targets: set[str],
    nb_rhs_text: list[str],
    parent_defaults: frozenset[str],
    nesting_depth: int,
) -> None:
    assigned_vars = set(parent_defaults)

    for step in steps:
        # ── Action steps ──
        if isinstance(step, ActionFlowStep):
            var = _extract_lhs_var(step.label)

            # S1: Blocking in sequential (with intermediate-variable fix)
            if is_seq and step.action_kind == ActionKind.ASSIGNMENT_BLOCKING:
                is_intermediate = (
                    var is not None
                    and var not in nb_targets
                    and any(var in rhs for rhs in nb_rhs_text)
                )
                if not is_intermediate:
                    smells.append(
                        Smell(
                            kind=SmellKind.BLOCKING_IN_SEQUENTIAL,
                            severity=SmellSeverity.ERROR,
                            message=f"Blocking assignment '{step.label}' in sequential block",
                            location=SmellLocation(block_name=block_name, step_label=step.label),
                        )
                    )

            # S2: Nonblocking in combinational
            if is_comb and step.action_kind == ActionKind.ASSIGNMENT_NONBLOCKING:
                smells.append(
                    Smell(
                        kind=SmellKind.NONBLOCKING_IN_COMBINATIONAL,
                        severity=SmellSeverity.WARNING,
                        message=f"Nonblocking assignment '{step.label}' in combinational block",
                        location=SmellLocation(block_name=block_name, step_label=step.label),
                    )
                )

            # S8: Unsized literal
            if step.action_kind in (
                ActionKind.ASSIGNMENT_BLOCKING,
                ActionKind.ASSIGNMENT_NONBLOCKING,
            ) and _is_unsized_literal(step.label):
                smells.append(
                    Smell(
                        kind=SmellKind.UNSIZED_LITERAL,
                        severity=SmellSeverity.INFO,
                        message=f"Unsized literal in '{step.label}'",
                        location=SmellLocation(block_name=block_name, step_label=step.label),
                    )
                )

            # S10: Procedural continuous assignment
            if step.action_kind == ActionKind.PROCEDURAL_CONTINUOUS:
                smells.append(
                    Smell(
                        kind=SmellKind.PROCEDURAL_CONTINUOUS_USAGE,
                        severity=SmellSeverity.WARNING,
                        message=f"Procedural continuous assignment '{step.label}' — avoid in synthesizable RTL",
                        location=SmellLocation(block_name=block_name, step_label=step.label),
                    )
                )

            if var:
                assigned_vars.add(var)

        # ── If/else ──
        if isinstance(step, IfFlowStep):
            # S12: Deep nesting
            if nesting_depth >= 3:
                smells.append(
                    Smell(
                        kind=SmellKind.DEEP_NESTING,
                        severity=SmellSeverity.INFO,
                        message=f"Deep nesting (depth {nesting_depth + 1}) at if '{step.condition}'",
                        location=SmellLocation(block_name=block_name, step_label=step.condition),
                    )
                )

            # S3: Latch risk — incomplete if in combinational (with default check)
            if is_comb and len(step.else_steps) == 0:
                then_vars = _collect_assigned_vars(step.then_steps)
                uncovered = then_vars - assigned_vars
                if uncovered:
                    smells.append(
                        Smell(
                            kind=SmellKind.LATCH_RISK_INCOMPLETE_IF,
                            severity=SmellSeverity.WARNING,
                            message=f"Incomplete if (no else) in combinational block: '{step.condition}'",
                            location=SmellLocation(block_name=block_name, step_label=step.condition),
                        )
                    )

            defaults = frozenset(assigned_vars)
            _walk_steps(step.then_steps, block_name, is_comb, is_seq, smells, nb_targets, nb_rhs_text, defaults, nesting_depth + 1)
            _walk_steps(step.else_steps, block_name, is_comb, is_seq, smells, nb_targets, nb_rhs_text, defaults, nesting_depth + 1)

        # ── Switch/case ──
        if isinstance(step, SwitchFlowStep):
            # S12: Deep nesting
            if nesting_depth >= 3:
                smells.append(
                    Smell(
                        kind=SmellKind.DEEP_NESTING,
                        severity=SmellSeverity.INFO,
                        message=f"Deep nesting (depth {nesting_depth + 1}) at case '{step.expression}'",
                        location=SmellLocation(block_name=block_name, step_label=step.expression),
                    )
                )

            # S4: Case missing default
            has_default = any(c.label.strip() == "default" for c in step.cases)
            if not has_default:
                context = " — will infer latch" if is_comb else ""
                smells.append(
                    Smell(
                        kind=SmellKind.CASE_MISSING_DEFAULT,
                        severity=SmellSeverity.WARNING,
                        message=f"case '{step.expression}' has no default branch{context}",
                        location=SmellLocation(block_name=block_name, step_label=step.expression),
                    )
                )

            # S5: casex usage
            if step.case_keyword == "casex":
                smells.append(
                    Smell(
                        kind=SmellKind.CASEX_USAGE,
                        severity=SmellSeverity.INFO,
                        message=f"casex used for '{step.expression}' — prefer casez or explicit checks",
                        location=SmellLocation(block_name=block_name, step_label=step.expression),
                    )
                )

            # S11: Empty case branch
            for case in step.cases:
                if not case.steps:
                    smells.append(
                        Smell(
                            kind=SmellKind.EMPTY_CASE_BRANCH,
                            severity=SmellSeverity.INFO,
                            message=f"Empty case branch '{case.label}' in '{step.expression}'",
                            location=SmellLocation(block_name=block_name, step_label=case.label),
                        )
                    )

            # S13: Large case
            if len(step.cases) > 16:
                smells.append(
                    Smell(
                        kind=SmellKind.LARGE_CASE,
                        severity=SmellSeverity.INFO,
                        message=f"Large case '{step.expression}' with {len(step.cases)} branches",
                        location=SmellLocation(block_name=block_name, step_label=step.expression),
                    )
                )

            # S16: Duplicate case labels
            seen_labels: dict[str, int] = {}
            for case in step.cases:
                label = case.label.strip()
                if label != "default":
                    seen_labels[label] = seen_labels.get(label, 0) + 1
            for label, count in seen_labels.items():
                if count > 1:
                    smells.append(
                        Smell(
                            kind=SmellKind.DUPLICATE_CASE_LABEL,
                            severity=SmellSeverity.ERROR,
                            message=f"Duplicate case label '{label}' appears {count} times in '{step.expression}'",
                            location=SmellLocation(block_name=block_name, step_label=label),
                        )
                    )

            defaults = frozenset(assigned_vars)
            for case in step.cases:
                _walk_steps(case.steps, block_name, is_comb, is_seq, smells, nb_targets, nb_rhs_text, defaults, nesting_depth + 1)

        # ── Delay ──
        if isinstance(step, DelayFlowStep):
            # S9: Delay in synthesizable block
            if is_seq:
                smells.append(
                    Smell(
                        kind=SmellKind.DELAY_IN_SYNTHESIZABLE,
                        severity=SmellSeverity.WARNING,
                        message=f"#delay in sequential block — synthesis will ignore",
                        location=SmellLocation(block_name=block_name, step_label=f"#{step.delay}"),
                    )
                )
            if step.body_steps:
                _walk_steps(step.body_steps, block_name, is_comb, is_seq, smells, nb_targets, nb_rhs_text, frozenset(assigned_vars), nesting_depth + 1)

        # ── Forever ──
        if isinstance(step, ForeverFlowStep):
            # S17: Forever without disable
            if not _has_disable_in_tree(step.body_steps):
                smells.append(
                    Smell(
                        kind=SmellKind.FOREVER_WITHOUT_DISABLE,
                        severity=SmellSeverity.WARNING,
                        message="forever loop without disable — no escape path",
                        location=SmellLocation(block_name=block_name, step_label="forever"),
                    )
                )
            _walk_steps(step.body_steps, block_name, is_comb, is_seq, smells, nb_targets, nb_rhs_text, frozenset(assigned_vars), nesting_depth + 1)

        # ── Other compound steps (for, while, repeat, fork, event, wait) ──
        defaults = frozenset(assigned_vars)
        if hasattr(step, "body_steps") and not isinstance(step, (IfFlowStep, SwitchFlowStep, DelayFlowStep, ForeverFlowStep)):
            _walk_steps(step.body_steps, block_name, is_comb, is_seq, smells, nb_targets, nb_rhs_text, defaults, nesting_depth + 1)
        if hasattr(step, "then_steps") and not isinstance(step, IfFlowStep):
            _walk_steps(getattr(step, "then_steps"), block_name, is_comb, is_seq, smells, nb_targets, nb_rhs_text, defaults, nesting_depth)
        if hasattr(step, "else_steps") and not isinstance(step, IfFlowStep):
            _walk_steps(getattr(step, "else_steps"), block_name, is_comb, is_seq, smells, nb_targets, nb_rhs_text, defaults, nesting_depth)


# ── Helpers ──


def _extract_lhs_var(label: str) -> str | None:
    """Extract the variable name from the LHS of an assignment like 'count = count + 1'."""
    for sep in ("<=", "="):
        if sep in label:
            lhs = label.split(sep, 1)[0].strip()
            if "[" in lhs:
                lhs = lhs[: lhs.index("[")].strip()
            return lhs if lhs and lhs[0].isalpha() else None
    return None


def _collect_assignment_info(
    steps: tuple[ControlFlowStep, ...],
    blocking_vars: dict[str, list[str]],
    nb_vars: dict[str, list[str]],
    nb_rhs_text: list[str],
) -> None:
    """Collect per-variable assignment info across the step tree."""
    for step in steps:
        if isinstance(step, ActionFlowStep):
            var = _extract_lhs_var(step.label)
            if step.action_kind == ActionKind.ASSIGNMENT_BLOCKING:
                if var:
                    blocking_vars.setdefault(var, []).append(step.label)
            elif step.action_kind == ActionKind.ASSIGNMENT_NONBLOCKING:
                if var:
                    nb_vars.setdefault(var, []).append(step.label)
                nb_rhs_text.append(step.label)
        if isinstance(step, IfFlowStep):
            _collect_assignment_info(step.then_steps, blocking_vars, nb_vars, nb_rhs_text)
            _collect_assignment_info(step.else_steps, blocking_vars, nb_vars, nb_rhs_text)
        if isinstance(step, SwitchFlowStep):
            for case in step.cases:
                _collect_assignment_info(case.steps, blocking_vars, nb_vars, nb_rhs_text)
        if hasattr(step, "body_steps"):
            _collect_assignment_info(step.body_steps, blocking_vars, nb_vars, nb_rhs_text)


def _collect_assigned_vars(steps: tuple[ControlFlowStep, ...]) -> set[str]:
    """Collect all LHS variable names assigned anywhere in a step subtree."""
    result: set[str] = set()
    for step in steps:
        if isinstance(step, ActionFlowStep):
            var = _extract_lhs_var(step.label)
            if var:
                result.add(var)
        if isinstance(step, IfFlowStep):
            result |= _collect_assigned_vars(step.then_steps)
            result |= _collect_assigned_vars(step.else_steps)
        if isinstance(step, SwitchFlowStep):
            for case in step.cases:
                result |= _collect_assigned_vars(case.steps)
        if hasattr(step, "body_steps"):
            result |= _collect_assigned_vars(step.body_steps)
    return result


def _extract_identifiers(text: str) -> set[str]:
    """Extract Verilog signal identifiers from text, excluding keywords."""
    cleaned = re.sub(r"\d+'[bBhHdDoO][0-9a-fA-F_xXzZ?]+", "", text)
    ids = set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", cleaned))
    return ids - _VERILOG_KEYWORDS


def _extract_read_signals(label: str) -> set[str]:
    """Extract signal names from the RHS of an assignment."""
    for sep in ("<=", "="):
        if sep in label:
            rhs = label.split(sep, 1)[1].strip()
            return _extract_identifiers(rhs)
    return _extract_identifiers(label)


def _extract_body_signals(steps: tuple[ControlFlowStep, ...]) -> set[str]:
    """Extract all signal names read in the body of a block."""
    signals: set[str] = set()
    for step in steps:
        if isinstance(step, ActionFlowStep):
            signals |= _extract_read_signals(step.label)
        if isinstance(step, IfFlowStep):
            signals |= _extract_identifiers(step.condition)
            signals |= _extract_body_signals(step.then_steps)
            signals |= _extract_body_signals(step.else_steps)
        if isinstance(step, SwitchFlowStep):
            signals |= _extract_identifiers(step.expression)
            for case in step.cases:
                signals |= _extract_identifiers(case.label)
                signals |= _extract_body_signals(case.steps)
        if hasattr(step, "body_steps") and not isinstance(step, (IfFlowStep, SwitchFlowStep)):
            signals |= _extract_body_signals(step.body_steps)
        if hasattr(step, "condition") and not isinstance(step, IfFlowStep):
            cond = getattr(step, "condition", "")
            if isinstance(cond, str):
                signals |= _extract_identifiers(cond)
        if hasattr(step, "event"):
            ev = getattr(step, "event", "")
            if isinstance(ev, str):
                signals |= _extract_identifiers(ev)
    return signals


def _parse_sensitivity_signals(sensitivity: str) -> set[str]:
    """Extract signal names from a sensitivity list like '(posedge clk or negedge rst)'."""
    s = sensitivity.strip().lstrip("(").rstrip(")")
    s = re.sub(r"\b(posedge|negedge)\b", "", s, flags=re.IGNORECASE)
    parts = re.split(r"\bor\b", s, flags=re.IGNORECASE)
    signals: set[str] = set()
    for part in parts:
        name = part.strip()
        if name and name != "*":
            signals.add(name)
    return signals


def _has_reset_condition(steps: tuple[ControlFlowStep, ...]) -> bool:
    """Check if any if condition in the tree references a reset signal."""
    for step in steps:
        if isinstance(step, IfFlowStep):
            if re.search(r"\b(rst|reset|arst|async_rst|rst_n|reset_n)\b", step.condition, re.IGNORECASE):
                return True
            if _has_reset_condition(step.then_steps) or _has_reset_condition(step.else_steps):
                return True
        if isinstance(step, SwitchFlowStep):
            for case in step.cases:
                if _has_reset_condition(case.steps):
                    return True
        if hasattr(step, "body_steps"):
            if _has_reset_condition(step.body_steps):
                return True
    return False


def _has_disable_in_tree(steps: tuple[ControlFlowStep, ...]) -> bool:
    """Check if a disable statement exists anywhere in the step subtree."""
    for step in steps:
        if isinstance(step, DisableFlowStep):
            return True
        if isinstance(step, IfFlowStep):
            if _has_disable_in_tree(step.then_steps) or _has_disable_in_tree(step.else_steps):
                return True
        if isinstance(step, SwitchFlowStep):
            for case in step.cases:
                if _has_disable_in_tree(case.steps):
                    return True
        if hasattr(step, "body_steps"):
            if _has_disable_in_tree(step.body_steps):
                return True
    return False


def _is_unsized_literal(label: str) -> bool:
    """Check if action assigns a bare unsized decimal literal as the entire RHS."""
    for sep in ("<=", "="):
        if sep in label:
            rhs = label.split(sep, 1)[1].strip()
            if re.match(r"^-?\d+$", rhs):
                return True
    return False


def _is_combinational(sensitivity: str | None) -> bool:
    if sensitivity is None:
        return False
    s = sensitivity.strip().lstrip("(").rstrip(")")
    return s == "*"


def _is_sequential(sensitivity: str | None) -> bool:
    if sensitivity is None:
        return False
    return "posedge" in sensitivity.lower() or "negedge" in sensitivity.lower()


def _is_explicit_sensitivity(sensitivity: str | None) -> bool:
    """True if sensitivity is an explicit non-wildcard, non-edge-triggered list."""
    if sensitivity is None:
        return False
    s = sensitivity.strip()
    if s == "*":
        return False
    if "posedge" in s.lower() or "negedge" in s.lower():
        return False
    return True
