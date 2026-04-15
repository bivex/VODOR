"""Tests for the Nassi-Shneiderman HTML renderer."""

from __future__ import annotations

from swifta.domain.control_flow import (
    ActionFlowStep,
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
    SwitchCaseFlow,
    SwitchFlowStep,
    WaitConditionFlowStep,
    WhileFlowStep,
)
from swifta.infrastructure.rendering.nassi_html_renderer import (
    HtmlNassiDiagramRenderer,
)


def _render_steps(
    *steps: ControlFlowStep, name: str = "test_func", signature: str = "func test()"
) -> str:
    diagram = ControlFlowDiagram(
        source_location="test.v",
        functions=(
            FunctionControlFlow(
                name=name,
                signature=signature,
                container=None,
                steps=steps,
            ),
        ),
    )
    return HtmlNassiDiagramRenderer().render(diagram)


def _render_empty() -> str:
    diagram = ControlFlowDiagram(source_location="empty.v", functions=())
    return HtmlNassiDiagramRenderer().render(diagram)


# ── Boilerplate ──


class TestNassiHtmlBoilerplate:
    def test_html_structure(self) -> None:
        html = _render_steps(ActionFlowStep("x <= 1"))
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert 'charset="utf-8"' in html

    def test_contains_source_location(self) -> None:
        html = _render_steps(ActionFlowStep("x <= 1"))
        assert "test.v" in html

    def test_empty_diagram_message(self) -> None:
        html = _render_empty()
        assert "No functions found" in html

    def test_function_panel_with_name_and_signature(self) -> None:
        html = _render_steps(
            ActionFlowStep("x <= 1"), name="my_block", signature="always @(posedge clk)"
        )
        assert "my_block" in html
        assert "always @(posedge clk)" in html


# ── Action ──


class TestNassiHtmlAction:
    def test_action_label_escaped(self) -> None:
        html = _render_steps(ActionFlowStep("result <= data_in"))
        assert "result &lt;= data_in" in html
        assert "ns-action" in html

    def test_html_entities_escaped(self) -> None:
        html = _render_steps(ActionFlowStep("a < b && c > d"))
        assert "a &lt; b &amp;&amp; c &gt; d" in html


# ── If/Else ──


class TestNassiHtmlIf:
    def test_if_only_has_yes_branch(self) -> None:
        html = _render_steps(
            IfFlowStep(condition="rst", then_steps=(ActionFlowStep("x <= 0"),), else_steps=())
        )
        assert "Yes" in html
        assert "No branch continues" in html

    def test_if_else_has_both_branches(self) -> None:
        html = _render_steps(
            IfFlowStep(
                condition="en",
                then_steps=(ActionFlowStep("x <= 1"),),
                else_steps=(ActionFlowStep("x <= 0"),),
            )
        )
        assert "Yes" in html
        assert "No" in html
        assert "x &lt;= 1" in html
        assert "x &lt;= 0" in html

    def test_nested_if_renders(self) -> None:
        html = _render_steps(
            IfFlowStep(
                condition="a",
                then_steps=(
                    IfFlowStep(
                        condition="b", then_steps=(ActionFlowStep("z <= 1"),), else_steps=()
                    ),
                ),
                else_steps=(),
            )
        )
        assert html.count("Yes") == 2

    def test_if_condition_escaped(self) -> None:
        html = _render_steps(IfFlowStep(condition="a > b", then_steps=(), else_steps=()))
        assert "a &gt; b" in html


# ── Loops ──


class TestNassiHtmlWhile:
    def test_while_header_and_body(self) -> None:
        html = _render_steps(
            WhileFlowStep(condition="ready == 0", body_steps=(ActionFlowStep("x <= x + 1"),))
        )
        assert "While ready == 0" in html
        assert "x &lt;= x + 1" in html
        assert "ns-loop" in html


class TestNassiHtmlFor:
    def test_for_header_and_body(self) -> None:
        html = _render_steps(
            ForInFlowStep(header="i = 0; i < 8; i = i + 1", body_steps=(ActionFlowStep("x <= i"),))
        )
        assert "For i = 0; i &lt; 8; i = i + 1" in html
        assert "x &lt;= i" in html


