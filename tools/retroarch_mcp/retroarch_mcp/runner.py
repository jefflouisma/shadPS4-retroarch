from __future__ import annotations

import logging
import platform
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from .models import (
    CommandStep,
    ExitStep,
    InputStep,
    LaunchStep,
    LoadStateStep,
    OpenRouterEvaluation,
    SaveStateStep,
    ScreenshotAssertStep,
    Step,
    StepResult,
    TestDefinition,
    TestRunResult,
    WaitStep,
)
from .openrouter import OpenRouterClient
from .retroarch import RetroArchArtifacts, RetroArchController
from .utils import ensure_dir, load_env_file, setup_logging, timestamp_slug, write_json


@dataclass
class TestRunContext:
    definition: TestDefinition
    artifacts: RetroArchArtifacts
    controller: RetroArchController
    openrouter: Optional[OpenRouterClient]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_seconds(start: float, end: float) -> float:
    return round(end - start, 3)


def _build_artifacts(definition: TestDefinition) -> RetroArchArtifacts:
    output_base = (
        Path(definition.output_directory)
        if definition.output_directory
        else Path.cwd() / "retroarch-test-runs"
    )
    output_dir = ensure_dir(output_base / f"{definition.name}-{timestamp_slug()}")
    logs_dir = ensure_dir(
        Path(definition.log_directory).expanduser()
        if definition.log_directory
        else output_dir / "logs"
    )
    screenshots_dir = ensure_dir(
        Path(definition.screenshot_directory).expanduser()
        if definition.screenshot_directory
        else output_dir / "screenshots"
    )
    states_dir = ensure_dir(output_dir / "states")
    append_config_path = output_dir / "retroarch-append.cfg"
    log_path = logs_dir / "retroarch.log"

    return RetroArchArtifacts(
        output_dir=output_dir,
        logs_dir=logs_dir,
        screenshots_dir=screenshots_dir,
        states_dir=states_dir,
        append_config_path=append_config_path,
        log_path=log_path,
    )


def _write_append_config(
    artifacts: RetroArchArtifacts,
    definition: TestDefinition,
) -> None:
    lines = [
        'network_cmd_enable = "true"',
        f'screenshot_directory = "{artifacts.screenshots_dir}"',
        f'savestate_directory = "{artifacts.states_dir}"',
    ]

    force_fullscreen = any(
        isinstance(step, ScreenshotAssertStep) and step.capture_mode == "system"
        for step in definition.steps
    )
    if force_fullscreen:
        lines.append('video_fullscreen = "true"')

    artifacts.append_config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _get_macos_window_id(process_id: int, process_name: Optional[str]) -> int:
    scripts = [
        (
            "pid",
            (
                'tell application "System Events" to get the id of first window of '
                f'(first process whose unix id is {process_id})'
            ),
        ),
    ]

    if process_name:
        safe_name = process_name.replace("\"", "\\\"")
        scripts.append(
            (
                "name",
                (
                    'tell application "System Events" to get the id of first window of '
                    f'(first process whose name is "{safe_name}")'
                ),
            )
        )

    errors: List[str] = []
    for label, script in scripts:
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            errors.append(f"{label} script failed: {detail}")
            continue

        match = re.search(r"\d+", result.stdout)
        if match:
            return int(match.group(0))

        output = result.stdout.strip() or "<no output>"
        errors.append(f"{label} script returned: {output}")

    error_detail = " | ".join(errors) if errors else "No script output."
    raise RuntimeError(
        "System Events did not return a window id for RetroArch. "
        "Grant Automation permission to the host app (Terminal/IDE) in "
        "System Settings > Privacy & Security > Automation (allow control of System Events). "
        f"Details: {error_detail}"
    )


def _capture_system_screenshot(
    controller: RetroArchController,
    artifacts: RetroArchArtifacts,
    timeout_seconds: float,
) -> Path:
    screenshots_dir = ensure_dir(artifacts.screenshots_dir)
    target = screenshots_dir / f"system-{timestamp_slug()}.png"

    if platform.system() != "Darwin":
        raise RuntimeError("System screenshot capture is only supported on macOS.")

    process = controller.process
    if not process or process.poll() is not None:
        raise RuntimeError("RetroArch must be running to capture a system screenshot.")

    command = shutil.which("screencapture") or "/usr/sbin/screencapture"
    if not command:
        raise FileNotFoundError("screencapture command not found on this system.")

    deadline = time.time() + timeout_seconds
    last_error: Optional[Exception] = None
    while time.time() < deadline:
        try:
            subprocess.run(
                [command, "-x", "-t", "png", str(target)],
                check=True,
            )
            break
        except subprocess.CalledProcessError as exc:
            last_error = exc
            time.sleep(0.25)

    if not target.exists():
        raise RuntimeError(
            "System screenshot capture failed to create output file. "
            f"Last error: {last_error}"
        )

    return target


def _resolve_openrouter(env_path: Optional[str]) -> Optional[OpenRouterClient]:
    if env_path:
        load_env_file(env_path)
    else:
        default_env = Path.cwd() / ".env"
        if default_env.exists():
            load_env_file(str(default_env))

    api_key = None
    try:
        from .utils import get_env_value

        api_key = get_env_value("OPENROUTER_API_KEY")
    except Exception:
        api_key = None

    if not api_key:
        return None

    return OpenRouterClient(api_key)


