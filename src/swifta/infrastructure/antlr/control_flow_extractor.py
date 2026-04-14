"""Extract structured control flow from Verilog source."""

from __future__ import annotations

import re
from dataclasses import dataclass

from swifta.domain.control_flow import (
    ActionFlowStep,
    ControlFlowDiagram,
    ControlFlowStep,
    ForInFlowStep,
    FunctionControlFlow,
    IfFlowStep,
    RepeatWhileFlowStep,
    SwitchCaseFlow,
    SwitchFlowStep,
    WhileFlowStep,
)
from swifta.domain.model import SourceUnit
from swifta.domain.ports import VerilogControlFlowExtractor


@dataclass(frozen=True, slots=True)
class _BlockSlice:
    name: str
    body: str


class AntlrVerilogControlFlowExtractor(VerilogControlFlowExtractor):
    def extract(self, source_unit: SourceUnit) -> ControlFlowDiagram:
        blocks = _scan_procedural_blocks(source_unit.content)
        functions = tuple(
            FunctionControlFlow(
                name=block.name,
                signature=f"always {block.name}",
                container=None,
                steps=_extract_steps(block.body),
            )
            for block in blocks
        )
        return ControlFlowDiagram(
            source_location=source_unit.location,
            functions=functions,
        )


def _scan_procedural_blocks(source_text: str) -> tuple[_BlockSlice, ...]:
    pattern = re.compile(r"\b(always|initial)\b", re.IGNORECASE)
    blocks: list[_BlockSlice] = []
    index = 0
    counter = 1
    while True:
        match = pattern.search(source_text, index)
        if not match:
            break
        start = match.start()
        begin_index = source_text.find("begin", match.end())
        if begin_index == -1:
            index = match.end()
            continue
        end_index = _find_matching_end(source_text, begin_index)
        if end_index == -1:
            index = match.end()
            continue
        body = source_text[begin_index + len("begin") : end_index].strip()
        kind = match.group(1).lower()
        blocks.append(_BlockSlice(name=f"{kind}_{counter}", body=body))
        counter += 1
        index = end_index + len("end")
    return tuple(blocks)


def _find_matching_end(text: str, begin_index: int) -> int:
    begin_pattern = re.compile(r"\bbegin\b", re.IGNORECASE)
    end_pattern = re.compile(r"\bend\b", re.IGNORECASE)
    depth = 1
    index = begin_index + len("begin")
    while index < len(text):
        begin_match = begin_pattern.search(text, index)
        end_match = end_pattern.search(text, index)
        if end_match is None:
            return -1
        if begin_match is not None and begin_match.start() < end_match.start():
            depth += 1
            index = begin_match.end()
            continue
        depth -= 1
        if depth == 0:
            return end_match.start()
        index = end_match.end()
    return -1


def _extract_steps(body: str) -> tuple[ControlFlowStep, ...]:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    steps, _ = _parse_steps(lines, 0, stop_prefixes=set())
    return tuple(steps)


def _parse_steps(
    lines: list[str],
    start: int,
    *,
    stop_prefixes: set[str],
) -> tuple[list[ControlFlowStep], int]:
    steps: list[ControlFlowStep] = []
    index = start

    while index < len(lines):
        line = lines[index]
        lower = line.lower()
        if any(lower.startswith(prefix) for prefix in stop_prefixes):
            break
        if "endcase" in stop_prefixes and _is_case_label_line(line):
            break

        if lower == "begin":
            nested, index = _parse_steps(lines, index + 1, stop_prefixes={"end"})
            steps.extend(nested)
            if index < len(lines) and lines[index].lower().startswith("end"):
                index += 1
            continue

        if lower.startswith("if "):
            step, index = _parse_if(lines, index)
            steps.append(step)
            continue

        if lower.startswith("while "):
            step, index = _parse_while(lines, index)
            steps.append(step)
            continue

        if lower.startswith("for "):
            step, index = _parse_for(lines, index)
            steps.append(step)
            continue

        if lower.startswith("repeat "):
            step, index = _parse_repeat(lines, index)
            steps.append(step)
            continue

        if lower.startswith("case "):
            step, index = _parse_case(lines, index)
            steps.append(step)
            continue

        if lower.startswith(("end", "endcase", "else")):
            break

        steps.append(ActionFlowStep(_clean_line(line)))
        index += 1

    return steps, index


def _parse_if(lines: list[str], index: int) -> tuple[IfFlowStep, int]:
    line = lines[index]
    condition = _extract_parenthesized(line[2:].strip()) or "condition"
    index += 1
    then_steps, index = _parse_branch_body(lines, index)

    else_steps: tuple[ControlFlowStep, ...] = ()
    if index < len(lines) and lines[index].lower().startswith("else"):
        else_line = lines[index]
        if else_line.lower().startswith("else if "):
            nested, index = _parse_if_after_header(
                "if " + else_line[8:].strip(),
                lines,
                index + 1,
            )
            else_steps = (nested,)
        else:
            index += 1
            parsed_else, index = _parse_branch_body(lines, index)
            else_steps = tuple(parsed_else)

    return (
        IfFlowStep(
            condition=condition,
            then_steps=tuple(then_steps),
            else_steps=else_steps,
        ),
        index,
    )


