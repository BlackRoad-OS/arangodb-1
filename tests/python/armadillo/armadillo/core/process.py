"""Process execution and supervision with timeout enforcement and crash detection."""

import os
import signal
import subprocess
import threading
import time
import traceback
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import psutil
from .errors import (
    ProcessError,
    ProcessStartupError,
    ProcessTimeoutError,
    ArmadilloTimeoutError,
)
from .time import clamp_timeout, timeout_scope
from .log import get_logger, log_process_event
from .types import ProcessStats, CrashInfo

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

    def run(
        self,
        command: List[str],
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        input_data: Optional[str] = None,
        capture_output: bool = True,
    ) -> ProcessResult:
        """Execute a command with timeout enforcement."""
        effective_timeout = clamp_timeout(timeout, f"process:{command[0]}")
        start_time = time.time()
        log_process_event(
            logger, "exec.start", command=command, timeout=effective_timeout
        )
        logger.info("=== EXECUTING COMMAND ===")
        logger.info("Working directory: %s", cwd or Path.cwd())
        logger.info("Command: %s", " ".join(command))
        if env:
            logger.info("Environment: %s", env)
        logger.info("=========================")
        try:
            with timeout_scope(effective_timeout, f"process_exec_{command[0]}"):
                process = subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=env,
                    stdin=subprocess.PIPE if input_data else None,
                    stdout=subprocess.PIPE if capture_output else None,
                    stderr=subprocess.PIPE if capture_output else None,
                    text=True,
                )
                try:
                    stdout, stderr = process.communicate(
                        input=input_data, timeout=effective_timeout
                    )
                    duration = time.time() - start_time
                    result = ProcessResult(
                        returncode=process.returncode,
                        stdout=stdout or "",
                        stderr=stderr or "",
                        duration=duration,
                    )
                    if process.returncode == 0:
                        log_process_event(logger, "exec.ok", duration=duration)
                    else:
                        log_process_event(
                            logger,
                            "exec.failed",
                            return_code=process.returncode,
                            duration=duration,
                        )
                    return result
                except subprocess.TimeoutExpired as e:
                    duration = time.time() - start_time
                    log_process_event(logger, "exec.timeout", duration=duration)
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise ProcessTimeoutError(
                        f"Command {command[0]} timed out after {effective_timeout}s",
                        timeout=effective_timeout,
                        details={"command": command, "duration": duration},
                    ) from e
        except ArmadilloTimeoutError as e:
            duration = time.time() - start_time
            raise ProcessTimeoutError(
                f"Command {command[0]} exceeded deadline",
                timeout=effective_timeout,
                details={"command": command, "duration": duration},
            ) from e
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            duration = time.time() - start_time
            log_process_event(logger, "exec.error", duration=duration, error=str(e))
            raise ProcessError(f"Failed to execute command {command[0]}: {e}") from e


