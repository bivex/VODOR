"""Extract structured control flow from Verilog source."""

from __future__ import annotations

import re
from dataclasses import dataclass

from swifta.domain.control_flow import (
    ActionFlowStep,
    ControlFlowDiagram,
    ControlFlowStep,
    DeferFlowStep,
    DelayFlowStep,
    DisableFlowStep,
    EventWaitFlowStep,
    ForkJoinFlowStep,
    ForInFlowStep,
    ForeverFlowStep,
    FunctionControlFlow,
    IfFlowStep,
    RepeatWhileFlowStep,
    SwitchCaseFlow,
    SwitchFlowStep,
    WaitConditionFlowStep,
    WhileFlowStep,
)
from swifta.domain.model import SourceUnit
from swifta.domain.ports import VerilogControlFlowExtractor


@dataclass(frozen=True, slots=True)
class _BlockSlice:
    name: str
    body: str
    kind: str = "always"
    sensitivity: str | None = None
    signature: str | None = None


class AntlrVerilogControlFlowExtractor(VerilogControlFlowExtractor):
    def extract(self, source_unit: SourceUnit) -> ControlFlowDiagram:
        blocks = _scan_procedural_blocks(source_unit.content)
        functions = tuple(
            FunctionControlFlow(
                name=block.name,
                signature=_build_signature(block),
                container=None,
                steps=_extract_steps(block.body),
                sensitivity=block.sensitivity,
            )
            for block in blocks
        )
        return ControlFlowDiagram(
            source_location=source_unit.location,
            functions=functions,
        )


def _scan_procedural_blocks(source_text: str) -> tuple[_BlockSlice, ...]:
    source_text = _strip_comments(source_text)
    blocks: list[_BlockSlice] = []

    # Scan always/initial blocks
    blocks.extend(_scan_always_initial(source_text))

    # Scan function/task blocks
    blocks.extend(_scan_function_task(source_text))

    # Preserve source order
    return tuple(blocks)


def _scan_always_initial(source_text: str) -> list[_BlockSlice]:
    pattern = re.compile(r"\b(always|initial)\b", re.IGNORECASE)
    blocks: list[_BlockSlice] = []
    index = 0
    counter = 1
    while True:
        match = pattern.search(source_text, index)
        if not match:
            break
        kind = match.group(1).lower()

        # Capture sensitivity list for always blocks: @(...) or @*
        sensitivity: str | None = None
        rest = source_text[match.end():]
        sens_match = re.match(r"\s*@\s*(\([^)]*\)|\*)", rest)
        if sens_match:
            sensitivity = sens_match.group(1).strip()
            after_sens = match.end() + sens_match.end()
        else:
            after_sens = match.end()

        begin_index = source_text.find("begin", after_sens)
        if begin_index == -1 or begin_index > _next_statement_boundary(source_text, after_sens):
            # Single-statement block: everything until next ';'
            semi = source_text.find(";", after_sens)
            if semi == -1:
                index = after_sens
                continue
            body = source_text[after_sens:semi].strip()
            if body:
                blocks.append(_BlockSlice(name=f"{kind}_{counter}", body=body, kind=kind, sensitivity=sensitivity))
                counter += 1
            index = semi + 1
            continue

        end_index = _find_matching_end(source_text, begin_index)
        if end_index == -1:
            index = after_sens
            continue
        body = source_text[begin_index + len("begin") : end_index].strip()
        blocks.append(_BlockSlice(name=f"{kind}_{counter}", body=body, kind=kind, sensitivity=sensitivity))
        counter += 1
        index = end_index + len("end")
    return blocks


def _scan_function_task(source_text: str) -> list[_BlockSlice]:
    pattern = re.compile(r"\b(function|task)\b", re.IGNORECASE)
    blocks: list[_BlockSlice] = []
    index = 0
    while True:
        match = pattern.search(source_text, index)
        if not match:
            break
        kind = match.group(1).lower()
        after_keyword = match.end()

        # Extract the rest of the header line (until ';')
        semi = source_text.find(";", after_keyword)
        if semi == -1:
            index = after_keyword
            continue
        header_line = source_text[after_keyword:semi].strip()

        # Extract function/task name — last identifier in the header
        name = _extract_last_identifier(header_line) or f"{kind}_anon"

        # Find endfunction / endtask
        end_keyword = f"end{kind}"
        end_pattern = re.compile(rf"\b{end_keyword}\b", re.IGNORECASE)
        end_match = end_pattern.search(source_text, semi + 1)
        if end_match is None:
            index = semi + 1
            continue

        body = source_text[semi + 1 : end_match.start()].strip()
        # Build signature from the full header
        signature = f"{kind} {header_line}"

        blocks.append(_BlockSlice(name=name, body=body, kind=kind, sensitivity=None, signature=signature))
        index = end_match.end()

    return blocks