class TestRunner:
    def __init__(self, *, env_path: Optional[str] = None) -> None:
        setup_logging()
        self._logger = logging.getLogger(__name__)
        self._env_path = env_path

    def run(self, definition: TestDefinition) -> TestRunResult:
        artifacts = _build_artifacts(definition)
        _write_append_config(artifacts, definition)

        append_configs = list(definition.append_config_paths)
        append_configs.append(str(artifacts.append_config_path))

        controller = RetroArchController(
            host=definition.network_host,
            port=definition.network_port,
            artifacts=artifacts,
        )

        if definition.network_port != 55355:
            self._logger.warning(
                "Network command port set to %s. Ensure RetroArch is configured to listen on this port.",
                definition.network_port,
            )

        openrouter = _resolve_openrouter(self._env_path)
        context = TestRunContext(
            definition=definition,
            artifacts=artifacts,
            controller=controller,
            openrouter=openrouter,
        )

        started_at = _now_iso()
        start_time = time.time()
        step_results: List[StepResult] = []
        passed = True

        try:
            for index, step in enumerate(definition.steps):
                result = self._run_step(index, step, context, append_configs)
                step_results.append(result)
                if result.status == "failed":
                    passed = False
                    if not definition.continue_on_failure:
                        break
        finally:
            controller.shutdown()

        finished_at = _now_iso()
        total_duration = _duration_seconds(start_time, time.time())

        test_result = TestRunResult(
            name=definition.name,
            passed=passed,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=total_duration,
            output_directory=str(artifacts.output_dir),
            logs_directory=str(artifacts.logs_dir),
            screenshots_directory=str(artifacts.screenshots_dir),
            states_directory=str(artifacts.states_dir),
            log_path=str(artifacts.log_path),
            steps=step_results,
        )

        write_json(artifacts.output_dir / "results.json", test_result.model_dump())
        return test_result

    def _run_step(
        self,
        index: int,
        step: Step,
        context: TestRunContext,
        append_configs: List[str],
    ) -> StepResult:
        start_time = time.time()
        started_at = _now_iso()
        status = "passed"
        message = None
        error = None
        screenshot_path = None
        openrouter_eval: Optional[OpenRouterEvaluation] = None

        try:
            if isinstance(step, LaunchStep):
                context.controller.launch(
                    core_path=step.core_path or context.definition.core_path,
                    content_path=step.content_path or context.definition.content_path,
                    config_path=step.config_path or context.definition.config_path,
                    append_config_paths=append_configs,
                    retroarch_path=step.retroarch_path or context.definition.retroarch_path,
                    menu=step.menu,
                    verbose=step.verbose,
                    extra_args=step.extra_args,
                )
                time.sleep(step.startup_wait_seconds)
                message = "RetroArch launched"

            elif isinstance(step, WaitStep):
                time.sleep(step.seconds)
                message = f"Waited {step.seconds} seconds"

            elif isinstance(step, CommandStep):
                context.controller.send_command(step.command)
                message = f"Sent command {step.command}"

            elif isinstance(step, InputStep):
                for _ in range(step.repeat):
                    context.controller.send_command(step.command)
                    if step.delay_seconds > 0:
                        time.sleep(step.delay_seconds)
                message = f"Sent {step.command} x{step.repeat}"

            elif isinstance(step, SaveStateStep):
                if step.slot is not None:
                    context.controller.set_state_slot(step.slot)
                context.controller.send_command("SAVE_STATE")
                message = "Save state command issued"

            elif isinstance(step, LoadStateStep):
                if step.slot is not None:
                    context.controller.set_state_slot(step.slot)
                context.controller.send_command("LOAD_STATE")
                message = "Load state command issued"

            elif isinstance(step, ScreenshotAssertStep):
                if step.capture_mode == "system":
                    screenshot = _capture_system_screenshot(
                        context.controller,
                        context.artifacts,
                        step.timeout_seconds,
                    )
                else:
                    screenshot = context.controller.capture_screenshot(step.timeout_seconds)
                screenshot_path = str(screenshot)
                if not context.openrouter:
                    status = "failed"
                    error = "OPENROUTER_API_KEY not configured"
                else:
                    prompt = (
                        "You are a strict visual QA assistant. "
                        "Return a JSON object ONLY with keys 'pass' (boolean) and 'reason' (string). "
                        f"Criteria: {step.prompt}"
                    )
                    result = context.openrouter.validate_image(
                        prompt=prompt,
                        image_path=screenshot,
                        model=step.model,
                    )
                    openrouter_eval = OpenRouterEvaluation(
                        passed=result.passed,
                        reason=result.reason,
                        raw_content=result.raw_content,
                        parsed_json=result.parsed_json,
                    )
                    if not result.passed:
                        status = "failed"
                        error = result.reason

            elif isinstance(step, ExitStep):
                context.controller.shutdown()
                message = "RetroArch shutdown requested"

        except Exception as exc:
            status = "failed"
            error = str(exc)

        finished_at = _now_iso()
        duration = _duration_seconds(start_time, time.time())

        return StepResult(
            index=index,
            type=step.type,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
            message=message,
            error=error,
            screenshot_path=screenshot_path,
            openrouter=openrouter_eval,
        )
