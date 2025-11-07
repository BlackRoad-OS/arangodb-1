"""Timeout handling for test execution with extensible diagnostic collection."""

import subprocess
import threading
import time
from enum import Enum
from typing import Optional, Callable
from rich.console import Console
from ..core.log import get_logger


logger = get_logger(__name__)


class TimeoutType(Enum):
    """Type of timeout that was triggered."""

    GLOBAL = "global"
    OUTPUT_IDLE = "output_idle"


class TimeoutHandler:
    """Centralized timeout monitoring with hooks for diagnostic collection.

    This class provides a clean abstraction for timeout enforcement with
    extension points for collecting diagnostics (logs, coredumps, etc.) when
    timeouts are triggered.

    Future extensions can:
    - Add pre_terminate_hook for diagnostic collection before killing process
    - Add post_terminate_hook for cleanup after process termination
    - Collect server logs, coredumps, process states, etc.
    """

    def __init__(
        self,
        process: subprocess.Popen,
        console: Console,
        global_timeout: Optional[float] = None,
        output_idle_timeout: Optional[float] = None,
    ):
        """Initialize timeout handler.

        Args:
            process: The subprocess to monitor
            console: Rich console for user messages
            global_timeout: Global session timeout in seconds (None = disabled)
            output_idle_timeout: Output idle timeout in seconds (None = disabled)
        """
        self.process = process
        self.console = console
        self.global_timeout = global_timeout
        self.output_idle_timeout = output_idle_timeout

        # State tracking
        self.start_time = time.monotonic()
        self.last_output_time = time.monotonic()
        self.timeout_triggered = False
        self.timeout_type: Optional[TimeoutType] = None
        self.monitor_active = True

        # Extension hooks (placeholder for future diagnostic collection)
        self.pre_terminate_hook: Optional[Callable[[TimeoutType, float], None]] = None
        self.post_terminate_hook: Optional[Callable[[TimeoutType], None]] = None

    def update_output_timestamp(self) -> None:
        """Update the last output timestamp (called when output is received)."""
        self.last_output_time = time.monotonic()

    def _terminate_process(self, timeout_type: TimeoutType, elapsed: float) -> None:
        """Terminate the process with escalating signals.

        Args:
            timeout_type: Type of timeout that was triggered
            elapsed: Elapsed time when timeout was triggered
        """
        self.timeout_triggered = True
        self.timeout_type = timeout_type

        # Future extension point: Call pre-termination hook for diagnostic collection
        # This is where we would:
        # - Collect server logs
        # - Capture process states
        # - Trigger coredump collection
        # - Save test artifacts
        if self.pre_terminate_hook:
            try:
                self.pre_terminate_hook(timeout_type, elapsed)
            except Exception as e:
                logger.error(f"Error in pre-termination hook: {e}")

        # Escalating termination: SIGTERM -> 5s wait -> SIGKILL
        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
                logger.info("Process terminated gracefully after SIGTERM")
            except subprocess.TimeoutExpired:
                logger.warning("Process did not respond to SIGTERM, sending SIGKILL")
                self.console.print("[red]Sending SIGKILL...[/red]")
                self.process.kill()
                self.process.wait()
                logger.info("Process killed with SIGKILL")
        except ProcessLookupError:
            pass

        # Future extension point: Call post-termination hook for cleanup
        if self.post_terminate_hook:
            try:
                self.post_terminate_hook(timeout_type)
            except Exception as e:
                logger.error(f"Error in post-termination hook: {e}")

    def _global_timeout_monitor(self) -> None:
        """Monitor for global session timeout."""
        while self.monitor_active and self.process.poll() is None:
            time.sleep(1.0)
            elapsed = time.monotonic() - self.start_time

            if self.global_timeout and elapsed > self.global_timeout:
                logger.warning(
                    f"Global timeout ({self.global_timeout}s) exceeded. "
                    f"Elapsed: {elapsed:.1f}s. Terminating pytest..."
                )
                self.console.print(
                    f"\n[red]⏱️  Global timeout: test session exceeded {self.global_timeout}s "
                    f"(elapsed: {elapsed:.1f}s)[/red]"
                )
                self.console.print("[yellow]Sending SIGTERM to pytest...[/yellow]")

                self._terminate_process(TimeoutType.GLOBAL, elapsed)
                break

    def _output_idle_monitor(self) -> None:
        """Monitor for output idle timeout."""
        while self.monitor_active and self.process.poll() is None:
            time.sleep(1.0)
            idle_duration = time.monotonic() - self.last_output_time

            if self.output_idle_timeout and idle_duration > self.output_idle_timeout:
                logger.warning(
                    f"Output idle timeout ({self.output_idle_timeout}s) exceeded. "
                    f"No output for {idle_duration:.1f}s. Terminating pytest..."
                )
                self.console.print(
                    f"\n[red]⏱️  Output idle timeout: no output for {idle_duration:.1f}s "
                    f"(threshold: {self.output_idle_timeout}s)[/red]"
                )
                self.console.print("[yellow]Sending SIGTERM to pytest...[/yellow]")

                self._terminate_process(TimeoutType.OUTPUT_IDLE, idle_duration)
                break

    def start_monitoring(self) -> None:
        """Start timeout monitoring threads."""
        # Always start global timeout monitor (it checks if timeout is set)
        global_monitor = threading.Thread(
            target=self._global_timeout_monitor, daemon=True
        )
        global_monitor.start()

        # Start output idle monitor if enabled
        if self.output_idle_timeout:
            idle_monitor = threading.Thread(
                target=self._output_idle_monitor, daemon=True
            )
            idle_monitor.start()

    def stop_monitoring(self) -> None:
        """Stop timeout monitoring."""
        self.monitor_active = False

    def was_timeout_triggered(self) -> bool:
        """Check if any timeout was triggered."""
        return self.timeout_triggered

    def get_timeout_type(self) -> Optional[TimeoutType]:
        """Get the type of timeout that was triggered (if any)."""
        return self.timeout_type

    def set_pre_terminate_hook(
        self, hook: Callable[[TimeoutType, float], None]
    ) -> None:
        """Set hook to run before process termination.

        The hook receives the timeout type and elapsed time, and can be used
        to collect diagnostics before the process is killed.

        Args:
            hook: Callable that takes (timeout_type, elapsed_time)
        """
        self.pre_terminate_hook = hook

    def set_post_terminate_hook(self, hook: Callable[[TimeoutType], None]) -> None:
        """Set hook to run after process termination.

        The hook receives the timeout type and can be used for cleanup.

        Args:
            hook: Callable that takes (timeout_type)
        """
        self.post_terminate_hook = hook
