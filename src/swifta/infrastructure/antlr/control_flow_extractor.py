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
    steps: list[ControlFlowStep] = []
    for line in lines:
        lower = line.lower()
        if lower.startswith("if "):
            condition = line[2:].strip().strip("()")
            steps.append(IfFlowStep(condition=condition, then_steps=(), else_steps=()))
        elif lower.startswith("case "):
            expr = line[4:].strip().strip("()")
            steps.append(SwitchFlowStep(expression=expr, cases=()))
        elif lower.startswith("while "):
            condition = line[5:].strip().strip("()")
            steps.append(WhileFlowStep(condition=condition, body_steps=()))
        elif lower.startswith("for "):
            header = line[3:].strip().strip("()")
            steps.append(ForInFlowStep(header=header or "i in range", body_steps=()))
        else:
            steps.append(ActionFlowStep(line.removesuffix(";")))
    return tuple(steps)


# Backward-compatible alias for downstream imports during migration.
AntlrSwiftControlFlowExtractor = AntlrVerilogControlFlowExtractor