class ProcessSupervisor:
    """Manages long-running processes with health monitoring and crash detection."""

    def __init__(self) -> None:
        self._processes: Dict[str, subprocess.Popen] = {}
        self._process_info: Dict[str, ProcessInfo] = {}
        self._monitoring_threads: Dict[str, threading.Thread] = {}
        self._streaming_threads: Dict[str, threading.Thread] = {}
        self._stop_monitoring = threading.Event()
        self._crash_state: Dict[str, CrashInfo] = {}  # Track crash information per process
        self._lock = threading.Lock()  # Protect crash state access

    def _stream_output(self, process_id: str, process: subprocess.Popen) -> None:
        """Stream process output to terminal in real-time."""
        if not process.stdout:
            logger.warning("No stdout available for %s", process_id)
            return
        try:
            line_count = 0
            while process.poll() is None and (not self._stop_monitoring.is_set()):
                line = process.stdout.readline()
                if line:
                    line_count += 1
                    print(f"[{process_id}] {line.rstrip()}", flush=True)
                else:
                    time.sleep(0.1)
            remaining_output = process.stdout.read()
            if remaining_output:
                for line in remaining_output.splitlines():
                    if line.strip():
                        line_count += 1
                        print(f"[{process_id}] {line}", flush=True)
        except (OSError, UnicodeDecodeError, BrokenPipeError, ValueError) as e:
            logger.error(
                "Output streaming error for %s: %s", process_id, e, exc_info=True
            )

    def start(
        self,
        process_id: str,
        command: List[str],
        cwd: Optional[Path] = None,
        env: Optional[Dict[str, str]] = None,
        startup_timeout: float = 30.0,
        readiness_check: Optional[Callable[[], bool]] = None,
        inherit_console: bool = False,
    ) -> ProcessInfo:
        """Start a supervised process.

        Args:
            process_id: Unique identifier for the process
            command: Command and arguments to execute
            cwd: Working directory (optional)
            env: Environment variables (optional)
            startup_timeout: Maximum time to wait for startup (seconds)
            readiness_check: Function to check if process is ready (optional)
            inherit_console: If True, process inherits parent's stdout/stderr directly
                           (no buffering delays). If False, output is captured and
                           streamed with [process_id] prefixes (default: False)

        Returns:
            ProcessInfo object with process details
        """
        if process_id in self._processes:
            raise ProcessStartupError(f"Process {process_id} is already running")
        effective_timeout = clamp_timeout(startup_timeout, f"startup_{process_id}")
        log_process_event(
            logger, "supervisor.start", process_id=process_id, command=command
        )
        logger.info("=== STARTING PROCESS: %s ===", process_id)
        logger.info("Working directory: %s", cwd or Path.cwd())
        logger.info("Complete command line:")
        logger.info("  %s", " ".join(command))
        if env:
            logger.info("Environment variables: %s", env)
        logger.info("======================================")
        try:
            if inherit_console:
                stdout_config = None
                stderr_config = None
                use_streaming = False
            else:
                stdout_config = subprocess.PIPE
                stderr_config = subprocess.STDOUT
                use_streaming = True
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=stdout_config,
                stderr=stderr_config,
                text=True if use_streaming else None,
                bufsize=1 if use_streaming else -1,
                universal_newlines=True if use_streaming else None,
                start_new_session=True,
            )
            process_info = ProcessInfo(
                pid=process.pid,
                command=command,
                start_time=time.time(),
                working_dir=cwd or Path.cwd(),
                env=env or {},
            )
            self._processes[process_id] = process
            self._process_info[process_id] = process_info
            log_process_event(
                logger, "supervisor.started", process_id=process_id, pid=process.pid
            )
            if use_streaming:
                self._start_output_streaming(process_id)
            if readiness_check:
                self._wait_for_readiness(process_id, readiness_check, effective_timeout)
            self._start_monitoring(process_id)
            return process_info
        except (
            OSError,
            subprocess.SubprocessError,
            ProcessStartupError,
            ProcessTimeoutError,
        ) as e:
            error_output = ""
            try:
                if process_id in self._processes:
                    proc = self._processes[process_id]
                    if proc.stdout:
                        stdout, _ = proc.communicate(timeout=1.0)
                        if stdout:
                            error_output = f"\nProcess output:\n{stdout}"
            except Exception:  # pylint: disable=broad-exception-caught
                # Ignore errors when trying to get process output for error message
                pass
            log_process_event(
                logger, "supervisor.start_failed", process_id=process_id, error=str(e)
            )
            self._cleanup_process(process_id)
            raise ProcessStartupError(
                f"Failed to start process {process_id}: {e}{error_output}"
            ) from e

    def stop(
        self, process_id: str, graceful: bool = True, timeout: float = 30.0
    ) -> None:
        """Stop a supervised process with bulletproof termination.

        This method provides watertight process termination:
        1. If graceful=True: Send SIGTERM, wait for timeout, then escalate to SIGKILL
        2. If graceful=False: Send SIGKILL immediately
        3. Always wait for process to be fully reaped
        4. Handle edge cases and zombie processes defensively

        Args:
            process_id: Process to stop
            graceful: If True, try SIGTERM first. If False, use SIGKILL immediately
            timeout: Time to wait for graceful termination before escalating
        """
        if process_id not in self._processes:
            logger.warning("Process %s not found for stop", process_id)
            return
        process = self._processes[process_id]
        log_process_event(
            logger,
            "supervisor.stop",
            process_id=process_id,
            graceful=graceful,
            timeout=timeout,
        )
        try:
            if graceful:
                logger.debug(
                    "Sending SIGTERM to process group %s (PGID: -%s, timeout: %ss)",
                    process_id,
                    process.pid,
                    timeout,
                )
                try:
                    if os.name != "nt":
                        os.killpg(process.pid, signal.SIGTERM)
                    else:
                        process.terminate()
                except (OSError, ProcessLookupError) as e:
                    logger.debug(
                        "Could not send SIGTERM to process group %s: %s", process.pid, e
                    )
                    try:
                        process.terminate()
                    except (OSError, ProcessLookupError):
                        # Process already dead or not accessible - acceptable during cleanup
                        pass
                try:
                    process.wait(timeout=timeout)
                    log_process_event(
                        logger,
                        "supervisor.stopped",
                        process_id=process_id,
                        method="graceful_sigterm_group",
                    )
                    logger.debug(
                        "Process group %s terminated gracefully via SIGTERM", process_id
                    )
                    return
                except subprocess.TimeoutExpired:
                    logger.warning(
                        "Process group %s (PGID: %s) did not respond to SIGTERM within %ss, escalating to SIGKILL",
                        process_id,
                        process.pid,
                        timeout,
                    )
                    log_process_event(
                        logger,
                        "supervisor.graceful_timeout",
                        process_id=process_id,
                        timeout=timeout,
                    )
            logger.debug(
                "Sending SIGKILL to process group %s (PGID: -%s)",
                process_id,
                process.pid,
            )
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except (OSError, ProcessLookupError) as e:
                logger.debug(
                    "Could not send SIGKILL to process group %s: %s", process.pid, e
                )
                try:
                    process.kill()
                except (OSError, ProcessLookupError):
                    pass
            try:
                process.wait(timeout=5.0)
                log_process_event(
                    logger,
                    "supervisor.stopped",
                    process_id=process_id,
                    method="killed_sigkill",
                )
                logger.debug("Process %s killed successfully via SIGKILL", process_id)
            except subprocess.TimeoutExpired:
                logger.error(
                    "CRITICAL: Process group %s (PID: %s) did not die even after SIGKILL!",
                    process_id,
                    process.pid,
                )
                log_process_event(
                    logger,
                    "supervisor.sigkill_timeout",
                    process_id=process_id,
                    pid=process.pid,
                )
                logger.warning(
                    "Attempting emergency process tree kill for %s (PID: %s)",
                    process_id,
                    process.pid,
                )
                try:
                    if kill_process_tree(process.pid, signal.SIGKILL, timeout=3.0):
                        logger.info(
                            "Emergency process tree kill succeeded for %s", process_id
                        )
                    else:
                        logger.error(
                            "Emergency process tree kill also failed for %s", process_id
                        )
                except (OSError, ProcessLookupError, PermissionError) as tree_e:
                    logger.error(
                        "Emergency process tree kill exception for %s: %s",
                        process_id,
                        tree_e,
                    )
                try:
                    poll_result = process.poll()
                    logger.error(
                        "Process %s poll() result after all kill attempts: %s",
                        process_id,
                        poll_result,
                    )
                except (OSError, ProcessLookupError) as poll_e:
                    logger.error("Could not poll process %s: %s", process_id, poll_e)
        except (
            OSError,
            ProcessLookupError,
            PermissionError,
            subprocess.SubprocessError,
        ) as e:
            logger.error("Unexpected error stopping process %s: %s", process_id, e)
            log_process_event(
                logger, "supervisor.stop_error", process_id=process_id, error=str(e)
            )
            logger.error("Stack trace: %s", traceback.format_exc())
        finally:
            self._cleanup_process(process_id)

    def is_running(self, process_id: str) -> bool:
        """Check if process is running."""
        if process_id not in self._processes:
            logger.debug("is_running(%s): not in _processes", process_id)
            return False
        process = self._processes[process_id]
        poll_result = process.poll()
        is_running = poll_result is None
        if not is_running:
            logger.debug(
                "is_running(%s): process exited with code %s", process_id, poll_result
            )
        return is_running

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
                status=ps_process.status(),
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
            except (
                OSError,
                ProcessLookupError,
                PermissionError,
                subprocess.SubprocessError,
            ) as e:
                logger.error("Error stopping process %s: %s", process_id, e)
        self._stop_monitoring.set()

    def _wait_for_readiness(
        self, process_id: str, readiness_check: Callable[[], bool], timeout: float
    ) -> None:
        """Wait for process to become ready."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not self.is_running(process_id):
                error_output = ""
                try:
                    if process_id in self._processes:
                        proc = self._processes[process_id]
                        if proc.stdout:
                            stdout, _ = proc.communicate(timeout=1.0)
                            if stdout:
                                error_output = f"\nProcess output:\n{stdout}"
                except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
                    pass
                raise ProcessStartupError(
                    f"Process {process_id} died during startup{error_output}"
                )
            try:
                if readiness_check():
                    log_process_event(
                        logger,
                        "supervisor.ready",
                        process_id=process_id,
                        duration=time.time() - start_time,
                    )
                    return
            except (
                OSError,
                ConnectionError,
                TimeoutError,
                ValueError,
                RuntimeError,
            ) as e:
                logger.debug("Readiness check failed for %s: %s", process_id, e)
            time.sleep(0.5)
        raise ProcessTimeoutError(
            f"Process {process_id} did not become ready within {timeout}s",
            timeout=timeout,
        )

    def _start_output_streaming(self, process_id: str) -> None:
        """Start output streaming thread for process."""
        process = self._processes.get(process_id)
        if not process:
            logger.warning("No process found for streaming: %s", process_id)
            return
        streaming_thread = threading.Thread(
            target=self._stream_output,
            args=(process_id, process),
            name=f"OutputStreamer-{process_id}",
            daemon=True,
        )
        self._streaming_threads[process_id] = streaming_thread
        streaming_thread.start()

    def _start_monitoring(self, process_id: str) -> None:
        """Start monitoring thread for process."""
        monitor_thread = threading.Thread(
            target=self._monitor_process,
            args=(process_id,),
            name=f"ProcessMonitor-{process_id}",
            daemon=True,
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
                poll_result = process.poll()
                if poll_result is not None:
                    self._handle_process_exit(process_id, poll_result)
                    break
                time.sleep(1.0)
            except (OSError, ProcessLookupError, AttributeError) as e:
                logger.error("Error monitoring process %s: %s", process_id, e)
                break

    def _handle_process_exit(self, process_id: str, exit_code: int) -> None:
        """Handle unexpected process exit."""
        _ = self._process_info.get(process_id)  # For future crash analysis
        if exit_code == 0:
            log_process_event(
                logger, "supervisor.exited", process_id=process_id, exit_code=exit_code
            )
        else:
            log_process_event(
                logger, "supervisor.crashed", process_id=process_id, exit_code=exit_code
            )
            process = self._processes.get(process_id)
            stderr_output = ""
            if process and process.stderr:
                try:
                    stderr_output = process.stderr.read()
                except (OSError, UnicodeDecodeError, ValueError):
                    pass
            logger.error("Process %s crashed with exit code %s", process_id, exit_code)
            if stderr_output:
                logger.error("Process %s stderr: %s", process_id, stderr_output[:1000])

            # Record crash information for pytest integration
            with self._lock:
                self._crash_state[process_id] = CrashInfo(
                    exit_code=exit_code,
                    timestamp=time.time(),
                    stderr=stderr_output[:1000] if stderr_output else None,
                    signal=-exit_code if exit_code < 0 else None,
                )

    def _cleanup_process(self, process_id: str) -> None:
        """Clean up process resources."""
        if self._processes.pop(process_id, None):
            logger.debug("Removed process %s from tracking", process_id)
        if self._process_info.pop(process_id, None):
            logger.debug("Removed process info for %s", process_id)
        streaming_thread = self._streaming_threads.pop(process_id, None)
        if streaming_thread:
            logger.debug("Cleaned up streaming thread for %s", process_id)
        monitor_thread = self._monitoring_threads.pop(process_id, None)
        if monitor_thread:
            logger.debug("Cleaned up monitoring thread for %s", process_id)

    def get_crash_state(self, process_id: Optional[str] = None) -> Optional[Dict[str, CrashInfo]]:
        """Get crash state for a process or all processes.

        Args:
            process_id: Specific process ID, or None to get all crashes

        Returns:
            CrashInfo for specific process if process_id given, or dict of all crashes
        """
        with self._lock:
            if process_id:
                return {process_id: self._crash_state[process_id]} if process_id in self._crash_state else None
            # Return copy of all crash states
            return dict(self._crash_state)

    def has_any_crash(self) -> bool:
        """Check if any process has crashed."""
        with self._lock:
            return len(self._crash_state) > 0

    def clear_crash_state(self, process_id: Optional[str] = None) -> None:
        """Clear crash state for a process or all processes.

        Args:
            process_id: Specific process ID, or None to clear all
        """
        with self._lock:
            if process_id:
                self._crash_state.pop(process_id, None)
            else:
                self._crash_state.clear()


_process_executor = ProcessExecutor()
_process_supervisor = ProcessSupervisor()


def execute_command(command: List[str], **kwargs) -> ProcessResult:
    """Execute a one-shot command."""
    return _process_executor.run(command, **kwargs)


def start_supervised_process(
    process_id: str, command: List[str], **kwargs
) -> ProcessInfo:
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


def get_crash_state(process_id: Optional[str] = None) -> Optional[Dict[str, CrashInfo]]:
    """Get crash state for supervised processes.

    Args:
        process_id: Specific process ID, or None to get all crashes

    Returns:
        Dict mapping process IDs to CrashInfo objects
    """
    return _process_supervisor.get_crash_state(process_id)


def has_any_crash() -> bool:
    """Check if any supervised process has crashed."""
    return _process_supervisor.has_any_crash()


def clear_crash_state(process_id: Optional[str] = None) -> None:
    """Clear crash state for supervised processes.

    Args:
        process_id: Specific process ID, or None to clear all
    """
    _process_supervisor.clear_crash_state(process_id)


def stop_all_processes(**kwargs) -> None:
    """Stop all supervised processes."""
    _process_supervisor.stop_all(**kwargs)


def get_child_pids(parent_pid: int) -> List[int]:
    """Get all child process PIDs for a given parent PID.

    This function recursively finds all descendants of the given process.

    Args:
        parent_pid: The parent process PID

    Returns:
        List of all child/descendant PIDs
    """
    child_pids = []
    try:
        parent = psutil.Process(parent_pid)
        children = parent.children(recursive=True)
        child_pids = [child.pid for child in children if child.is_running()]
        logger.debug(
            "Found %s child processes for PID %s: %s",
            len(child_pids),
            parent_pid,
            child_pids,
        )
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        logger.debug("Could not get children for PID %s: %s", parent_pid, e)
    except (psutil.Error, OSError) as e:
        logger.warning("Error getting child PIDs for %s: %s", parent_pid, e)
    return child_pids


def kill_process_tree(
    root_pid: int, signal_num: int = signal.SIGKILL, timeout: float = 5.0
) -> bool:
    """Kill an entire process tree (parent + all children).

    This is a backup method when process groups don't work properly.

    Args:
        root_pid: The root process PID
        signal_num: Signal to send (SIGTERM or SIGKILL)
        timeout: Time to wait after sending signals

    Returns:
        True if all processes were killed successfully
    """
    logger.debug(
        "Killing process tree rooted at PID %s with signal %s", root_pid, signal_num
    )
    try:
        all_pids = [root_pid] + get_child_pids(root_pid)
        if len(all_pids) > 1:
            logger.debug("Process tree has %s processes: %s", len(all_pids), all_pids)
        killed_count = 0
        for pid in all_pids:
            try:
                os.kill(pid, signal_num)
                killed_count += 1
                logger.debug("Sent signal %s to PID %s", signal_num, pid)
            except (OSError, ProcessLookupError):
                logger.debug("PID %s already dead or inaccessible", pid)
        if killed_count == 0:
            logger.debug("No processes to kill in tree rooted at %s", root_pid)
            return True
        start_time = time.time()
        while time.time() - start_time < timeout:
            alive_count = 0
            for pid in all_pids:
                try:
                    os.kill(pid, 0)
                    alive_count += 1
                except (OSError, ProcessLookupError):
                    pass
            if alive_count == 0:
                logger.debug("All processes in tree rooted at %s are dead", root_pid)
                return True
            time.sleep(0.1)
        logger.warning(
            "Some processes in tree rooted at %s are still alive after %ss",
            root_pid,
            timeout,
        )
        return False
    except (OSError, ProcessLookupError, PermissionError, psutil.Error) as e:
        logger.error("Error killing process tree rooted at %s: %s", root_pid, e)
        return False


def force_kill_by_pid(pid: int, timeout: float = 5.0) -> bool:
    """Emergency function to kill a process by PID using OS signals.

    This is a last resort when the normal process supervisor methods fail.

    Args:
        pid: Process ID to kill
        timeout: Time to wait after SIGKILL

    Returns:
        True if process was killed successfully, False otherwise
    """
    logger.warning("Emergency PID kill requested for PID %s", pid)
    try:
        try:
            os.kill(pid, 0)
        except OSError:
            logger.debug("PID %s does not exist - already dead", pid)
            return True
        logger.debug("Sending SIGKILL to PID %s", pid)
        os.kill(pid, signal.SIGKILL)
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except OSError:
                logger.info("Emergency PID kill succeeded for PID %s", pid)
                return True
        logger.error(
            "CRITICAL: PID %s still exists after SIGKILL and %ss wait!", pid, timeout
        )
        return False
    except (OSError, ProcessLookupError, PermissionError) as e:
        logger.error("Error in emergency PID kill for %s: %s", pid, e)
        return False


def kill_all_supervised_processes() -> None:
    """Emergency function to kill all processes tracked by the supervisor.

    This bypasses normal cleanup and kills entire process trees immediately.
    Use only when normal shutdown has failed completely.
    """
    logger.warning("Emergency kill of all supervised processes (including children)")
    try:
        if hasattr(_process_supervisor, "_processes"):
            processes = dict(_process_supervisor._processes)
            if processes:
                logger.warning(
                    "Emergency killing %s supervised processes and their children",
                    len(processes),
                )
                logger.debug("Phase 1: Attempting SIGTERM on process trees")
                failed_trees = []
                for process_id, process in processes.items():
                    try:
                        pid = process.pid
                        logger.debug(
                            "Emergency SIGTERM for process tree %s (root PID: %s)",
                            process_id,
                            pid,
                        )
                        if not kill_process_tree(pid, signal.SIGTERM, timeout=2.0):
                            failed_trees.append((process_id, pid))
                    except (
                        OSError,
                        ProcessLookupError,
                        AttributeError,
                        psutil.Error,
                    ) as e:
                        logger.error(
                            "Error in SIGTERM phase for process %s: %s", process_id, e
                        )
                        failed_trees.append((process_id, getattr(process, "pid", None)))
                if failed_trees:
                    logger.warning(
                        "Phase 2: Force killing %s stubborn process trees",
                        len(failed_trees),
                    )
                    for process_id, pid in failed_trees:
                        if pid is not None:
                            try:
                                logger.debug(
                                    "Emergency SIGKILL for process tree %s (root PID: %s)",
                                    process_id,
                                    pid,
                                )
                                if not kill_process_tree(
                                    pid, signal.SIGKILL, timeout=2.0
                                ):
                                    logger.error(
                                        "CRITICAL: Could not kill process tree %s (PID: %s) even with SIGKILL",
                                        process_id,
                                        pid,
                                    )
                            except (OSError, ProcessLookupError, psutil.Error) as e:
                                logger.error(
                                    "Error in SIGKILL phase for process %s: %s",
                                    process_id,
                                    e,
                                )
                _process_supervisor._processes.clear()
                _process_supervisor._process_info.clear()
                _process_supervisor._streaming_threads.clear()
                logger.warning("Emergency process tree kill completed")
            else:
                logger.debug("No supervised processes to kill")
    except (
        OSError,
        ProcessLookupError,
        AttributeError,
        psutil.Error,
        RuntimeError,
    ) as e:
        logger.error("Error in emergency process tree kill: %s", e)
        logger.error("Stack trace: %s", traceback.format_exc())


_process_supervisor = ProcessSupervisor()
