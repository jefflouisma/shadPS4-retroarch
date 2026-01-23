from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from .utils import ensure_dir


@dataclass
class RetroArchArtifacts:
    output_dir: Path
    logs_dir: Path
    screenshots_dir: Path
    states_dir: Path
    append_config_path: Path
    log_path: Path


class RetroArchController:
    def __init__(
        self,
        host: str,
        port: int,
        artifacts: RetroArchArtifacts,
    ) -> None:
        self._host = host
        self._port = port
        self._artifacts = artifacts
        self._process: Optional[subprocess.Popen[str]] = None
        self._log_handle: Optional[object] = None
        self._state_slot = 0
        self._logger = logging.getLogger(__name__)

    @property
    def process(self) -> Optional[subprocess.Popen[str]]:
        return self._process

    def resolve_retroarch_path(self, override: Optional[str]) -> str:
        if override:
            return override

        env_override = os.environ.get("RETROARCH_PATH")
        if env_override:
            return env_override

        binary = shutil.which("retroarch")
        if binary:
            return binary

        mac_bundle = Path("/Applications/RetroArch.app/Contents/MacOS/RetroArch")
        if mac_bundle.exists():
            return str(mac_bundle)

        raise FileNotFoundError(
            "RetroArch executable not found. Provide retroarch_path or set RETROARCH_PATH."
        )

    def build_command(
        self,
        retroarch_path: str,
        core_path: Optional[str],
        content_path: Optional[str],
        config_path: Optional[str],
        append_config_paths: Iterable[str],
        menu: Optional[bool],
        verbose: bool,
        extra_args: Iterable[str],
    ) -> List[str]:
        command: List[str] = [retroarch_path]

        if verbose:
            command.append("--verbose")

        if config_path:
            command.extend(["--config", config_path])

        for append_path in append_config_paths:
            command.extend(["--appendconfig", append_path])

        if core_path:
            command.extend(["-L", core_path])

        if menu is True or (menu is None and not content_path):
            command.append("--menu")

        command.extend(list(extra_args))

        if content_path:
            command.append(content_path)

        return command

    def launch(
        self,
        *,
        core_path: Optional[str],
        content_path: Optional[str],
        config_path: Optional[str],
        append_config_paths: List[str],
        retroarch_path: Optional[str],
        menu: Optional[bool],
        verbose: bool,
        extra_args: List[str],
    ) -> subprocess.Popen[str]:
        if self._process and self._process.poll() is None:
            raise RuntimeError("RetroArch is already running.")

        resolved_path = self.resolve_retroarch_path(retroarch_path)
        command = self.build_command(
            resolved_path,
            core_path,
            content_path,
            config_path,
            append_config_paths,
            menu,
            verbose,
            extra_args,
        )

        self._logger.info("Launching RetroArch: %s", " ".join(command))

        if self._log_handle:
            try:
                self._log_handle.close()
            except Exception:
                pass

        log_file = self._artifacts.log_path.open("w", encoding="utf-8")
        self._log_handle = log_file
        process = subprocess.Popen(
            command,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            close_fds=True,
        )
        self._process = process
        return process

    def send_command(self, command: str) -> None:
        payload = command.encode("utf-8")
        self._logger.info("Sending command '%s' to %s:%s", command, self._host, self._port)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(payload, (self._host, self._port))

    def set_state_slot(self, slot: int) -> None:
        if slot < 0:
            raise ValueError("State slot must be non-negative.")

        while self._state_slot < slot:
            self.send_command("STATE_SLOT_PLUS")
            self._state_slot += 1

        while self._state_slot > slot:
            self.send_command("STATE_SLOT_MINUS")
            self._state_slot -= 1

    def capture_screenshot(self, timeout_seconds: float) -> Path:
        screenshots_dir = ensure_dir(self._artifacts.screenshots_dir)
        start_time = time.time()
        before = {path.name: path.stat().st_mtime for path in screenshots_dir.glob("*.*")}

        self.send_command("SCREENSHOT")

        deadline = start_time + timeout_seconds
        while time.time() < deadline:
            for path in screenshots_dir.glob("*.*"):
                if not path.is_file():
                    continue
                previous_mtime = before.get(path.name)
                if previous_mtime is None or path.stat().st_mtime > start_time:
                    self._logger.info("Captured screenshot: %s", path)
                    return path
            time.sleep(0.25)

        raise TimeoutError("Timed out waiting for RetroArch screenshot output.")

    def shutdown(self, timeout_seconds: float = 8.0) -> None:
        if not self._process:
            return

        if self._process.poll() is not None:
            return

        try:
            self.send_command("QUIT")
        except Exception as exc:  # pragma: no cover - best effort
            self._logger.warning("Failed to send QUIT command: %s", exc)

        try:
            self._process.wait(timeout=timeout_seconds)
            return
        except subprocess.TimeoutExpired:
            self._logger.warning("RetroArch did not exit, terminating process.")

        self._process.terminate()
        try:
            self._process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            self._logger.error("RetroArch did not terminate; killing process.")
            self._process.kill()
            self._process.wait(timeout=timeout_seconds)

        if self._log_handle:
            try:
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None
