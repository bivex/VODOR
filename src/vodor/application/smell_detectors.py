"""Verilog code smell detectors operating on the extracted control flow model."""

from __future__ import annotations

from vodor.domain.control_flow import (
    ActionFlowStep,
    ActionKind,
    ControlFlowStep,
    FunctionControlFlow,
    IfFlowStep,
    Smell,
    SmellKind,
    SmellLocation,
    SmellSeverity,
    SwitchFlowStep,
)


def detect_smells(function: FunctionControlFlow) -> list[Smell]:
    """Run all Tier 1 smell detectors on a single procedural block."""
    smells: list[Smell] = []
    is_combinational = _is_combinational(function.sensitivity)
    is_sequential = _is_sequential(function.sensitivity)

    # First pass: collect nonblocking targets + RHS text for intermediate variable detection
    nb_targets: set[str] = set()
    nb_rhs_text: list[str] = []
    _collect_nonblocking_info(function.steps, nb_targets, nb_rhs_text)

    # Second pass: detect smells with context
    _walk_steps(
        function.steps,
        function.name,
        is_combinational,
        is_sequential,
        smells,
        nb_targets,
        nb_rhs_text,
        frozenset(),
    )
    return smells


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


def _collect_nonblocking_info(
    steps: tuple[ControlFlowStep, ...],
    targets: set[str],
    rhs_text: list[str],
) -> None:
    """Collect nonblocking assignment target names and full label text."""
    for step in steps:
        if isinstance(step, ActionFlowStep) and step.action_kind == ActionKind.ASSIGNMENT_NONBLOCKING:
            var = _extract_lhs_var(step.label)
            if var:
                targets.add(var)
            rhs_text.append(step.label)
        if isinstance(step, IfFlowStep):
            _collect_nonblocking_info(step.then_steps, targets, rhs_text)
            _collect_nonblocking_info(step.else_steps, targets, rhs_text)
        if isinstance(step, SwitchFlowStep):
            for case in step.cases:
                _collect_nonblocking_info(case.steps, targets, rhs_text)
        if hasattr(step, "body_steps"):
            _collect_nonblocking_info(step.body_steps, targets, rhs_text)


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


# ── Classification ──


def _is_combinational(sensitivity: str | None) -> bool:
    if sensitivity is None:
        return False
    s = sensitivity.strip().lstrip("(").rstrip(")")
    return s == "*"


def _is_sequential(sensitivity: str | None) -> bool:
    if sensitivity is None:
        return False
    s = sensitivity.lower()
    return "posedge" in s or "negedge" in s


# ── Walk ──


def _walk_steps(
    steps: tuple[ControlFlowStep, ...],
    block_name: str,
    is_combinational: bool,
    is_sequential: bool,
    smells: list[Smell],
    nb_targets: set[str],
    nb_rhs_text: list[str],
    parent_defaults: frozenset[str],
) -> None:
    assigned_vars = set(parent_defaults)

    for step in steps:
        if isinstance(step, ActionFlowStep):
            if is_sequential and step.action_kind == ActionKind.ASSIGNMENT_BLOCKING:
                var = _extract_lhs_var(step.label)
                # Intermediate variable: blocking-only, feeds into a nonblocking RHS
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
            if is_combinational and step.action_kind == ActionKind.ASSIGNMENT_NONBLOCKING:
                smells.append(
                    Smell(
                        kind=SmellKind.NONBLOCKING_IN_COMBINATIONAL,
                        severity=SmellSeverity.WARNING,
                        message=f"Nonblocking assignment '{step.label}' in combinational block",
                        location=SmellLocation(block_name=block_name, step_label=step.label),
                    )
                )
            var = _extract_lhs_var(step.label)
            if var:
                assigned_vars.add(var)

        if isinstance(step, IfFlowStep):
            if is_combinational and len(step.else_steps) == 0:
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
            _walk_steps(step.then_steps, block_name, is_combinational, is_sequential, smells, nb_targets, nb_rhs_text, defaults)
            _walk_steps(step.else_steps, block_name, is_combinational, is_sequential, smells, nb_targets, nb_rhs_text, defaults)

        if isinstance(step, SwitchFlowStep):
            has_default = any(c.label.strip() == "default" for c in step.cases)
            if not has_default:
                smells.append(
                    Smell(
                        kind=SmellKind.CASE_MISSING_DEFAULT,
                        severity=SmellSeverity.WARNING,
                        message=f"case '{step.expression}' has no default branch",
                        location=SmellLocation(block_name=block_name, step_label=step.expression),
                    )
                )
            if step.case_keyword == "casex":
                smells.append(
                    Smell(
                        kind=SmellKind.CASEX_USAGE,
                        severity=SmellSeverity.INFO,
                        message=f"casex used for '{step.expression}' — prefer casez or explicit checks",
                        location=SmellLocation(block_name=block_name, step_label=step.expression),
                    )
                )
            defaults = frozenset(assigned_vars)
            for case in step.cases:
                _walk_steps(case.steps, block_name, is_combinational, is_sequential, smells, nb_targets, nb_rhs_text, defaults)

        # Recurse into other compound steps
        defaults = frozenset(assigned_vars)
        if hasattr(step, "body_steps"):
            _walk_steps(step.body_steps, block_name, is_combinational, is_sequential, smells, nb_targets, nb_rhs_text, defaults)
        if hasattr(step, "then_steps") and not isinstance(step, IfFlowStep):
            _walk_steps(getattr(step, "then_steps"), block_name, is_combinational, is_sequential, smells, nb_targets, nb_rhs_text, defaults)
        if hasattr(step, "else_steps") and not isinstance(step, IfFlowStep):
            _walk_steps(getattr(step, "else_steps"), block_name, is_combinational, is_sequential, smells, nb_targets, nb_rhs_text, defaults)
