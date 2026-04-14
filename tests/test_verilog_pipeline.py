from __future__ import annotations

from dataclasses import dataclass

import pytest

from swifta.domain.errors import InputValidationError
from swifta.domain.control_flow import (
    ActionFlowStep,
    ForInFlowStep,
    IfFlowStep,
    RepeatWhileFlowStep,
    SwitchFlowStep,
    WhileFlowStep,
)
from swifta.domain.model import SourceUnit, SourceUnitId, StructuralElementKind
from swifta.infrastructure.antlr.antlr_control_flow_extractor import (
    AntlrVerilogControlFlowExtractor,
)
from swifta.infrastructure.antlr.control_flow_extractor import (
    _extract_steps,
    _scan_procedural_blocks,
)
from swifta.infrastructure.antlr.parser_adapter import (
    _extract_structural_elements,
    _next_identifier,
)
from swifta.infrastructure.filesystem.source_repository import FileSystemSourceRepository


@dataclass(frozen=True)
class _Token:
    type: int
    text: str
    line: int = 1
    column: int = 0


class _Lexer:
    MODULE = 1
    FUNCTION = 2
    TASK = 3
    SIMPLE_IDENTIFIER = 4
    ESCAPED_IDENTIFIER = 5
    EOF = -1


def test_extract_structural_elements_finds_module_function_and_task() -> None:
    tokens = [
        _Token(_Lexer.MODULE, "module", line=1),
        _Token(_Lexer.SIMPLE_IDENTIFIER, "alu", line=1, column=7),
        _Token(_Lexer.FUNCTION, "function", line=5),
        _Token(_Lexer.SIMPLE_IDENTIFIER, "compute", line=5, column=9),
        _Token(_Lexer.TASK, "task", line=11),
        _Token(_Lexer.ESCAPED_IDENTIFIER, r"\do_work", line=11, column=5),
        _Token(_Lexer.EOF, "<EOF>", line=99),
    ]

    elements = _extract_structural_elements(tokens, _Lexer)
    assert [element.name for element in elements] == ["alu", "compute", "do_work"]
    assert [element.kind for element in elements] == [
        StructuralElementKind.CLASS,
        StructuralElementKind.FUNCTION,
        StructuralElementKind.FUNCTION,
    ]


def test_next_identifier_stops_at_statement_boundary() -> None:
    tokens = [
        _Token(_Lexer.MODULE, "module"),
        _Token(100, ";"),
        _Token(_Lexer.SIMPLE_IDENTIFIER, "never_reached"),
    ]
    assert _next_identifier(tokens, 1, _Lexer.SIMPLE_IDENTIFIER, _Lexer.ESCAPED_IDENTIFIER) is None


def test_scan_procedural_blocks_supports_nested_begin_end() -> None:
    source = """
module top;
  always @(posedge clk) begin
    if (en) begin
      value <= value + 1;
    end
  end
  initial begin
    done <= 1'b0;
  end
endmodule
"""
    blocks = _scan_procedural_blocks(source)
    assert [block.name for block in blocks] == ["always_1", "initial_2"]
    assert "value <= value + 1;" in blocks[0].body
    assert "done <= 1'b0;" in blocks[1].body


def test_extract_steps_maps_common_control_constructs() -> None:
    body = "\n".join(
        [
            "if (a > 0)",
            "result <= value;",
            "while (ready)",
            "result <= next;",
            "for (i = 0; i < 4; i = i + 1)",
            "result <= i;",
            "repeat (3)",
            "result <= result + 1;",
            "case (state)",
            "0: ",
            "result <= 0;",
            "default:",
            "result <= 1;",
            "endcase",
            "result <= value;",
        ]
    )
    steps = _extract_steps(body)
    assert isinstance(steps[0], IfFlowStep)
    assert isinstance(steps[1], WhileFlowStep)
    assert isinstance(steps[2], ForInFlowStep)
    assert isinstance(steps[3], RepeatWhileFlowStep)
    assert isinstance(steps[4], SwitchFlowStep)
    assert isinstance(steps[5], ActionFlowStep)


def test_extract_steps_builds_if_else_bodies() -> None:
    body = "\n".join(
        [
            "if (a > 0)",
            "begin",
            "x <= 1;",
            "end",
            "else",
            "begin",
            "x <= 0;",
            "end",
        ]
    )
    steps = _extract_steps(body)
    assert len(steps) == 1
    assert isinstance(steps[0], IfFlowStep)
    assert [step.label for step in steps[0].then_steps if isinstance(step, ActionFlowStep)] == [
        "x <= 1"
    ]
    assert [step.label for step in steps[0].else_steps if isinstance(step, ActionFlowStep)] == [
        "x <= 0"
    ]


def test_extract_steps_builds_case_labels() -> None:
    body = "\n".join(
        [
            "case (state)",
            "2'b00:",
            "result <= 0;",
            "2'b01:",
            "result <= 1;",
            "default:",
            "result <= 2;",
            "endcase",
        ]
    )
    steps = _extract_steps(body)
    assert len(steps) == 1
    assert isinstance(steps[0], SwitchFlowStep)
    assert [case.label for case in steps[0].cases] == ["2'b00", "2'b01", "default"]
    assert steps[0].cases[0].steps and isinstance(steps[0].cases[0].steps[0], ActionFlowStep)


def test_control_flow_extractor_builds_diagram_from_verilog_source() -> None:
    source = SourceUnit(
        identifier=SourceUnitId("simple.v"),
        location="simple.v",
        content=(
            "module simple;\n"
            "  always @(posedge clk) begin\n"
            "    if (rst) value <= 0;\n"
            "  end\n"
            "endmodule\n"
        ),
    )
    diagram = AntlrVerilogControlFlowExtractor().extract(source)
    assert diagram.source_location == "simple.v"
    assert len(diagram.functions) == 1
    assert diagram.functions[0].name == "always_1"


def test_source_repository_accepts_v_files(tmp_path) -> None:
    source_file = tmp_path / "good.v"
    source_file.write_text("module good; endmodule\n", encoding="utf-8")

    repository = FileSystemSourceRepository()
    loaded = repository.load_file(str(source_file))
    assert loaded.location.endswith("good.v")
    assert "module good" in loaded.content


def test_source_repository_rejects_non_verilog_extension(tmp_path) -> None:
    source_file = tmp_path / "bad.sv"
    source_file.write_text("module bad; endmodule\n", encoding="utf-8")

    repository = FileSystemSourceRepository()
    with pytest.raises(InputValidationError, match=r"expected a \.v file"):
        repository.load_file(str(source_file))