def _extract_last_identifier(text: str) -> str | None:
    """Extract the last Verilog identifier from a header line."""
    # Match word characters, allowing brackets for return types like [7:0]
    tokens = re.findall(r"[a-zA-Z_]\w*", text)
    # Filter out Verilog keywords that commonly appear in headers
    keywords = {
        "input", "output", "inout", "reg", "wire", "integer",
        "signed", "unsigned", "begin", "end", "automatic",
    }
    for token in reversed(tokens):
        if token.lower() not in keywords:
            return token
    return tokens[-1] if tokens else None


def _next_statement_boundary(text: str, start: int) -> int:
    """Return index of the first ';' after start, or len(text) if none."""
    idx = text.find(";", start)
    return idx if idx != -1 else len(text)


def _build_signature(block: _BlockSlice) -> str:
    if block.signature:
        return block.signature
    parts = [block.kind]
    if block.sensitivity:
        parts.append(f"@({block.sensitivity})")
    return " ".join(parts)


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
    cleaned = _strip_comments(body)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    # Skip named begin labels like ": processing_block" at the start
    while lines and lines[0].startswith(":"):
        lines = lines[1:]
    steps, _ = _parse_steps(lines, 0, stop_prefixes=set())
    return tuple(steps)


def _strip_comments(text: str) -> str:
    """Remove // line comments and /* block */ comments."""
    # Remove block comments first
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Remove line comments
    text = re.sub(r"//[^\n]*", "", text)
    return text


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

        if lower == "begin" or lower.startswith("begin "):
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

        if lower.startswith("forever "):
            step, index = _parse_forever(lines, index)
            steps.append(step)
            continue

        if lower.startswith("disable "):
            step, index = _parse_disable(lines, index)
            steps.append(step)
            continue

        if lower.startswith(("case ", "casez ", "casex ")):
            step, index = _parse_case(lines, index)
            steps.append(step)
            continue

        if lower.startswith("fork"):
            step, index = _parse_fork(lines, index)
            steps.append(step)
            continue

        if lower.startswith("#"):
            step, index = _parse_delay(lines, index)
            steps.append(step)
            continue

        if lower.startswith("@"):
            step, index = _parse_event_wait(lines, index)
            steps.append(step)
            continue

        if lower.startswith("wait "):
            step, index = _parse_wait_condition(lines, index)
            steps.append(step)
            continue

        if lower.startswith(("end", "endcase", "else")):
            break

        steps.append(ActionFlowStep(_clean_line(line)))
        index += 1

    return steps, index


def _parse_if(lines: list[str], index: int) -> tuple[IfFlowStep, int]:
    line = lines[index]
    lower_line = line.lower()
    has_begin_on_same_line = " begin" in lower_line

    # Extract condition
    if_part = line[2:].strip()
    if has_begin_on_same_line:
        if_part = if_part.replace(" begin", "").strip()
    condition = _extract_parenthesized(if_part) or "condition"

    index += 1

    if has_begin_on_same_line:
        # Parse until 'end' or line containing 'else'
        then_steps = []
        while index < len(lines):
            line = lines[index]
            lower = line.lower()
            if lower.startswith("end") or "else" in lower:
                break
            if lower == "begin":
                nested, index = _parse_steps(lines, index + 1, stop_prefixes={"end"})
                then_steps.extend(nested)
                if index < len(lines) and lines[index].lower().startswith("end"):
                    index += 1
                continue
            # Single statement
            then_steps.append(_single_line_step(line))
            index += 1
    else:
        then_steps, index = _parse_branch_body(lines, index)

    else_steps: tuple[ControlFlowStep, ...] = ()
    # Skip any 'end' lines and look for 'else'
    while index < len(lines) and lines[index].lower().startswith("end"):
        index += 1
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
            # Check if 'begin' is on the same line as 'else'
            has_begin_on_same_line = " begin" in else_line.lower()
            index += 1

            if has_begin_on_same_line:
                # Parse until 'end'
                parsed_else, index = _parse_steps(lines, index, stop_prefixes={"end"})
                if index < len(lines) and lines[index].lower().startswith("end"):
                    index += 1
            else:
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
    lower_line = line.lower()
    has_begin_on_same_line = " begin" in lower_line

    # Extract condition
    while_part = line[5:].strip()
    if has_begin_on_same_line:
        while_part = while_part.replace(" begin", "").strip()
    condition = _extract_parenthesized(while_part) or "condition"

    index += 1

    if has_begin_on_same_line:
        # Parse until 'end'
        body_steps, index = _parse_steps(lines, index, stop_prefixes={"end"})
        if index < len(lines) and lines[index].lower().startswith("end"):
            index += 1
    else:
        body_steps, index = _parse_branch_body(lines, index)

    return WhileFlowStep(condition=condition, body_steps=tuple(body_steps)), index


