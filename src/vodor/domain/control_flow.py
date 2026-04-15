"""Domain model for structured control flow diagrams."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionKind(Enum):
    ASSIGNMENT_BLOCKING = "assignment_blocking"
    ASSIGNMENT_NONBLOCKING = "assignment_nonblocking"
    SYSTEM_TASK = "system_task"
    TASK_CALL = "task_call"
    EVENT_TRIGGER = "event_trigger"
    PROCEDURAL_CONTINUOUS = "procedural_continuous"
    CONTINUOUS_ASSIGN = "continuous_assign"
    OTHER = "other"


class SmellSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class SmellKind(Enum):
    BLOCKING_IN_SEQUENTIAL = "blocking_in_sequential"
    NONBLOCKING_IN_COMBINATIONAL = "nonblocking_in_combinational"
    LATCH_RISK_INCOMPLETE_IF = "latch_risk_incomplete_if"
    CASE_MISSING_DEFAULT = "case_missing_default"
    CASEX_USAGE = "casex_usage"


@dataclass(frozen=True, slots=True)
class ControlFlowStep:
    """Base type for a structured control flow step."""


@dataclass(frozen=True, slots=True)
class ActionFlowStep(ControlFlowStep):
    label: str
    action_kind: ActionKind = ActionKind.OTHER


@dataclass(frozen=True, slots=True)
class IfFlowStep(ControlFlowStep):
    condition: str
    then_steps: tuple[ControlFlowStep, ...]
    else_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class GuardFlowStep(ControlFlowStep):
    condition: str
    else_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class WhileFlowStep(ControlFlowStep):
    condition: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class ForInFlowStep(ControlFlowStep):
    header: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class RepeatWhileFlowStep(ControlFlowStep):
    condition: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class SwitchCaseFlow:
    label: str
    steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class SwitchFlowStep(ControlFlowStep):
    expression: str
    cases: tuple[SwitchCaseFlow, ...]
    case_keyword: str = "case"


@dataclass(frozen=True, slots=True)
class CatchClauseFlow:
    pattern: str
    steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class DoCatchFlowStep(ControlFlowStep):
    body_steps: tuple[ControlFlowStep, ...]
    catches: tuple[CatchClauseFlow, ...]


@dataclass(frozen=True, slots=True)
class DeferFlowStep(ControlFlowStep):
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class ForeverFlowStep(ControlFlowStep):
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class DisableFlowStep(ControlFlowStep):
    target: str


@dataclass(frozen=True, slots=True)
class ForkJoinFlowStep(ControlFlowStep):
    join_type: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class DelayFlowStep(ControlFlowStep):
    delay: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class EventWaitFlowStep(ControlFlowStep):
    event: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class WaitConditionFlowStep(ControlFlowStep):
    condition: str
    body_steps: tuple[ControlFlowStep, ...]


@dataclass(frozen=True, slots=True)
class StructDeclarationFlowStep(ControlFlowStep):
    name: str
    fields: tuple[tuple[str, str], ...]  # (field_name, field_type)


@dataclass(frozen=True, slots=True)
class StructFieldAccessFlowStep(ControlFlowStep):
    struct_name: str
    field_name: str
    is_write: bool


@dataclass(frozen=True, slots=True)
class FunctionControlFlow:
    name: str
    signature: str
    container: str | None
    steps: tuple[ControlFlowStep, ...]
    sensitivity: str | None = None

    @property
    def qualified_name(self) -> str:
        if self.container:
            return f"{self.container}.{self.name}"
        return self.name


@dataclass(frozen=True, slots=True)
class PortDeclaration:
    direction: str  # "input", "output", "inout"
    kind: str  # "wire", "reg", ""
    name: str
    width: str | None  # "[7:0]"


@dataclass(frozen=True, slots=True)
class Declaration:
    kind: str  # "wire", "reg", "integer", "parameter", "localparam"
    name: str
    width: str | None
    value: str | None


@dataclass(frozen=True, slots=True)
class PortConnection:
    port_name: str
    signal: str


@dataclass(frozen=True, slots=True)
class ModuleInstantiation:
    module_name: str
    instance_name: str
    connections: tuple[PortConnection, ...]


@dataclass(frozen=True, slots=True)
class GenerateBlock:
    label: str | None
    kind: str  # "for" or "if"
    condition: str


@dataclass(frozen=True, slots=True)
class ModuleStructure:
    name: str
    ports: tuple[PortDeclaration, ...]
    declarations: tuple[Declaration, ...]
    instantiations: tuple[ModuleInstantiation, ...]
    generate_blocks: tuple[GenerateBlock, ...]


@dataclass(frozen=True, slots=True)
class ControlFlowDiagram:
    source_location: str
    functions: tuple[FunctionControlFlow, ...]
    top_level_steps: tuple[ControlFlowStep, ...] = ()
    module_structure: ModuleStructure | None = None


@dataclass(frozen=True, slots=True)
class SmellLocation:
    block_name: str
    step_label: str


@dataclass(frozen=True, slots=True)
class Smell:
    kind: SmellKind
    severity: SmellSeverity
    message: str
    location: SmellLocation


@dataclass(frozen=True, slots=True)
class SmellReport:
    source_location: str
    smells: tuple[Smell, ...]