class TestNassiHtmlRepeat:
    def test_repeat_has_header_and_footer(self) -> None:
        html = _render_steps(
            RepeatWhileFlowStep(
                condition="count > 0", body_steps=(ActionFlowStep("count <= count - 1"),)
            )
        )
        assert "Repeat" in html
        assert "While count &gt; 0" in html
        assert "ns-repeat" in html


class TestNassiHtmlForever:
    def test_forever_renders(self) -> None:
        html = _render_steps(ForeverFlowStep(body_steps=(ActionFlowStep("x <= x + 1"),)))
        assert "Forever" in html
        assert "x &lt;= x + 1" in html
        assert "ns-loop" in html


# ── Disable ──


class TestNassiHtmlDisable:
    def test_disable_renders_target(self) -> None:
        html = _render_steps(DisableFlowStep(target="forever"))
        assert "disable forever" in html
        assert "ns-action" in html


# ── Switch/Case ──


class TestNassiHtmlSwitch:
    def test_switch_grid(self) -> None:
        html = _render_steps(
            SwitchFlowStep(
                expression="opcode",
                cases=(
                    SwitchCaseFlow(label="4'h0", steps=(ActionFlowStep("result <= data"),)),
                    SwitchCaseFlow(label="4'h1", steps=(ActionFlowStep("result <= acc"),)),
                    SwitchCaseFlow(label="default", steps=(ActionFlowStep("result <= 0"),)),
                ),
            )
        )
        assert "switch opcode" in html
        assert "4&#x27;h0" in html
        assert "4&#x27;h1" in html
        assert "default" in html
        assert "ns-switch" in html

    def test_switch_no_cases(self) -> None:
        html = _render_steps(SwitchFlowStep(expression="x", cases=()))
        assert "No cases" in html

    def test_case_label_escaping(self) -> None:
        html = _render_steps(
            SwitchFlowStep(
                expression="data",
                cases=(SwitchCaseFlow(label="8'b1???_????", steps=(ActionFlowStep("x <= 1"),)),),
            )
        )
        assert "switch data" in html


# ── Fork/Join ──


class TestNassiHtmlFork:
    def test_fork_join_renders(self) -> None:
        html = _render_steps(
            ForkJoinFlowStep(
                join_type="join",
                body_steps=(ActionFlowStep("a <= 1"), ActionFlowStep("b <= 2")),
            )
        )
        assert "Fork" in html
        assert "join" in html
        assert "a &lt;= 1" in html
        assert "ns-fork" in html

    def test_fork_join_any_renders(self) -> None:
        html = _render_steps(ForkJoinFlowStep(join_type="join_any", body_steps=()))
        assert "Fork" in html
        assert "join_any" in html


# ── Delay ──


class TestNassiHtmlDelay:
    def test_delay_renders(self) -> None:
        html = _render_steps(DelayFlowStep(delay="10", body_steps=(ActionFlowStep("x <= 1"),)))
        assert "#10" in html
        assert "x &lt;= 1" in html
        assert "ns-delay" in html


# ── Event Wait ──


class TestNassiHtmlEventWait:
    def test_event_wait_renders(self) -> None:
        html = _render_steps(
            EventWaitFlowStep(event="posedge clk", body_steps=(ActionFlowStep("x <= data"),))
        )
        assert "@ posedge clk" in html
        assert "x &lt;= data" in html
        assert "ns-event" in html


# ── Wait Condition ──


class TestNassiHtmlWaitCondition:
    def test_wait_condition_renders(self) -> None:
        html = _render_steps(
            WaitConditionFlowStep(condition="ready == 1", body_steps=(ActionFlowStep("x <= data"),))
        )
        assert "Wait ready == 1" in html
        assert "x &lt;= data" in html
        assert "ns-wait" in html


# ── Do/Catch ──


class TestNassiHtmlDoCatch:
    def test_do_catch_renders(self) -> None:
        html = _render_steps(
            DoCatchFlowStep(
                body_steps=(ActionFlowStep("work()"),),
                catches=(),
            )
        )
        assert "Do" in html
        assert "ns-do-catch" in html


# ── Defer ──


class TestNassiHtmlDefer:
    def test_defer_renders(self) -> None:
        html = _render_steps(DeferFlowStep(body_steps=(ActionFlowStep("cleanup()"),)))
        assert "Defer" in html
        assert "ns-defer" in html


