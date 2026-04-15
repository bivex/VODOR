"""Render structured control flow as behavioral Verilog."""

from __future__ import annotations

from html import escape

import re

from vodor.domain.control_flow import (
    ActionFlowStep,
    ControlFlowDiagram,
    DeferFlowStep,
    DelayFlowStep,
    DisableFlowStep,
    DoCatchFlowStep,
    EventWaitFlowStep,
    ForkJoinFlowStep,
    ForInFlowStep,
    ForeverFlowStep,
    GuardFlowStep,
    IfFlowStep,
    RepeatWhileFlowStep,
    StructDeclarationFlowStep,
    StructFieldAccessFlowStep,
    SwitchCaseFlow,
    SwitchFlowStep,
    WaitConditionFlowStep,
    WhileFlowStep,
)
from vodor.domain.ports import VerilogRenderer

_INDENT = "    "


class VerilogDiagramRenderer(VerilogRenderer):
    def render(self, diagram: ControlFlowDiagram) -> str:
        if not diagram.functions:
            return f"// No functions found in {diagram.source_location}\n"

        header = (
            f"// ============================================================\n"
            f"// Behavioral Verilog generated from source code\n"
            f"// Source: {diagram.source_location}\n"
            f"// ============================================================\n"
            f"`timescale 1ns / 1ps\n"
        )
        modules = "\n".join(
            self._render_function(function) for function in diagram.functions
        )
        return header + modules

    def _render_function(self, function) -> str:
        params = _parse_parameters(function.signature)
        module_name = _sanitize_identifier(function.qualified_name)

        port_lines = []
        for param in params:
            port_lines.append(f"{_INDENT}input  [31:0] {param}")
        port_lines.append(f"{_INDENT}output reg [31:0] result")

        ports = ",\n".join(port_lines)

        body = self._render_sequence(function.steps, depth=2)

        comment = f"// Function: {function.qualified_name}"
        if function.container:
            comment += f"\n{_INDENT}// Container: {function.container}"

        return (
            f"\n{comment}\n"
            f"module {module_name} (\n"
            f"{ports}\n"
            f");\n"
            f"{_INDENT}initial begin\n"
            f"{body}"
            f"{_INDENT}end\n"
            f"endmodule\n"
        )

    def _render_sequence(
        self, steps: tuple[ControlFlowStep, ...], *, depth: int
    ) -> str:
        if not steps:
            indent = _INDENT * depth
            return f"{indent}// (empty)\n"
        return "".join(self._render_step(step, depth=depth) for step in steps)

    def _render_step(self, step: ControlFlowStep, *, depth: int) -> str:
        if isinstance(step, ActionFlowStep):
            return self._render_action(step, depth=depth)
        if isinstance(step, StructDeclarationFlowStep):
            return self._render_struct(step, depth=depth)
        if isinstance(step, StructFieldAccessFlowStep):
            return self._render_struct_access(step, depth=depth)
        if isinstance(step, IfFlowStep):
            return self._render_if(step, depth=depth)
        if isinstance(step, GuardFlowStep):
            return self._render_guard(step, depth=depth)
        if isinstance(step, WhileFlowStep):
            return self._render_while(step, depth=depth)
        if isinstance(step, ForInFlowStep):
            return self._render_for_in(step, depth=depth)
        if isinstance(step, RepeatWhileFlowStep):
            return self._render_repeat_while(step, depth=depth)
        if isinstance(step, SwitchFlowStep):
            return self._render_switch(step, depth=depth)
        if isinstance(step, DoCatchFlowStep):
            return self._render_do_catch(step, depth=depth)
        if isinstance(step, DeferFlowStep):
            return self._render_defer(step, depth=depth)
        if isinstance(step, ForeverFlowStep):
            return self._render_forever(step, depth=depth)
        if isinstance(step, DisableFlowStep):
            return self._render_disable(step, depth=depth)
        if isinstance(step, ForkJoinFlowStep):
            return self._render_fork_join(step, depth=depth)
        if isinstance(step, DelayFlowStep):
            return self._render_delay(step, depth=depth)
        if isinstance(step, EventWaitFlowStep):
            return self._render_event_wait(step, depth=depth)
        if isinstance(step, WaitConditionFlowStep):
            return self._render_wait_condition(step, depth=depth)
        raise TypeError(f"unsupported step type: {type(step)!r}")

    def _render_struct(self, step: StructDeclarationFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        fields_str = "".join(
            f"{_INDENT * (depth + 1)}{escape(field_name)}: {escape(field_type)};\n"
            for field_name, field_type in step.fields
        )
        return (
            f"{indent}// Struct: {escape(step.name)}\n"
            f"{indent}// Fields:\n"
            f"{indent}{fields_str}"
        )

    def _render_struct_access(self, step: StructFieldAccessFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        direction = "write" if step.is_write else "read"
        return (
            f"{indent}// {direction} {escape(step.struct_name)}.{escape(step.field_name)}\n"
            f"{indent}{escape(step.struct_name)}.{escape(step.field_name)};\n"
        )

    def _render_action(self, step: ActionFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        return f"{indent}{step.label};\n"

    def _render_if(self, step: IfFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        condition = _sanitize_verilog_expression(step.condition)
        then_body = self._render_sequence(step.then_steps, depth=depth + 1)

        if step.else_steps:
            else_body = self._render_sequence(step.else_steps, depth=depth + 1)
            return (
                f"{indent}if ({condition}) begin\n"
                f"{then_body}"
                f"{indent}end else begin\n"
                f"{else_body}"
                f"{indent}end\n"
            )

        return (
            f"{indent}if ({condition}) begin\n"
            f"{then_body}"
            f"{indent}end\n"
        )

    def _render_guard(self, step: GuardFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        condition = _sanitize_verilog_expression(step.condition)
        else_body = self._render_sequence(step.else_steps, depth=depth + 1)
        return (
            f"{indent}// guard: {step.condition}\n"
            f"{indent}if (!({condition})) begin\n"
            f"{else_body}"
            f"{indent}end\n"
        )

    def _render_while(self, step: WhileFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        condition = _sanitize_verilog_expression(step.condition)
        body = self._render_sequence(step.body_steps, depth=depth + 1)
        return (
            f"{indent}while ({condition}) begin\n"
            f"{body}"
            f"{indent}end\n"
        )

    def _render_for_in(self, step: ForInFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        iter_var, collection = _parse_for_in_header(step.header)
        body = self._render_sequence(step.body_steps, depth=depth + 2)
        return (
            f"{indent}// for {step.header}\n"
            f"{indent}for ({iter_var} = 0; {iter_var} < {collection}; {iter_var} = {iter_var} + 1) begin\n"
            f"{body}"
            f"{indent}end\n"
        )

    def _render_repeat_while(self, step: RepeatWhileFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        condition = _sanitize_verilog_expression(step.condition)
        body = self._render_sequence(step.body_steps, depth=depth + 1)
        return (
            f"{indent}begin\n"
            f"{body}"
            f"{indent}    while ({condition}) begin\n"
            f"{body}"
            f"{indent}    end\n"
            f"{indent}end\n"
        )

    def _render_switch(self, step: SwitchFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        expression = _sanitize_verilog_expression(step.expression)

        if not step.cases:
            return f"{indent}// switch {step.expression} (no cases)\n"

        cases = "".join(
            self._render_case(case, depth=depth + 1) for case in step.cases
        )
        return (
            f"{indent}case ({expression})\n"
            f"{cases}"
            f"{indent}endcase\n"
        )

    def _render_case(self, case: SwitchCaseFlow, *, depth: int) -> str:
        indent = _INDENT * depth
        label = _normalize_case_label(case.label)
        body = self._render_sequence(case.steps, depth=depth + 1)
        return (
            f"{indent}{label}: begin\n"
            f"{body}"
            f"{indent}end\n"
        )

    def _render_do_catch(self, step: DoCatchFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        body = self._render_sequence(step.body_steps, depth=depth + 1)

        catch_blocks = ""
        for catch in step.catches:
            catch_body = self._render_sequence(catch.steps, depth=depth + 1)
            catch_blocks += (
                f"{indent}// catch {catch.pattern}\n"
                f"{indent}begin\n"
                f"{catch_body}"
                f"{indent}end\n"
            )

        return (
            f"{indent}// do-catch\n"
            f"{indent}begin\n"
            f"{body}"
            f"{catch_blocks}"
            f"{indent}end\n"
        )

    def _render_defer(self, step: DeferFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        body = self._render_sequence(step.body_steps, depth=depth + 1)
        return (
            f"{indent}// defer\n"
            f"{indent}begin\n"
            f"{body}"
            f"{indent}end\n"
        )

    def _render_forever(self, step: ForeverFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        body = self._render_sequence(step.body_steps, depth=depth + 1)
        return (
            f"{indent}forever begin\n"
            f"{body}"
            f"{indent}end\n"
        )

    def _render_disable(self, step: DisableFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        return f"{indent}disable {step.target};\n"

    def _render_fork_join(self, step: ForkJoinFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        body = self._render_sequence(step.body_steps, depth=depth + 1)
        return (
            f"{indent}fork\n"
            f"{body}"
            f"{indent}{step.join_type}\n"
        )

    def _render_delay(self, step: DelayFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        body = self._render_sequence(step.body_steps, depth=depth + 1)
        return (
            f"{indent}#{step.delay} begin\n"
            f"{body}"
            f"{indent}end\n"
        )

    def _render_event_wait(self, step: EventWaitFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        body = self._render_sequence(step.body_steps, depth=depth + 1)
        return (
            f"{indent}@({step.event}) begin\n"
            f"{body}"
            f"{indent}end\n"
        )

    def _render_wait_condition(self, step: WaitConditionFlowStep, *, depth: int) -> str:
        indent = _INDENT * depth
        body = self._render_sequence(step.body_steps, depth=depth + 1)
        return (
            f"{indent}wait ({step.condition}) begin\n"
            f"{body}"
            f"{indent}end\n"
        )


def _sanitize_identifier(name: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    if result and result[0].isdigit():
        result = f"_{result}"
    return result or "anonymous"


def _parse_parameters(signature: str) -> list[str]:
    match = re.search(r"\(([^)]*)\)", signature)
    if not match:
        return ["in0"]

    params_text = match.group(1).strip()
    if not params_text:
        return ["in0"]

    params: list[str] = []
    for index, segment in enumerate(params_text.split(",")):
        segment = segment.strip()
        if not segment:
            continue

        name = _extract_parameter_name(segment)
        if name:
            params.append(_sanitize_identifier(name))
        else:
            params.append(f"in{index}")

    return params if params else ["in0"]


def _sanitize_verilog_expression(expression: str) -> str:
    padded = re.sub(r"\s*(==|!=|>=|<=|&&|\|\||>|<)\s*", r" \1 ", expression)
    return re.sub(r"\s+", " ", padded).strip()


def _extract_parameter_name(segment: str) -> str | None:
    lhs = segment.split(":", maxsplit=1)[0].strip()
    if not lhs:
        return None

    tokens = [token for token in lhs.split() if token]
    if not tokens:
        return None

    if len(tokens) == 1:
        token = tokens[0]
        return token.lstrip("_") or None

    # Signatures can contain placeholders like "_ value: Int".
    local_name = tokens[-1]
    return local_name.lstrip("_") or None


def _parse_for_in_header(header: str) -> tuple[str, str]:
    match = re.match(r"(\w+)\s+in\s+(.+)", header)
    if match:
        return _sanitize_identifier(match.group(1)), _sanitize_identifier(match.group(2))
    return "i", "collection"


def _normalize_case_label(label: str) -> str:
    compact = label.removesuffix(":").strip()
    if compact.startswith("default"):
        return "default"
    if compact.startswith("case "):
        value = compact[len("case "):].strip()
        if re.match(r"^-?\d+$", value):
            return value
        return f"'{value}"
    return compact
