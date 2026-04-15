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
    _walk_steps(
        function.steps,
        function.name,
        is_combinational,
        is_sequential,
        smells,
    )
    return smells


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


def _walk_steps(
    steps: tuple[ControlFlowStep, ...],
    block_name: str,
    is_combinational: bool,
    is_sequential: bool,
    smells: list[Smell],
) -> None:
    for step in steps:
        if isinstance(step, ActionFlowStep):
            if is_sequential and step.action_kind == ActionKind.ASSIGNMENT_BLOCKING:
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

        if isinstance(step, IfFlowStep):
            if is_combinational and len(step.else_steps) == 0:
                smells.append(
                    Smell(
                        kind=SmellKind.LATCH_RISK_INCOMPLETE_IF,
                        severity=SmellSeverity.WARNING,
                        message=f"Incomplete if (no else) in combinational block: '{step.condition}'",
                        location=SmellLocation(block_name=block_name, step_label=step.condition),
                    )
                )
            _walk_steps(step.then_steps, block_name, is_combinational, is_sequential, smells)
            _walk_steps(step.else_steps, block_name, is_combinational, is_sequential, smells)

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
            for case in step.cases:
                _walk_steps(case.steps, block_name, is_combinational, is_sequential, smells)

        # Recurse into other compound steps
        if hasattr(step, "body_steps"):
            _walk_steps(step.body_steps, block_name, is_combinational, is_sequential, smells)
        if hasattr(step, "then_steps") and not isinstance(step, IfFlowStep):
            _walk_steps(getattr(step, "then_steps"), block_name, is_combinational, is_sequential, smells)
        if hasattr(step, "else_steps") and not isinstance(step, IfFlowStep):
            _walk_steps(getattr(step, "else_steps"), block_name, is_combinational, is_sequential, smells)