# ── Unsupported type ──


class TestNassiHtmlUnsupported:
    def test_unsupported_step_raises(self) -> None:
        from dataclasses import dataclass
        from swifta.domain.control_flow import ControlFlowStep

        @dataclass(frozen=True)
        class FakeStep(ControlFlowStep):
            pass

        import pytest

        with pytest.raises(TypeError, match="unsupported step type"):
            _render_steps(FakeStep())


# ── Sensitivity badge ──


class TestNassiHtmlSensitivityBadge:
    def test_always_with_sensitivity_shows_badge(self) -> None:
        diagram = ControlFlowDiagram(
            source_location="test.v",
            functions=(
                FunctionControlFlow(
                    name="always_1",
                    signature="always @(posedge clk)",
                    container=None,
                    steps=(ActionFlowStep("x <= 1"),),
                    sensitivity="posedge clk",
                ),
            ),
        )
        html = HtmlNassiDiagramRenderer().render(diagram)
        assert "sensitivity-badge" in html
        assert "posedge clk" in html
        assert "kind-badge" in html

    def test_initial_no_sensitivity_no_badge(self) -> None:
        diagram = ControlFlowDiagram(
            source_location="test.v",
            functions=(
                FunctionControlFlow(
                    name="initial_1",
                    signature="initial",
                    container=None,
                    steps=(ActionFlowStep("x <= 0"),),
                    sensitivity=None,
                ),
            ),
        )
        html = HtmlNassiDiagramRenderer().render(diagram)
        # Extract just the function panel section (after </style>)
        panel_start = html.index('<section class="function-panel">')
        panel_end = html.index("</section>", panel_start) + len("</section>")
        panel_html = html[panel_start:panel_end]
        assert "function-meta" in panel_html
        assert "sensitivity-badge" not in panel_html
        assert "@(" not in panel_html

    def test_function_shows_kind_badge(self) -> None:
        diagram = ControlFlowDiagram(
            source_location="test.v",
            functions=(
                FunctionControlFlow(
                    name="adder",
                    signature="function [7:0] adder",
                    container=None,
                    steps=(ActionFlowStep("adder = a + b"),),
                    sensitivity=None,
                ),
            ),
        )
        html = HtmlNassiDiagramRenderer().render(diagram)
        assert "kind-badge" in html
        assert "function" in html
        assert "adder" in html


class TestTopLevelPanel:
    def test_top_level_panel_appears_before_functions(self):
        diagram = ControlFlowDiagram(
            source_location="top.v",
            functions=(
                FunctionControlFlow(
                    name="always_1",
                    signature="always @(posedge clk)",
                    container=None,
                    steps=(ActionFlowStep("x <= 1"),),
                ),
            ),
            top_level_steps=(ActionFlowStep("assign a = b"), ActionFlowStep("assign c = d")),
        )
        html = HtmlNassiDiagramRenderer().render(diagram)
        module_panel_idx = html.find("Module")
        always_panel_idx = html.find("always_1")
        assert module_panel_idx < always_panel_idx
        assert "Module" in html
        assert "continuous assignments" in html
        assert "MODULE" in html
        assert "assign a = b" in html
        assert "assign c = d" in html

    def test_top_level_panel_escapes_html(self):
        diagram = ControlFlowDiagram(
            source_location="top.v",
            functions=(),
            top_level_steps=(ActionFlowStep("a < b && c > d"),),
        )
        html = HtmlNassiDiagramRenderer().render(diagram)
        assert "a &lt; b &amp;&amp; c &gt; d" in html
        assert "Module" in html

    def test_no_top_level_panel_when_empty(self):
        diagram = ControlFlowDiagram(
            source_location="top.v",
            functions=(
                FunctionControlFlow(
                    name="always_1",
                    signature="always @(posedge clk)",
                    container=None,
                    steps=(ActionFlowStep("x <= 1"),),
                ),
            ),
            top_level_steps=(),
        )
        html = HtmlNassiDiagramRenderer().render(diagram)
        assert "Module" not in html
        assert "continuous assignments" not in html
        assert "MODULE" not in html
        assert "always_1" in html
