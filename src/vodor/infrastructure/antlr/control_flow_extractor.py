"""Extract structured control flow from Verilog source."""

from __future__ import annotations

import re
from dataclasses import dataclass

from vodor.domain.control_flow import (
    ActionFlowStep,
    ActionKind,
    ControlFlowDiagram,
    ControlFlowStep,
    Declaration,
    DeferFlowStep,
    DelayFlowStep,
    DisableFlowStep,
    EventWaitFlowStep,
    ForkJoinFlowStep,
    ForInFlowStep,
    ForeverFlowStep,
    FunctionControlFlow,
    GenerateBlock,
    IfFlowStep,
    ModuleInstantiation,
    ModuleStructure,
    PortConnection,
    PortDeclaration,
    RepeatWhileFlowStep,
    SwitchCaseFlow,
    SwitchFlowStep,
    WaitConditionFlowStep,
    WhileFlowStep,
)
from vodor.domain.model import SourceUnit
from vodor.domain.ports import VerilogControlFlowExtractor


@dataclass(frozen=True, slots=True)
class _BlockSlice:
    name: str
    body: str
    kind: str = "always"
    sensitivity: str | None = None
    signature: str | None = None
    start: int = 0
    end: int = 0


class AntlrVerilogControlFlowExtractor(VerilogControlFlowExtractor):
    def extract(self, source_unit: SourceUnit) -> ControlFlowDiagram:
        cleaned = _strip_comments(source_unit.content)
        blocks = _scan_procedural_blocks_impl(cleaned)
        top_actions = _scan_top_level_actions(cleaned, blocks)
        module_structure = _scan_module_structure(cleaned, blocks)

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
            top_level_steps=tuple(top_actions),
            module_structure=module_structure,
        )


def _scan_procedural_blocks(source_text: str) -> tuple[_BlockSlice, ...]:
    cleaned = _strip_comments(source_text)
    return _scan_procedural_blocks_impl(cleaned)


def _scan_procedural_blocks_impl(cleaned_text: str) -> tuple[_BlockSlice, ...]:
    blocks: list[_BlockSlice] = []
    # Scan always/initial blocks
    blocks.extend(_scan_always_initial(cleaned_text))
    # Scan function/task blocks
    blocks.extend(_scan_function_task(cleaned_text))
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
        block_start = match.start()

        # Capture sensitivity list for always blocks: @(...) or @*
        sensitivity: str | None = None
        rest = source_text[match.end() :]
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
            block_end = semi + 1
            if body:
                blocks.append(
                    _BlockSlice(
                        name=f"{kind}_{counter}",
                        body=body,
                        kind=kind,
                        sensitivity=sensitivity,
                        start=block_start,
                        end=block_end,
                    )
                )
                counter += 1
            index = block_end
            continue

        end_index = _find_matching_end(source_text, begin_index)
        if end_index == -1:
            index = after_sens
            continue
        body = source_text[begin_index + len("begin") : end_index].strip()
        block_end = end_index + 3  # len("end")
        blocks.append(
            _BlockSlice(
                name=f"{kind}_{counter}",
                body=body,
                kind=kind,
                sensitivity=sensitivity,
                start=block_start,
                end=block_end,
            )
        )
        counter += 1
        index = block_end
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
        block_start = match.start()
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

        block_end = end_match.end()
        blocks.append(
            _BlockSlice(
                name=name,
                body=body,
                kind=kind,
                sensitivity=None,
                signature=signature,
                start=block_start,
                end=block_end,
            )
        )
        index = block_end
    return blocks


