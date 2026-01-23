from __future__ import annotations

from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class LaunchStep(BaseModel):
    type: Literal["launch"] = "launch"
    core_path: Optional[str] = None
    content_path: Optional[str] = None
    config_path: Optional[str] = None
    append_config_paths: List[str] = Field(default_factory=list)
    retroarch_path: Optional[str] = None
    menu: Optional[bool] = None
    verbose: bool = False
    extra_args: List[str] = Field(default_factory=list)
    startup_wait_seconds: float = 2.0


class WaitStep(BaseModel):
    type: Literal["wait"] = "wait"
    seconds: float


class CommandStep(BaseModel):
    type: Literal["command"] = "command"
    command: str


class InputStep(BaseModel):
    type: Literal["input"] = "input"
    command: str
    repeat: int = 1
    delay_seconds: float = 0.0


class ScreenshotAssertStep(BaseModel):
    type: Literal["screenshot_assert"] = "screenshot_assert"
    prompt: str
    model: Optional[str] = None
    timeout_seconds: float = 10.0
    capture_mode: Literal["retroarch", "system"] = "retroarch"


class SaveStateStep(BaseModel):
    type: Literal["save_state"] = "save_state"
    slot: Optional[int] = None


class LoadStateStep(BaseModel):
    type: Literal["load_state"] = "load_state"
    slot: Optional[int] = None


class ExitStep(BaseModel):
    type: Literal["exit"] = "exit"


Step = Annotated[
    Union[
        LaunchStep,
        WaitStep,
        CommandStep,
        InputStep,
        ScreenshotAssertStep,
        SaveStateStep,
        LoadStateStep,
        ExitStep,
    ],
    Field(discriminator="type"),
]


class TestDefinition(BaseModel):
    name: str = "retroarch-test"
    core_path: Optional[str] = None
    content_path: Optional[str] = None
    config_path: Optional[str] = None
    append_config_paths: List[str] = Field(default_factory=list)
    retroarch_path: Optional[str] = None
    network_host: str = "127.0.0.1"
    network_port: int = 55355
    output_directory: Optional[str] = None
    screenshot_directory: Optional[str] = None
    log_directory: Optional[str] = None
    continue_on_failure: bool = False
    steps: List[Step]


class OpenRouterEvaluation(BaseModel):
    passed: bool
    reason: str
    raw_content: str
    parsed_json: Optional[dict] = None


class StepResult(BaseModel):
    index: int
    type: str
    status: Literal["passed", "failed", "skipped"]
    started_at: str
    finished_at: str
    duration_seconds: float
    message: Optional[str] = None
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
    openrouter: Optional[OpenRouterEvaluation] = None


class TestRunResult(BaseModel):
    name: str
    passed: bool
    started_at: str
    finished_at: str
    duration_seconds: float
    output_directory: str
    logs_directory: str
    screenshots_directory: str
    states_directory: str
    log_path: str
    steps: List[StepResult]