def _parse_if_after_header(
    header_line: str,
    lines: list[str],
    index: int,
) -> tuple[IfFlowStep, int]:
    condition = _extract_parenthesized(header_line[2:].strip()) or "condition"
    then_steps, index = _parse_branch_body(lines, index)

    else_steps: tuple[ControlFlowStep, ...] = ()
    if index < len(lines) and lines[index].lower().startswith("else"):
        else_line = lines[index]
        if else_line.lower().startswith("else if "):
            nested, index = _parse_if_after_header(
                "if " + else_line[8:].strip(),
                lines,
                index + 1,
            )
            else_steps = (nested,)
        else:
            index += 1
            parsed_else, index = _parse_branch_body(lines, index)
            else_steps = tuple(parsed_else)

    return (
        IfFlowStep(
            condition=condition,
            then_steps=tuple(then_steps),
            else_steps=else_steps,
        ),
        index,
    )


def _parse_while(lines: list[str], index: int) -> tuple[WhileFlowStep, int]:
    line = lines[index]
    condition = _extract_parenthesized(line[5:].strip()) or "condition"
    index += 1
    body_steps, index = _parse_branch_body(lines, index)
    return WhileFlowStep(condition=condition, body_steps=tuple(body_steps)), index


def _parse_for(lines: list[str], index: int) -> tuple[ForInFlowStep, int]:
    line = lines[index]
    header = _extract_parenthesized(line[3:].strip()) or "i in range"
    index += 1
    body_steps, index = _parse_branch_body(lines, index)
    return ForInFlowStep(header=header, body_steps=tuple(body_steps)), index


def _parse_repeat(lines: list[str], index: int) -> tuple[RepeatWhileFlowStep, int]:
    line = lines[index]
    condition = _extract_parenthesized(line[6:].strip()) or "condition"
    index += 1
    body_steps, index = _parse_branch_body(lines, index)
    return RepeatWhileFlowStep(condition=condition, body_steps=tuple(body_steps)), index


def _parse_case(lines: list[str], index: int) -> tuple[SwitchFlowStep, int]:
    line = lines[index]
    expression = _extract_parenthesized(line[4:].strip()) or "expression"
    index += 1
    cases: list[SwitchCaseFlow] = []

    while index < len(lines):
        current = lines[index]
        lower = current.lower()
        if lower.startswith("endcase"):
            index += 1
            break

        if _is_case_label_line(current):
            label = current.split(":", maxsplit=1)[0].strip()
            index += 1
            case_steps: list[ControlFlowStep] = []
            while index < len(lines):
                next_line = lines[index]
                if next_line.lower().startswith("endcase") or _is_case_label_line(next_line):
                    break
                parsed, index = _parse_steps(lines, index, stop_prefixes={"endcase"})
                case_steps.extend(parsed)
            cases.append(SwitchCaseFlow(label=label, steps=tuple(case_steps)))
            continue

        index += 1

    return SwitchFlowStep(expression=expression, cases=tuple(cases)), index


def _parse_branch_body(lines: list[str], index: int) -> tuple[list[ControlFlowStep], int]:
    if index >= len(lines):
        return [], index

    line = lines[index].lower()
    if line == "begin":
        body, index = _parse_steps(lines, index + 1, stop_prefixes={"end"})
        if index < len(lines) and lines[index].lower().startswith("end"):
            index += 1
        return body, index

    step = _single_line_step(lines[index])
    return [step], index + 1


def _single_line_step(line: str) -> ControlFlowStep:
    lower = line.lower()
    if lower.startswith("if "):
        condition = _extract_parenthesized(line[2:].strip()) or "condition"
        return IfFlowStep(condition=condition, then_steps=(), else_steps=())
    if lower.startswith("while "):
        condition = _extract_parenthesized(line[5:].strip()) or "condition"
        return WhileFlowStep(condition=condition, body_steps=())
    if lower.startswith("for "):
        header = _extract_parenthesized(line[3:].strip()) or "i in range"
        return ForInFlowStep(header=header, body_steps=())
    if lower.startswith("repeat "):
        condition = _extract_parenthesized(line[6:].strip()) or "condition"
        return RepeatWhileFlowStep(condition=condition, body_steps=())
    if lower.startswith("case "):
        expr = _extract_parenthesized(line[4:].strip()) or "expression"
        return SwitchFlowStep(expression=expr, cases=())
    return ActionFlowStep(_clean_line(line))


def _clean_line(line: str) -> str:
    return line.strip().removesuffix(";")


def _extract_parenthesized(text: str) -> str:
    open_index = text.find("(")
    close_index = text.rfind(")")
    if open_index == -1 or close_index == -1 or close_index <= open_index:
        return text.strip().removesuffix(";")
    return text[open_index + 1 : close_index].strip()


def _is_case_label_line(line: str) -> bool:
    stripped = line.strip()
    if stripped.lower().startswith("default:"):
        return True
    return ":" in stripped and not stripped.lower().startswith(("if ", "for ", "while ", "repeat ", "case "))


# Backward-compatible alias for downstream imports during migration.
AntlrSwiftControlFlowExtractor = AntlrVerilogControlFlowExtractor