def _extract_last_identifier(text: str) -> str | None:
    """Extract the last Verilog identifier from a header line."""
    # Match word characters, allowing brackets for return types like [7:0]
    tokens = re.findall(r"[a-zA-Z_]\w*", text)
    # Filter out Verilog keywords that commonly appear in headers
    keywords = {
        "input",
        "output",
        "inout",
        "reg",
        "wire",
        "integer",
        "signed",
        "unsigned",
        "begin",
        "end",
        "automatic",
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
    # Split compound lines like "end else begin" and "end else if ..." into separate lines
    lines = _split_compound_end(lines)
    # Join continuation lines (multi-line expressions ending with ||, &&, etc.)
    lines = _join_continuation_lines(lines)
    # Skip named begin labels like ": processing_block" at the start
    while lines and lines[0].startswith(":"):
        lines = lines[1:]
    steps, _ = _parse_steps(lines, 0, stop_prefixes=set())
    return tuple(steps)


def _join_continuation_lines(lines: list[str]) -> list[str]:
    """Join lines that are continuations of multi-line expressions.

    A line is a continuation target (should pull in the next line) if it ends
    with a binary operator (``||``, ``&&``) or a comma, or has more opening
    parentheses/brackets than closing ones.
    """
    _CONTINUATION_SUFFIXES = ("||", "&&", ",")
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Keep joining while the current accumulated line is a continuation target
        while i + 1 < len(lines) and _is_continuation(line):
            i += 1
            line = line + " " + lines[i]
        result.append(line)
        i += 1
    return result


def _is_continuation(line: str) -> bool:
    """Return True if *line* expects more content on the next line."""
    stripped = line.rstrip()
    if not stripped:
        return False
    # Ends with a binary operator or comma
    if stripped.endswith(("||", "&&", ",")):
        return True
    # Unbalanced parentheses — more ( than )
    if stripped.count("(") > stripped.count(")"):
        return True
    return False


def _split_compound_end(lines: list[str]) -> list[str]:
    """Split 'end else ...' on the same line into ['end', 'else ...']."""
    result: list[str] = []
    for line in lines:
        lower = line.lower()
        if lower.startswith("end ") and ("else" in lower[4:] or "join" in lower[4:]):
            # "end else begin" → ["end", "else begin"]
            # "end else if ..." → ["end", "else if ..."]
            # "end join" → ["end", "join"]  (unlikely but safe)
            after_end = line[3:].strip()
            result.append("end")
            result.append(after_end)
        else:
            result.append(line)
    return result


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

        steps.append(_classify_action(line))
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
        # Parse the then-body until matching 'end'
        then_steps, index = _parse_steps(lines, index, stop_prefixes={"end"})
        if index < len(lines) and lines[index].lower().startswith("end"):
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

    lower_header = header_line.lower()
    has_begin_on_same_line = " begin" in lower_header

    if has_begin_on_same_line:
        then_steps, index = _parse_steps(lines, index, stop_prefixes={"end"})
        if index < len(lines) and lines[index].lower().startswith("end"):
            index += 1
    else:
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
            # Handle "label: begin" — open a block immediately
            if after_colon.lower() == "begin":
                nested, index = _parse_steps(lines, index, stop_prefixes={"end"})
                case_steps.extend(nested)
                if index < len(lines) and lines[index].lower().startswith("end"):
                    index += 1
            elif after_colon:
                # Single statement on same line as label
                case_steps.append(ActionFlowStep(after_colon, _classify_kind(after_colon)))
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
                if next_line.lower().startswith("else"):
                    # Dangling else (from a multi-line if misparse) — skip and continue
                    index += 1
                    continue
                prev_index = index
                parsed, index = _parse_steps(lines, index, stop_prefixes={"endcase"})
                case_steps.extend(parsed)
                # Safety: ensure progress to prevent infinite loops
                if index == prev_index:
                    index += 1
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
        after_delay = line[delay_match.end() :].strip().removesuffix(";").strip()

    index += 1

    if has_begin_on_same_line:
        body_steps, index = _parse_steps(lines, index, stop_prefixes={"end"})
        if index < len(lines) and lines[index].lower().startswith("end"):
            index += 1
    elif after_delay:
        body_steps = [_classify_action(after_delay)]
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
        body_steps = [_classify_action(after_event)]
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
        body_steps = [_classify_action(after_condition)]
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
    return _classify_action(line)


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
    after = text[close_index + 1 :].strip().removesuffix(";").strip()
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


def _scan_top_level_actions(
    cleaned_text: str, blocks: tuple[_BlockSlice, ...]
) -> list[ActionFlowStep]:
    """Extract top-level continuous assignment statements (`assign`, `force`, `release`)
    that appear outside of any procedural block (always, initial, function, task).

    Args:
        cleaned_text: Verilog source with /* */ and // comments removed.
        blocks: Tuple of procedural block slices with start/end offsets.

    Returns:
        List of ActionFlowStep objects in source order.
    """
    # Build exclusion intervals from block spans
    excluded = sorted([(b.start, b.end) for b in blocks], key=lambda x: x[0])

    pattern = re.compile(r"\b(assign|force|release)\b[^;]*;", re.IGNORECASE)
    actions: list[ActionFlowStep] = []
    for match in pattern.finditer(cleaned_text):
        s, e = match.start(), match.end()
        # Check if this match lies entirely within any excluded block
        inside = any(s >= ex_start and e <= ex_end for (ex_start, ex_end) in excluded)
        if not inside:
            stmt = match.group().strip().removesuffix(";").strip()
            # Module-level assign/force/release are continuous assignments,
            # not procedural continuous (which is assign/deassign/force/release inside always blocks)
            actions.append(ActionFlowStep(stmt, ActionKind.CONTINUOUS_ASSIGN))
    return actions


# ── Action classification ──

# Matches blocking assignment: lhs = rhs  (but not ==, !=, <=, >=)
_RE_BLOCKING_ASSIGN = re.compile(r"^[^=]*[^!=<>]=[^=].*", re.DOTALL)
# Matches nonblocking assignment: lhs <= rhs
_RE_NONBLOCKING_ASSIGN = re.compile(r"^[^=]*<=\s*.+", re.DOTALL)
# Matches system tasks: $display, $finish, $monitor, etc.
_RE_SYSTEM_TASK = re.compile(r"^\$\w+", re.IGNORECASE)
# Matches event trigger: ->event_name
_RE_EVENT_TRIGGER = re.compile(r"^->\s*\w+", re.DOTALL)
# Matches procedural continuous: assign/deassign/force/release inside always
_RE_PROCEDURAL_CONTINUOUS = re.compile(
    r"^(assign|deassign|force|release)\b", re.IGNORECASE
)


def _classify_action(line: str) -> ActionFlowStep:
    """Create an ActionFlowStep with classified kind from a raw line."""
    clean = _clean_line(line)
    return ActionFlowStep(clean, _classify_kind(clean))


def _classify_kind(clean: str) -> ActionKind:
    """Classify a cleaned action line into an ActionKind."""
    stripped = clean.strip()
    if not stripped:
        return ActionKind.OTHER

    # Event trigger: ->event_name
    if _RE_EVENT_TRIGGER.match(stripped):
        return ActionKind.EVENT_TRIGGER

    # System task: $display, $finish, $monitor, etc.
    if _RE_SYSTEM_TASK.match(stripped):
        return ActionKind.SYSTEM_TASK

    # Procedural continuous assignment: assign/deassign/force/release
    if _RE_PROCEDURAL_CONTINUOUS.match(stripped):
        return ActionKind.PROCEDURAL_CONTINUOUS

    # Nonblocking assignment: lhs <= rhs  (check before blocking because <= also matches =)
    if _RE_NONBLOCKING_ASSIGN.match(stripped):
        return ActionKind.ASSIGNMENT_NONBLOCKING

    # Blocking assignment: lhs = rhs
    if _RE_BLOCKING_ASSIGN.match(stripped):
        return ActionKind.ASSIGNMENT_BLOCKING

    # Task call (bare identifier — no =, no $, no keyword): identifier or identifier(args)
    lower = stripped.lower()
    if re.match(r"^[a-zA-Z_]\w*(\s*\(|\s*$)", stripped) and lower not in {
        "begin",
        "end",
        "if",
        "else",
        "while",
        "for",
        "repeat",
        "forever",
        "disable",
        "case",
        "casez",
        "casex",
        "fork",
        "join",
        "join_any",
        "join_none",
        "wait",
        "assign",
        "deassign",
        "force",
        "release",
    }:
        return ActionKind.TASK_CALL

    return ActionKind.OTHER


# ── Module structure scanning ──

_VERILOG_KEYWORDS = frozenset({
    "always", "and", "assign", "automatic", "begin", "buf", "bufif0", "bufif1",
    "case", "casex", "casez", "cmos", "deassign", "default", "defparam", "disable",
    "edge", "else", "end", "endcase", "endfunction", "endgenerate", "endmodule",
    "endprimitive", "endspecify", "endtable", "endtask", "event", "for", "force",
    "forever", "fork", "function", "generate", "genvar", "highz0", "highz1",
    "if", "ifnone", "initial", "inout", "input", "integer", "join", "join_any",
    "join_none", "large", "localparam", "macromodule", "medium", "module", "nand",
    "negedge", "nmos", "nor", "not", "notif0", "notif1", "or", "output",
    "parameter", "pmos", "posedge", "primitive", "pull0", "pull1", "pulldown",
    "pullup", "rcmos", "real", "realtime", "reg", "release", "repeat", "rnmos",
    "rpmos", "rtran", "rtranif0", "rtranif1", "scalared", "signed", "small",
    "specify", "specparam", "strength", "strong0", "strong1", "supply0", "supply1",
    "table", "task", "time", "tran", "tranif0", "tranif1", "tri", "tri0", "tri1",
    "triand", "trior", "trireg", "unsigned", "vectored", "wait", "wand", "weak0",
    "weak1", "while", "wire", "wor", "xnor", "xor",
})


def _scan_module_structure(
    cleaned_text: str,
    blocks: tuple[_BlockSlice, ...],
) -> ModuleStructure | None:
    header = _parse_module_header(cleaned_text)
    if header is None:
        return None
    name, ports, header_end = header

    excluded = sorted(
        [(b.start, b.end) for b in blocks] + [(0, header_end)],
        key=lambda x: x[0],
    )
    port_names = {p.name for p in ports}

    declarations = _scan_declarations(cleaned_text, excluded, port_names)
    instantiations = _scan_module_instantiations(cleaned_text, excluded)
    generate_blocks = _scan_generate_blocks(cleaned_text, excluded)

    return ModuleStructure(
        name=name,
        ports=ports,
        declarations=declarations,
        instantiations=instantiations,
        generate_blocks=generate_blocks,
    )


def _parse_module_header(
    cleaned_text: str,
) -> tuple[str, tuple[PortDeclaration, ...], int] | None:
    m = re.search(r"\bmodule\s+(\w+)", cleaned_text)
    if m is None:
        return None
    name = m.group(1)

    # Find the port list opening paren, skipping optional #(...) parameter list
    after_name = m.end()
    rest = cleaned_text[after_name:]
    # Check for #( parameter override
    param_match = re.match(r"\s*#\s*\(", rest)
    if param_match:
        # Skip the parameter list
        param_paren_end = _find_matching_paren(cleaned_text, after_name + param_match.end() - 1)
        if param_paren_end != -1:
            paren_start = cleaned_text.find("(", param_paren_end + 1)
        else:
            paren_start = -1
    else:
        paren_start = cleaned_text.find("(", after_name)
    if paren_start == -1:
        # Module with no ports: module name; ... endmodule
        semi = cleaned_text.find(";", after_name)
        header_end = semi + 1 if semi != -1 else after_name
        return name, (), header_end

    # Find matching closing paren
    paren_end = _find_matching_paren(cleaned_text, paren_start)
    if paren_end == -1:
        semi = cleaned_text.find(";", paren_start)
        header_end = semi + 1 if semi != -1 else paren_start + 1
        return name, (), header_end

    port_text = cleaned_text[paren_start + 1 : paren_end].strip()
    header_end = cleaned_text.find(";", paren_end) + 1

    if not port_text:
        return name, (), header_end

    ports = _parse_port_list(port_text)
    return name, ports, header_end


def _find_matching_paren(text: str, open_index: int) -> int:
    depth = 1
    index = open_index + 1
    while index < len(text):
        ch = text[index]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _parse_port_list(port_text: str) -> tuple[PortDeclaration, ...]:
    ports: list[PortDeclaration] = []
    # Split by commas respecting nested brackets
    segments = _split_respecting_brackets(port_text)

    current_direction = "wire"
    current_kind = ""

    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        # Try ANSI-style: direction [kind] [width] name
        ansi_match = re.match(
            r"(input|output|inout)\s+(reg\s+|wire\s+)?"
            r"(\[[^\]]*\])?\s*"
            r"(\w+)",
            seg,
            re.IGNORECASE,
        )
        if ansi_match:
            current_direction = ansi_match.group(1).lower()
            kind_part = ansi_match.group(2)
            if kind_part:
                current_kind = kind_part.strip().lower()
            else:
                current_kind = ""
            width = ansi_match.group(3)
            port_name = ansi_match.group(4)
            ports.append(PortDeclaration(
                direction=current_direction,
                kind=current_kind,
                name=port_name,
                width=width,
            ))
            continue

        # Try simple identifier (non-ANSI or continuation)
        simple_match = re.match(r"(input|output|inout)\s+(\[[^\]]*\])?\s*(\w+)", seg, re.IGNORECASE)
        if simple_match:
            current_direction = simple_match.group(1).lower()
            width = simple_match.group(2)
            port_name = simple_match.group(3)
            ports.append(PortDeclaration(
                direction=current_direction, kind="", name=port_name, width=width,
            ))
            continue

        # Bare name (continuation of previous direction)
        bare_match = re.match(r"(\[[^\]]*\])?\s*(\w+)$", seg.strip())
        if bare_match:
            width = bare_match.group(1)
            port_name = bare_match.group(2)
            ports.append(PortDeclaration(
                direction=current_direction, kind="", name=port_name, width=width,
            ))

    return tuple(ports)


def _split_respecting_brackets(text: str) -> list[str]:
    """Split by commas, but skip commas inside [...]."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in text:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def _scan_declarations(
    cleaned_text: str,
    excluded: list[tuple[int, int]],
    port_names: set[str],
) -> tuple[Declaration, ...]:
    declarations: list[Declaration] = []

    # parameter/localparam
    param_pattern = re.compile(
        r"\b(parameter|localparam)\s+(?:\[/[^;]*?\]\s+)?(\[[^\]]*\])?\s*"
        r"(\w+)\s*=\s*([^;]+);",
        re.IGNORECASE,
    )
    for m in param_pattern.finditer(cleaned_text):
        if _inside_excluded(m.start(), m.end(), excluded):
            continue
        name = m.group(3)
        if name in port_names:
            continue
        declarations.append(Declaration(
            kind=m.group(1).lower(),
            name=name,
            width=m.group(2),
            value=m.group(4).strip(),
        ))

    # wire/reg/integer
    decl_pattern = re.compile(
        r"\b(wire|reg|integer)\s+(\[[^\]]*\])?\s*"
        r"(\w+)"
        r"(?:\s*\[[^\]]*\])?"  # memory dimension — skip
        r"\s*(?:=\s*([^;]+))?\s*;",
        re.IGNORECASE,
    )
    for m in decl_pattern.finditer(cleaned_text):
        if _inside_excluded(m.start(), m.end(), excluded):
            continue
        name = m.group(3)
        if name in port_names:
            continue
        # Skip if this name was already captured as a parameter
        if any(d.name == name for d in declarations):
            continue
        declarations.append(Declaration(
            kind=m.group(1).lower(),
            name=name,
            width=m.group(2),
            value=m.group(4).strip() if m.group(4) else None,
        ))

    return tuple(declarations)


def _inside_excluded(
    start: int, end: int, excluded: list[tuple[int, int]]
) -> bool:
    return any(start >= ex_start and end <= ex_end for ex_start, ex_end in excluded)


def _scan_module_instantiations(
    cleaned_text: str,
    excluded: list[tuple[int, int]],
) -> tuple[ModuleInstantiation, ...]:
    instantiations: list[ModuleInstantiation] = []

    # Match: module_name [#(...)] instance_name (
    candidate_pattern = re.compile(
        r"\b([a-zA-Z_]\w*)\s+"
        r"(?:#\s*\([^;]*?\)\s+)?"  # optional parameter override
        r"([a-zA-Z_]\w*)\s*\(",
        re.DOTALL,
    )
    for m in candidate_pattern.finditer(cleaned_text):
        mod_name = m.group(1)
        inst_name = m.group(2)

        # Filter out keywords
        if mod_name.lower() in _VERILOG_KEYWORDS or inst_name.lower() in _VERILOG_KEYWORDS:
            continue
        if _inside_excluded(m.start(), m.end(), excluded):
            continue

        # Find the port connection list
        paren_start = m.end() - 1  # the opening (
        paren_end = _find_matching_paren(cleaned_text, paren_start)
        if paren_end == -1:
            continue

        conn_text = cleaned_text[paren_start + 1 : paren_end]
        connections = _parse_port_connections(conn_text)

        instantiations.append(ModuleInstantiation(
            module_name=mod_name,
            instance_name=inst_name,
            connections=connections,
        ))

    return tuple(instantiations)


def _parse_port_connections(text: str) -> tuple[PortConnection, ...]:
    connections: list[PortConnection] = []
    for m in re.finditer(r"\.(\w+)\s*\(([^)]*)\)", text):
        connections.append(PortConnection(
            port_name=m.group(1),
            signal=m.group(2).strip(),
        ))
    return tuple(connections)


def _scan_generate_blocks(
    cleaned_text: str,
    excluded: list[tuple[int, int]],
) -> tuple[GenerateBlock, ...]:
    blocks: list[GenerateBlock] = []

    gen_pattern = re.compile(r"\bgenerate\b", re.IGNORECASE)
    endgen_pattern = re.compile(r"\bendgenerate\b", re.IGNORECASE)

    for gen_match in gen_pattern.finditer(cleaned_text):
        if _inside_excluded(gen_match.start(), gen_match.end(), excluded):
            continue
        end_match = endgen_pattern.search(cleaned_text, gen_match.end())
        if end_match is None:
            continue

        body = cleaned_text[gen_match.end() : end_match.start()]

        # for-generate
        for_m = re.finditer(
            r"\bfor\s*\(([^)]+)\)\s*begin\s*(?::\s*(\w+))?",
            body, re.IGNORECASE,
        )
        for fm in for_m:
            blocks.append(GenerateBlock(
                label=fm.group(2),
                kind="for",
                condition=fm.group(1).strip(),
            ))

        # if-generate
        for im in re.finditer(
            r"\bif\s*\(([^)]+)\)\s*begin\s*(?::\s*(\w+))?",
            body, re.IGNORECASE,
        ):
            blocks.append(GenerateBlock(
                label=im.group(2),
                kind="if",
                condition=im.group(1).strip(),
            ))

    return tuple(blocks)


# Backward-compatible alias for downstream imports during migration.
AntlrSwiftControlFlowExtractor = AntlrVerilogControlFlowExtractor
