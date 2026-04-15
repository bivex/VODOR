"""Tests for the Verilog diagram renderer."""

from __future__ import annotations

from swifta.domain.control_flow import (
    ActionFlowStep,
    CatchClauseFlow,
    ControlFlowDiagram,
    ControlFlowStep,
    DeferFlowStep,
    DelayFlowStep,
    DisableFlowStep,
    DoCatchFlowStep,
    EventWaitFlowStep,
    ForeverFlowStep,
    ForkJoinFlowStep,
    ForInFlowStep,
    FunctionControlFlow,
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
from swifta.infrastructure.rendering.verilog_renderer import (
    VerilogDiagramRenderer,
    _normalize_case_label,
    _parse_for_in_header,
    _parse_parameters,
    _sanitize_identifier,
    _sanitize_verilog_expression,
)


def _render_steps(*steps: ControlFlowStep) -> str:
    diagram = ControlFlowDiagram(
        source_location="test.swift",
        functions=(
            FunctionControlFlow(
                name="test_func",
                signature="func test_func()",
                container=None,
                steps=steps,
            ),
        ),
    )
    return VerilogDiagramRenderer().render(diagram)


class TestVerilogRendererAction:
    def test_action_step(self) -> None:
        result = _render_steps(ActionFlowStep("total = total + 1"))
        assert "total = total + 1;" in result

    def test_multiple_actions(self) -> None:
        result = _render_steps(
            ActionFlowStep("x = 1"),
            ActionFlowStep("y = 2"),
        )
        assert "x = 1;" in result
        assert "y = 2;" in result


class TestVerilogRendererIf:
    def test_if_only(self) -> None:
        result = _render_steps(
            IfFlowStep(
                condition="x > 0",
                then_steps=(ActionFlowStep("y = 1"),),
                else_steps=(),
            )
        )
        assert "if (x > 0) begin" in result
        assert "y = 1;" in result
        assert "end\n" in result
        assert "else" not in result

    def test_if_else(self) -> None:
        result = _render_steps(
            IfFlowStep(
                condition="x > 0",
                then_steps=(ActionFlowStep("y = 1"),),
                else_steps=(ActionFlowStep("y = -1"),),
            )
        )
        assert "if (x > 0) begin" in result
        assert "else begin" in result
        assert "y = 1;" in result
        assert "y = -1;" in result

    def test_nested_if(self) -> None:
        result = _render_steps(
            IfFlowStep(
                condition="x > 0",
                then_steps=(
                    IfFlowStep(
                        condition="x > 10",
                        then_steps=(ActionFlowStep("z = 1"),),
                        else_steps=(),
                    ),
                ),
                else_steps=(),
            )
        )
        assert "if (x > 0) begin" in result
        assert "if (x > 10) begin" in result
        # Verify nesting — inner if should be indented more
        lines = result.split("\n")
        inner_lines = [l for l in lines if "x > 10" in l]
        assert len(inner_lines) == 1
        inner_indent = len(inner_lines[0]) - len(inner_lines[0].lstrip())
        outer_lines = [l for l in lines if "x > 0" in l]
        outer_indent = len(outer_lines[0]) - len(outer_lines[0].lstrip())
        assert inner_indent > outer_indent


class TestVerilogRendererGuard:
    def test_guard(self) -> None:
        result = _render_steps(
            GuardFlowStep(
                condition="x >= 0",
                else_steps=(ActionFlowStep("return 0"),),
            )
        )
        assert "// guard: x >= 0" in result
        assert "if (!(x >= 0)) begin" in result
        assert "return 0;" in result


class TestVerilogRendererWhile:
    def test_while_loop(self) -> None:
        result = _render_steps(
            WhileFlowStep(
                condition="total > 100",
                body_steps=(ActionFlowStep("total = total - 10"),),
            )
        )
        assert "while (total > 100) begin" in result
        assert "total = total - 10;" in result


class TestVerilogRendererForIn:
    def test_for_in(self) -> None:
        result = _render_steps(
            ForInFlowStep(
                header="value in values",
                body_steps=(ActionFlowStep("sum = sum + value"),),
            )
        )
        assert "// for value in values" in result
        assert "for (value = 0; value < values; value = value + 1) begin" in result
        assert "sum = sum + value;" in result


class TestVerilogRendererRepeatWhile:
    def test_repeat_while(self) -> None:
        result = _render_steps(
            RepeatWhileFlowStep(
                condition="total > 50",
                body_steps=(ActionFlowStep("total = total - 1"),),
            )
        )
        assert "begin\n" in result
        assert "while (total > 50) begin" in result
        assert "total = total - 1;" in result


class TestVerilogRendererSwitch:
    def test_switch(self) -> None:
        result = _render_steps(
            SwitchFlowStep(
                expression="total",
                cases=(
                    SwitchCaseFlow(
                        label="case 0:",
                        steps=(ActionFlowStep("result = 0"),),
                    ),
                    SwitchCaseFlow(
                        label="case 1:",
                        steps=(ActionFlowStep("result = 1"),),
                    ),
                    SwitchCaseFlow(
                        label="default:",
                        steps=(ActionFlowStep("result = total"),),
                    ),
                ),
            )
        )
        assert "case (total)" in result
        assert "0: begin" in result
        assert "1: begin" in result
        assert "default: begin" in result
        assert "endcase" in result

    def test_switch_no_cases(self) -> None:
        result = _render_steps(
            SwitchFlowStep(expression="x", cases=())
        )
        assert "// switch x (no cases)" in result


class TestVerilogRendererDoCatch:
    def test_do_catch(self) -> None:
        result = _render_steps(
            DoCatchFlowStep(
                body_steps=(ActionFlowStep("perform_work()"),),
                catches=(
                    CatchClauseFlow(
                        pattern="Error e",
                        steps=(ActionFlowStep("handle_error()"),),
                    ),
                ),
            )
        )
        assert "// do-catch" in result
        assert "// catch Error e" in result
        assert "perform_work();" in result
        assert "handle_error();" in result


class TestVerilogRendererDefer:
    def test_defer(self) -> None:
        result = _render_steps(
            DeferFlowStep(body_steps=(ActionFlowStep("cleanup()"),))
        )
        assert "// defer" in result
        assert "cleanup();" in result


class TestVerilogRendererModule:
    def test_function_to_module(self) -> None:
        diagram = ControlFlowDiagram(
            source_location="Algorithms.swift",
            functions=(
                FunctionControlFlow(
                    name="score",
                    signature="func score(_ values: [Int]) -> Int",
                    container=None,
                    steps=(ActionFlowStep("total = 0"),),
                ),
            ),
        )
        result = VerilogDiagramRenderer().render(diagram)
        assert "module score (" in result
        assert "initial begin" in result
        assert "endmodule" in result
        assert "`timescale" in result

    def test_function_with_container(self) -> None:
        diagram = ControlFlowDiagram(
            source_location="test.swift",
            functions=(
                FunctionControlFlow(
                    name="normalize",
                    signature="func normalize(_ input: Int) -> Int",
                    container="MathBox",
                    steps=(ActionFlowStep("return input"),),
                ),
            ),
        )
        result = VerilogDiagramRenderer().render(diagram)
        assert "module MathBox_normalize (" in result
        assert "// Container: MathBox" in result

    def test_empty_diagram(self) -> None:
        diagram = ControlFlowDiagram(
            source_location="empty.swift",
            functions=(),
        )
        result = VerilogDiagramRenderer().render(diagram)
        assert "No functions found" in result
        assert "module" not in result


class TestVerilogHelpers:
    def test_sanitize_identifier(self) -> None:
        assert _sanitize_identifier("hello.world") == "hello_world"
        assert _sanitize_identifier("foo-bar") == "foo_bar"
        assert _sanitize_identifier("123start") == "_123start"

    def test_parse_parameters(self) -> None:
        assert _parse_parameters("func score(_ values: [Int]) -> Int") == ["values"]
        assert _parse_parameters("func add(_ a: Int, _ b: Int) -> Int") == ["a", "b"]
        assert _parse_parameters("func run()") == ["in0"]

    def test_sanitize_verilog_expression(self) -> None:
        assert _sanitize_verilog_expression("a>0&&b<10") == "a > 0 && b < 10"
        assert _sanitize_verilog_expression("x==1") == "x == 1"

    def test_parse_for_in_header(self) -> None:
        assert _parse_for_in_header("value in values") == ("value", "values")
        assert _parse_for_in_header("i in range") == ("i", "range")

    def test_normalize_case_label(self) -> None:
        assert _normalize_case_label("case 0:") == "0"
        assert _normalize_case_label("default:") == "default"
        assert _normalize_case_label("case .foo:") == "'.foo"


class TestVerilogRendererEmptySequence:
    def test_empty_steps(self) -> None:
        result = _render_steps()
        assert "// (empty)" in result


class TestVerilogRendererForever:
    def test_forever_begin_end(self) -> None:
        result = _render_steps(ForeverFlowStep(body_steps=(ActionFlowStep("x <= x + 1"),)))
        assert "forever begin" in result
        assert "x <= x + 1;" in result
        assert result.count("end\n") >= 1

    def test_forever_nested_disable(self) -> None:
        result = _render_steps(
            ForeverFlowStep(
                body_steps=(
                    ActionFlowStep("x <= x + 1"),
                    DisableFlowStep(target="loop"),
                ),
            )
        )
        assert "forever begin" in result
        assert "disable loop;" in result


class TestVerilogRendererDisable:
    def test_disable_emits_target(self) -> None:
        result = _render_steps(DisableFlowStep(target="processing_block"))
        assert "disable processing_block;" in result


class TestVerilogRendererForkJoin:
    def test_fork_join(self) -> None:
        result = _render_steps(
            ForkJoinFlowStep(
                join_type="join",
                body_steps=(ActionFlowStep("a <= 1"), ActionFlowStep("b <= 2")),
            )
        )
        assert "fork\n" in result
        assert "a <= 1;" in result
        assert "b <= 2;" in result
        assert "join\n" in result

    def test_fork_join_any(self) -> None:
        result = _render_steps(ForkJoinFlowStep(join_type="join_any", body_steps=()))
        assert "fork\n" in result
        assert "join_any\n" in result

    def test_fork_join_none(self) -> None:
        result = _render_steps(ForkJoinFlowStep(join_type="join_none", body_steps=()))
        assert "join_none\n" in result


class TestVerilogRendererDelay:
    def test_delay_with_body(self) -> None:
        result = _render_steps(DelayFlowStep(delay="10", body_steps=(ActionFlowStep("x <= 1"),)))
        assert "#10 begin" in result
        assert "x <= 1;" in result


class TestVerilogRendererEventWait:
    def test_event_wait_with_body(self) -> None:
        result = _render_steps(EventWaitFlowStep(event="posedge clk", body_steps=(ActionFlowStep("x <= data"),)))
        assert "@(posedge clk) begin" in result
        assert "x <= data;" in result


class TestVerilogRendererWaitCondition:
    def test_wait_with_body(self) -> None:
        result = _render_steps(WaitConditionFlowStep(condition="ready == 1", body_steps=(ActionFlowStep("x <= 1"),)))
        assert "wait (ready == 1) begin" in result
        assert "x <= 1;" in result


class TestStructVerification:
    def test_struct_declaration(self) -> None:
        result = _render_steps(
            StructDeclarationFlowStep(
                name="my_struct",
                fields=(
                    ("field_a", "int"),
                    ("field_b", "float"),
                ),
            )
        )
        assert "Struct: my_struct" in result
        assert "field_a: int" in result
        assert "field_b: float" in result

    def test_struct_field_access_read(self) -> None:
        result = _render_steps(
            StructFieldAccessFlowStep(
                struct_name="my_struct",
                field_name="field_a",
                is_write=False,
            )
        )
        assert "// read my_struct.field_a" in result
        assert "my_struct.field_a;" in result

    def test_struct_field_access_write(self) -> None:
        result = _render_steps(
            StructFieldAccessFlowStep(
                struct_name="my_struct",
                field_name="field_a",
                is_write=True,
            )
        )
        assert "// write my_struct.field_a" in result
        assert "my_struct.field_a;" in result

class TestVerilogRendererUnsupported:
    def test_unknown_step_type_raises(self) -> None:
        from dataclasses import dataclass
        from swifta.domain.control_flow import ControlFlowStep

        @dataclass(frozen=True)
        class FakeStep(ControlFlowStep):
            pass

        import pytest
        with pytest.raises(TypeError, match="unsupported step type"):
            _render_steps(FakeStep())