def _parse_for(lines: list[str], index: int) -> tuple[ForInFlowStep, int]:
    line = lines[index]
    # Check if 'begin' is on the same line as 'for'
    lower_line = line.lower()
    has_begin_on_same_line = " begin" in lower_line

    # Extract header
    for_part = line[3:].strip()
    if has_begin_on_same_line:
        for_part = for_part.replace(" begin", "").strip()
    header = _extract_parenthesized(for_part) or "i in range"

    index += 1

    if has_begin_on_same_line:
        # Parse until 'end'
        body_steps, index = _parse_steps(lines, index, stop_prefixes={"end"})
        if index < len(lines) and lines[index].lower().startswith("end"):
            index += 1
    else:
        # Single statement or begin on next line
        body_steps, index = _parse_branch_body(lines, index)

    return ForInFlowStep(header=header, body_steps=tuple(body_steps)), index


def _parse_repeat(lines: list[str], index: int) -> tuple[RepeatWhileFlowStep, int]:
    line = lines[index]
    lower_line = line.lower()
    has_begin_on_same_line = " begin" in lower_line

    # Extract condition
    repeat_part = line[6:].strip()
    if has_begin_on_same_line:
        repeat_part = repeat_part.replace(" begin", "").strip()
    condition = _extract_parenthesized(repeat_part) or "condition"

    index += 1

    if has_begin_on_same_line:
        # Parse until 'end'
        body_steps, index = _parse_steps(lines, index, stop_prefixes={"end"})
        if index < len(lines) and lines[index].lower().startswith("end"):
            index += 1
    else:
        body_steps, index = _parse_branch_body(lines, index)

    return RepeatWhileFlowStep(condition=condition, body_steps=tuple(body_steps)), index


def _parse_forever(lines: list[str], index: int) -> tuple[ForeverFlowStep, int]:
    line = lines[index]
    lower_line = line.lower()
    has_begin_on_same_line = " begin" in lower_line

    index += 1

    if has_begin_on_same_line:
        # Parse until 'end'
        body_steps, index = _parse_steps(lines, index, stop_prefixes={"end"})
        if index < len(lines) and lines[index].lower().startswith("end"):
            index += 1
    else:
        body_steps, index = _parse_branch_body(lines, index)

    return ForeverFlowStep(body_steps=tuple(body_steps)), index


def _parse_disable(lines: list[str], index: int) -> tuple[DisableFlowStep, int]:
    line = lines[index]
    target = line[7:].strip().removesuffix(";")  # Remove "disable " prefix and semicolon
    return DisableFlowStep(target=target), index + 1


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
            label, _, after_colon = current.partition(":")
            label = label.strip()
            after_colon = after_colon.strip().removesuffix(";").strip()
            index += 1
            case_steps: list[ControlFlowStep] = []
            # If there's a statement on the same line after the colon, capture it
            if after_colon:
                case_steps.append(ActionFlowStep(after_colon))
            while index < len(lines):
                next_line = lines[index]
                if next_line.lower().startswith("endcase") or _is_case_label_line(next_line):
                    break
                if next_line.lower() == "begin":
                    nested, index = _parse_steps(lines, index + 1, stop_prefixes={"end"})
                    case_steps.extend(nested)
                    if index < len(lines) and lines[index].lower().startswith("end"):
                        index += 1
                    continue
                if next_line.lower().startswith("end"):
                    index += 1
                    continue
                parsed, index = _parse_steps(lines, index, stop_prefixes={"endcase"})
                case_steps.extend(parsed)
            cases.append(SwitchCaseFlow(label=label, steps=tuple(case_steps)))
            continue

        index += 1

    return SwitchFlowStep(expression=expression, cases=tuple(cases)), index


def _parse_fork(lines: list[str], index: int) -> tuple[ForkJoinFlowStep, int]:
    line = lines[index]
    lower_line = line.lower()
    has_begin_on_same_line = " begin" in lower_line

    index += 1

    # Always parse until join/join_any/join_none
    body_steps, index = _parse_steps(lines, index, stop_prefixes={"join", "join_any", "join_none"})
    # Determine join type from the line we stopped at
    join_type = "join"
    if index < len(lines):
        stop_line = lines[index].lower().strip()
        if stop_line.startswith("join_any"):
            join_type = "join_any"
        elif stop_line.startswith("join_none"):
            join_type = "join_none"
        index += 1

    return ForkJoinFlowStep(join_type=join_type, body_steps=tuple(body_steps)), index


