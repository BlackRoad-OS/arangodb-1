"""Process execution and supervision with timeout enforcement and crash detection."""

import os
import signal
import subprocess
import threading
import time
import psutil
from typing import Optional, Dict, List, Any, Callable, IO, Union
from dataclasses import dataclass
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from .errors import (
    ProcessError, ProcessStartupError, ProcessTimeoutError,
    ProcessCrashError, TimeoutError as ArmadilloTimeoutError
)
from .time import clamp_timeout, timeout_scope
from .log import get_logger, log_process_event
from .types import ProcessStats

logger = get_logger(__name__)


@dataclass
class ProcessResult:
    """Result of process execution."""
    returncode: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False
    killed: bool = False


@dataclass
class ProcessInfo:
    """Information about a running process."""
    pid: int
    command: List[str]
    start_time: float
    working_dir: Path
    env: Dict[str, str]


class ProcessExecutor:
    """Executes one-shot commands with timeout enforcement."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(thread_name_prefix="ProcessExecutor")

    def run(self,
            command: List[str],
            cwd: Optional[Path] = None,
            env: Optional[Dict[str, str]] = None,
            timeout: Optional[float] = None,
            input_data: Optional[str] = None,
            capture_output: bool = True) -> ProcessResult:
        """Execute a command with timeout enforcement."""

        # Clamp timeout to current scope
        effective_timeout = clamp_timeout(timeout, f"process:{command[0]}")

        start_time = time.time()
        log_process_event(logger, "exec.start", command=command, timeout=effective_timeout)

        try:
            with timeout_scope(effective_timeout, f"process_exec_{command[0]}"):
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.PIPE if input_data else None,
                    stdout=subprocess.PIPE if capture_output else None,
                    stderr=subprocess.PIPE if capture_output else None,
                    text=True
                )

                try:
                    stdout, stderr = process.communicate(
                        input=input_data,
                        timeout=effective_timeout
                    )
                    duration = time.time() - start_time

                    result = ProcessResult(
                        returncode=process.returncode,
                        stdout=stdout or "",
                        stderr=stderr or "",
                        duration=duration
                    )

                    if process.returncode == 0:
                        log_process_event(logger, "exec.ok", duration=duration)
                    else:
                        log_process_event(logger, "exec.failed",
                                        return_code=process.returncode,
                                        duration=duration)

                    return result

                except subprocess.TimeoutExpired:
                    duration = time.time() - start_time
                    log_process_event(logger, "exec.timeout", duration=duration)

                    # Kill the process
                    process.kill()
                    stdout, stderr = process.communicate()

                    raise ProcessTimeoutError(
                        f"Command {command[0]} timed out after {effective_timeout}s",
                        timeout=effective_timeout,
                        details={'command': command, 'duration': duration}
                    )

        except ArmadilloTimeoutError as e:
            duration = time.time() - start_time
            raise ProcessTimeoutError(
                f"Command {command[0]} exceeded deadline",
                timeout=effective_timeout,
                details={'command': command, 'duration': duration}
            ) from e

        except Exception as e:
            duration = time.time() - start_time
            log_process_event(logger, "exec.error", duration=duration, error=str(e))
            raise ProcessError(f"Failed to execute command {command[0]}: {e}") from e


class ProcessSupervisor:
    """Manages long-running processes with health monitoring and crash detection."""

    def __init__(self) -> None:
        self._processes: Dict[str, subprocess.Popen] = {}
        self._process_info: Dict[str, ProcessInfo] = {}
        self._monitoring_threads: Dict[str, threading.Thread] = {}
        self._stop_monitoring = threading.Event()

    def start(self,
             process_id: str,
             command: List[str],
             cwd: Optional[Path] = None,
             env: Optional[Dict[str, str]] = None,
             startup_timeout: float = 30.0,
             readiness_check: Optional[Callable[[], bool]] = None) -> ProcessInfo:
        """Start a supervised process."""

        if process_id in self._processes:
            raise ProcessStartupError(f"Process {process_id} is already running")

        effective_timeout = clamp_timeout(startup_timeout, f"startup_{process_id}")

        log_process_event(logger, "supervisor.start", process_id=process_id,
                         command=command)

        try:
            # Start the process
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Store process information
            process_info = ProcessInfo(
                pid=process.pid,
                command=command,
                start_time=time.time(),
                working_dir=cwd or Path.cwd(),
                env=env or {}
            )

            self._processes[process_id] = process
            self._process_info[process_id] = process_info

            log_process_event(logger, "supervisor.started",
                            process_id=process_id, pid=process.pid)

            # Wait for readiness if check provided
            if readiness_check:
                self._wait_for_readiness(process_id, readiness_check, effective_timeout)

            # Start monitoring thread
            self._start_monitoring(process_id)

            return process_info

        except Exception as e:
            log_process_event(logger, "supervisor.start_failed",
                            process_id=process_id, error=str(e))
            self._cleanup_process(process_id)
            raise ProcessStartupError(f"Failed to start process {process_id}: {e}") from e

    def stop(self,
             process_id: str,
             graceful: bool = True,
             timeout: float = 30.0) -> None:
        """Stop a supervised process."""

        if process_id not in self._processes:
            logger.warning(f"Process {process_id} not found for stop")
            return

        process = self._processes[process_id]
        log_process_event(logger, "supervisor.stop", process_id=process_id,
                         graceful=graceful)

        try:
            if graceful:
                # Send SIGTERM and wait
                process.terminate()
                try:
                    process.wait(timeout=timeout)
                    log_process_event(logger, "supervisor.stopped",
                                    process_id=process_id, method="graceful")
                except subprocess.TimeoutExpired:
                    log_process_event(logger, "supervisor.graceful_timeout",
                                    process_id=process_id)
                    process.kill()
                    process.wait()
                    log_process_event(logger, "supervisor.stopped",
                                    process_id=process_id, method="killed")
            else:
                # Force kill
                process.kill()
                process.wait()
                log_process_event(logger, "supervisor.stopped",
                                process_id=process_id, method="killed")

        finally:
            self._cleanup_process(process_id)

    def is_running(self, process_id: str) -> bool:
        """Check if process is running."""
        if process_id not in self._processes:
            return False

        process = self._processes[process_id]
        return process.poll() is None

    def get_process_info(self, process_id: str) -> Optional[ProcessInfo]:
        """Get process information."""
        return self._process_info.get(process_id)

    def get_stats(self, process_id: str) -> Optional[ProcessStats]:
        """Get process statistics."""
        if not self.is_running(process_id):
            return None

        process_info = self._process_info.get(process_id)
        if not process_info:
            return None

        try:
            ps_process = psutil.Process(process_info.pid)
            memory_info = ps_process.memory_info()

            return ProcessStats(
                pid=process_info.pid,
                memory_rss=memory_info.rss,
                memory_vms=memory_info.vms,
                cpu_percent=ps_process.cpu_percent(),
                num_threads=ps_process.num_threads(),
                status=ps_process.status()
            )
        except psutil.NoSuchProcess:
            return None

    def list_processes(self) -> List[str]:
        """List all supervised process IDs."""
        return list(self._processes.keys())

    def stop_all(self, graceful: bool = True, timeout: float = 30.0) -> None:
        """Stop all supervised processes."""
        process_ids = list(self._processes.keys())
        for process_id in process_ids:
            try:
                self.stop(process_id, graceful, timeout)
            except Exception as e:
                logger.error(f"Error stopping process {process_id}: {e}")

        # Stop monitoring
        self._stop_monitoring.set()

    def _wait_for_readiness(self,
                           process_id: str,
                           readiness_check: Callable[[], bool],
                           timeout: float) -> None:
        """Wait for process to become ready."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if not self.is_running(process_id):
                raise ProcessStartupError(f"Process {process_id} died during startup")

            try:
                if readiness_check():
                    log_process_event(logger, "supervisor.ready",
                                    process_id=process_id,
                                    duration=time.time() - start_time)
                    return
            except Exception as e:
                logger.debug(f"Readiness check failed for {process_id}: {e}")

            time.sleep(0.5)

        raise ProcessTimeoutError(
            f"Process {process_id} did not become ready within {timeout}s",
            timeout=timeout
        )

    def _start_monitoring(self, process_id: str) -> None:
        """Start monitoring thread for process."""
        monitor_thread = threading.Thread(
            target=self._monitor_process,
            args=(process_id,),
            name=f"ProcessMonitor-{process_id}",
            daemon=True
        )
        self._monitoring_threads[process_id] = monitor_thread
        monitor_thread.start()

    def _monitor_process(self, process_id: str) -> None:
        """Monitor process for crashes and health."""
        process = self._processes.get(process_id)
        if not process:
            return

        while not self._stop_monitoring.is_set():
            try:
                # Check if process is still alive
                poll_result = process.poll()
                if poll_result is not None:
                    # Process has exited
                    self._handle_process_exit(process_id, poll_result)
                    break

                time.sleep(1.0)

            except Exception as e:
                logger.error(f"Error monitoring process {process_id}: {e}")
                break

    def _handle_process_exit(self, process_id: str, exit_code: int) -> None:
        """Handle unexpected process exit."""
        process_info = self._process_info.get(process_id)

        if exit_code == 0:
            log_process_event(logger, "supervisor.exited",
                            process_id=process_id, exit_code=exit_code)
        else:
            log_process_event(logger, "supervisor.crashed",
                            process_id=process_id, exit_code=exit_code)

            # Collect stderr for crash analysis
            process = self._processes.get(process_id)
            stderr_output = ""
            if process and process.stderr:
                try:
                    stderr_output = process.stderr.read()
                except Exception:
                    pass

            # This could trigger crash analysis in higher layers
            # For now, just log the crash
            logger.error(f"Process {process_id} crashed with exit code {exit_code}")
            if stderr_output:
                logger.error(f"Process {process_id} stderr: {stderr_output[:1000]}")

    def _cleanup_process(self, process_id: str) -> None:
        """Clean up process resources."""
        # Remove from tracking
        self._processes.pop(process_id, None)
        self._process_info.pop(process_id, None)

        # Stop monitoring thread
        monitor_thread = self._monitoring_threads.pop(process_id, None)
        if monitor_thread and monitor_thread.is_alive():
            # Monitoring thread will stop on next iteration
            pass


# Global instances
_process_executor = ProcessExecutor()
_process_supervisor = ProcessSupervisor()


def execute_command(command: List[str], **kwargs) -> ProcessResult:
    """Execute a one-shot command."""
    return _process_executor.run(command, **kwargs)


def start_supervised_process(process_id: str, command: List[str], **kwargs) -> ProcessInfo:
    """Start a supervised process."""
    return _process_supervisor.start(process_id, command, **kwargs)


def stop_supervised_process(process_id: str, **kwargs) -> None:
    """Stop a supervised process."""
    _process_supervisor.stop(process_id, **kwargs)


def is_process_running(process_id: str) -> bool:
    """Check if supervised process is running."""
    return _process_supervisor.is_running(process_id)


def get_process_info(process_id: str) -> Optional[ProcessInfo]:
    """Get supervised process information."""
    return _process_supervisor.get_process_info(process_id)


def get_process_stats(process_id: str) -> Optional[ProcessStats]:
    """Get supervised process statistics."""
    return _process_supervisor.get_stats(process_id)


def stop_all_processes(**kwargs) -> None:
    """Stop all supervised processes."""
    _process_supervisor.stop_all(**kwargs)