def _parse_delay(lines: list[str], index: int) -> tuple[DelayFlowStep, int]:
    line = lines[index]
    lower_line = line.lower()
    has_begin_on_same_line = " begin" in lower_line

    # Extract delay value: #10, #(5:3:2), etc.
    delay_match = re.match(r"#\s*(\([^)]+\)|\w+)", line)
    delay = delay_match.group(1) if delay_match else line[1:].strip().split()[0]

    # Check for same-line statement after delay
    after_delay = ""
    if delay_match:
        after_delay = line[delay_match.end():].strip().removesuffix(";").strip()

    index += 1

    if has_begin_on_same_line:
        body_steps, index = _parse_steps(lines, index, stop_prefixes={"end"})
        if index < len(lines) and lines[index].lower().startswith("end"):
            index += 1
    elif after_delay:
        body_steps = [ActionFlowStep(after_delay)]
    else:
        body_steps, index = _parse_branch_body(lines, index)

    return DelayFlowStep(delay=delay, body_steps=tuple(body_steps)), index


def _parse_event_wait(lines: list[str], index: int) -> tuple[EventWaitFlowStep, int]:
    line = lines[index]
    lower_line = line.lower()
    has_begin_on_same_line = " begin" in lower_line

    # Extract event: @(posedge clk), @(a or b), etc.
    rest = line[1:].strip()
    event = _extract_parenthesized(rest) or "event"

    # Check for same-line statement after @(event)
    after_event = _extract_after_parenthesized(rest)

    index += 1

    if has_begin_on_same_line:
        body_steps, index = _parse_steps(lines, index, stop_prefixes={"end"})
        if index < len(lines) and lines[index].lower().startswith("end"):
            index += 1
    elif after_event:
        body_steps = [ActionFlowStep(_clean_line(after_event))]
    else:
        body_steps, index = _parse_branch_body(lines, index)

    return EventWaitFlowStep(event=event, body_steps=tuple(body_steps)), index


def _parse_wait_condition(lines: list[str], index: int) -> tuple[WaitConditionFlowStep, int]:
    line = lines[index]
    lower_line = line.lower()
    has_begin_on_same_line = " begin" in lower_line

    # Extract condition: wait (expr)
    wait_part = line[4:].strip()
    if has_begin_on_same_line:
        wait_part = wait_part.replace(" begin", "").strip()
    condition = _extract_parenthesized(wait_part) or "condition"

    # Check for same-line statement after wait (condition)
    after_condition = _extract_after_parenthesized(wait_part)

    index += 1

    if has_begin_on_same_line:
        body_steps, index = _parse_steps(lines, index, stop_prefixes={"end"})
        if index < len(lines) and lines[index].lower().startswith("end"):
            index += 1
    elif after_condition:
        body_steps = [ActionFlowStep(_clean_line(after_condition))]
    else:
        body_steps, index = _parse_branch_body(lines, index)

    return WaitConditionFlowStep(condition=condition, body_steps=tuple(body_steps)), index


def _parse_branch_body(lines: list[str], index: int) -> tuple[list[ControlFlowStep], int]:
    if index >= len(lines):
        return [], index

    line = lines[index].lower()
    if line == "begin" or line.startswith("begin "):
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
    if lower.startswith("forever"):
        return ForeverFlowStep(body_steps=())
    if lower.startswith("disable "):
        target = line[7:].strip().removesuffix(";")
        return DisableFlowStep(target=target)
    if lower.startswith(("case ", "casez ", "casex ")):
        prefix_len = 5 if lower.startswith("casez ") or lower.startswith("casex ") else 4
        expr = _extract_parenthesized(line[prefix_len:].strip()) or "expression"
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


def _extract_after_parenthesized(text: str) -> str:
    """Return text after the closing ')' of the first parenthesized group."""
    open_index = text.find("(")
    if open_index == -1:
        return ""
    close_index = text.find(")", open_index)
    if close_index == -1:
        return ""
    after = text[close_index + 1:].strip().removesuffix(";").strip()
    return after


def _is_case_label_line(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("//"):
        return False
    if stripped.lower().startswith("default:"):
        return True
    return ":" in stripped and not stripped.lower().startswith(
        ("if ", "for ", "while ", "repeat ", "case ", "//")
    )


# Backward-compatible alias for downstream imports during migration.
AntlrSwiftControlFlowExtractor = AntlrVerilogControlFlowExtractor
