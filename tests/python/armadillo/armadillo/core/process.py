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

        # Log complete command line for debugging
        logger.info(f"=== EXECUTING COMMAND ===")
        logger.info(f"Working directory: {cwd or Path.cwd()}")
        logger.info(f"Command: {' '.join(command)}")
        if env:
            logger.info(f"Environment: {env}")
        logger.info(f"=========================")

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
        self._streaming_threads: Dict[str, threading.Thread] = {}
        self._stop_monitoring = threading.Event()

    def _stream_output(self, process_id: str, process: subprocess.Popen) -> None:
        """Stream process output to terminal in real-time."""
        if not process.stdout:
            logger.warning(f"No stdout available for {process_id}")
            return

        try:
            line_count = 0
            # Use unbuffered reading for real-time output
            while process.poll() is None and not self._stop_monitoring.is_set():
                line = process.stdout.readline()
                if line:
                    line_count += 1
                    # Print to terminal with process ID prefix, flush immediately
                    print(f"[{process_id}] {line.rstrip()}", flush=True)
                else:
                    # No more output, brief pause
                    time.sleep(0.1)

            # Read any remaining output after process ends
            remaining_output = process.stdout.read()
            if remaining_output:
                for line in remaining_output.splitlines():
                    if line.strip():
                        line_count += 1
                        print(f"[{process_id}] {line}", flush=True)

        except Exception as e:
            logger.error(f"Output streaming error for {process_id}: {e}", exc_info=True)

    def start(self,
             process_id: str,
             command: List[str],
             cwd: Optional[Path] = None,
             env: Optional[Dict[str, str]] = None,
             startup_timeout: float = 30.0,
             readiness_check: Optional[Callable[[], bool]] = None,
             inherit_console: bool = False) -> ProcessInfo:
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

        log_process_event(logger, "supervisor.start", process_id=process_id,
                         command=command)

        # Log complete command line for debugging
        logger.info(f"=== STARTING PROCESS: {process_id} ===")
        logger.info(f"Working directory: {cwd or Path.cwd()}")
        logger.info(f"Complete command line:")
        logger.info(f"  {' '.join(command)}")
        if env:
            logger.info(f"Environment variables: {env}")
        logger.info(f"======================================")

        try:
            # Configure stdout/stderr based on inheritance mode
            if inherit_console:
                # Direct console inheritance - no buffering, perfect timing
                stdout_config = None  # Inherit parent's stdout
                stderr_config = None  # Inherit parent's stderr
                use_streaming = False
            else:
                # Captured output with streaming - adds process ID prefixes
                stdout_config = subprocess.PIPE
                stderr_config = subprocess.STDOUT  # Merge stderr into stdout
                use_streaming = True

            # Start the process in its own process group for proper cleanup of children
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=stdout_config,
                stderr=stderr_config,
                text=True if use_streaming else None,
                bufsize=1 if use_streaming else -1,  # Line buffered only for streaming
                universal_newlines=True if use_streaming else None,
                start_new_session=True  # Create new process group for proper child cleanup
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

            # Start output streaming thread (only if not inheriting console)
            if use_streaming:
                self._start_output_streaming(process_id)

            # Wait for readiness if check provided
            if readiness_check:
                self._wait_for_readiness(process_id, readiness_check, effective_timeout)

            # Start monitoring thread
            self._start_monitoring(process_id)

            return process_info

        except Exception as e:
            # Try to capture any output from the failed process
            error_output = ""
            try:
                if process_id in self._processes:
                    proc = self._processes[process_id]
                    if proc.stdout:
                        stdout, _ = proc.communicate(timeout=1.0)
                        if stdout:
                            error_output = f"\nProcess output:\n{stdout}"
            except:
                pass

            log_process_event(logger, "supervisor.start_failed",
                            process_id=process_id, error=str(e))
            self._cleanup_process(process_id)
            raise ProcessStartupError(f"Failed to start process {process_id}: {e}{error_output}") from e

    def stop(self,
             process_id: str,
             graceful: bool = True,
             timeout: float = 30.0) -> None:
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
            logger.warning(f"Process {process_id} not found for stop")
            return

        process = self._processes[process_id]
        log_process_event(logger, "supervisor.stop", process_id=process_id,
                         graceful=graceful, timeout=timeout)

        try:
            if graceful:
                # Step 1: Send SIGTERM to entire process group
                logger.debug(f"Sending SIGTERM to process group {process_id} (PGID: -{process.pid}, timeout: {timeout}s)")

                try:
                    # Kill the entire process group, not just the main process
                    if os.name != 'nt':  # Unix systems
                        os.killpg(process.pid, signal.SIGTERM)
                    else:  # Windows - fallback to single process
                        process.terminate()
                except (OSError, ProcessLookupError) as e:
                    # Process group might not exist or process already dead
                    logger.debug(f"Could not send SIGTERM to process group {process.pid}: {e}")
                    # Try single process as fallback
                    try:
                        process.terminate()
                    except:
                        pass  # Process might already be dead

                try:
                    process.wait(timeout=timeout)
                    log_process_event(logger, "supervisor.stopped",
                                    process_id=process_id, method="graceful_sigterm_group")
                    logger.debug(f"Process group {process_id} terminated gracefully via SIGTERM")
                    return  # Successfully terminated gracefully

                except subprocess.TimeoutExpired:
                    logger.warning(f"Process group {process_id} (PGID: {process.pid}) did not respond to SIGTERM within {timeout}s, escalating to SIGKILL")
                    log_process_event(logger, "supervisor.graceful_timeout",
                                    process_id=process_id, timeout=timeout)

            # Step 2: Force kill entire process group with SIGKILL
            logger.debug(f"Sending SIGKILL to process group {process_id} (PGID: -{process.pid})")

            try:
                if os.name != 'nt':  # Unix systems
                    os.killpg(process.pid, signal.SIGKILL)
                else:  # Windows - fallback to single process
                    process.kill()
            except (OSError, ProcessLookupError) as e:
                logger.debug(f"Could not send SIGKILL to process group {process.pid}: {e}")
                # Try single process as fallback
                try:
                    process.kill()
                except:
                    pass  # Process might already be dead

            # Step 3: Wait for process to be fully reaped (short timeout - SIGKILL should be immediate)
            try:
                process.wait(timeout=5.0)
                log_process_event(logger, "supervisor.stopped",
                                process_id=process_id, method="killed_sigkill")
                logger.debug(f"Process {process_id} killed successfully via SIGKILL")

            except subprocess.TimeoutExpired:
                # This should never happen with SIGKILL, but handle it defensively
                logger.error(f"CRITICAL: Process group {process_id} (PID: {process.pid}) did not die even after SIGKILL!")
                log_process_event(logger, "supervisor.sigkill_timeout",
                                process_id=process_id, pid=process.pid)

                # Last resort: try to kill the entire process tree manually
                logger.warning(f"Attempting emergency process tree kill for {process_id} (PID: {process.pid})")
                try:
                    if kill_process_tree(process.pid, signal.SIGKILL, timeout=3.0):
                        logger.info(f"Emergency process tree kill succeeded for {process_id}")
                    else:
                        logger.error(f"Emergency process tree kill also failed for {process_id}")
                except Exception as tree_e:
                    logger.error(f"Emergency process tree kill exception for {process_id}: {tree_e}")

                # Try to get process status for debugging
                try:
                    poll_result = process.poll()
                    logger.error(f"Process {process_id} poll() result after all kill attempts: {poll_result}")
                except Exception as poll_e:
                    logger.error(f"Could not poll process {process_id}: {poll_e}")

                # Continue with cleanup anyway - we've exhausted all options

        except Exception as e:
            logger.error(f"Unexpected error stopping process {process_id}: {e}")
            log_process_event(logger, "supervisor.stop_error", process_id=process_id, error=str(e))
            import traceback
            logger.error(f"Stack trace: {traceback.format_exc()}")

        finally:
            # Always clean up our tracking, even if termination failed completely
            self._cleanup_process(process_id)

    def _cleanup_process(self, process_id: str) -> None:
        """Clean up process resources and tracking."""
        try:
            # Remove from process tracking
            if process_id in self._processes:
                self._processes.pop(process_id)
                logger.debug(f"Removed process {process_id} from tracking")

            # Remove process info
            if process_id in self._process_info:
                self._process_info.pop(process_id)
                logger.debug(f"Removed process info for {process_id}")

            # Stop and clean up streaming thread
            if process_id in self._streaming_threads:
                thread = self._streaming_threads.pop(process_id)
                # Thread is daemon, so it will stop when the process ends
                logger.debug(f"Cleaned up streaming thread for {process_id}")

        except Exception as e:
            logger.error(f"Error cleaning up process {process_id}: {e}")

    def is_running(self, process_id: str) -> bool:
        """Check if process is running."""
        if process_id not in self._processes:
            logger.debug(f"is_running({process_id}): not in _processes")
            return False

        process = self._processes[process_id]
        poll_result = process.poll()
        is_running = poll_result is None

        if not is_running:
            logger.debug(f"is_running({process_id}): process exited with code {poll_result}")

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
                # Try to capture any output from the dead process
                error_output = ""
                try:
                    if process_id in self._processes:
                        proc = self._processes[process_id]
                        if proc.stdout:
                            stdout, _ = proc.communicate(timeout=1.0)
                            if stdout:
                                error_output = f"\nProcess output:\n{stdout}"
                except:
                    pass
                raise ProcessStartupError(f"Process {process_id} died during startup{error_output}")

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

    def _start_output_streaming(self, process_id: str) -> None:
        """Start output streaming thread for process."""
        process = self._processes.get(process_id)
        if not process:
            logger.warning(f"No process found for streaming: {process_id}")
            return

        streaming_thread = threading.Thread(
            target=self._stream_output,
            args=(process_id, process),
            name=f"OutputStreamer-{process_id}",
            daemon=True
        )
        self._streaming_threads[process_id] = streaming_thread
        streaming_thread.start()

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

        # Stop streaming thread
        streaming_thread = self._streaming_threads.pop(process_id, None)
        if streaming_thread and streaming_thread.is_alive():
            # Streaming thread will stop when process terminates
            pass

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

        # Get all children recursively
        children = parent.children(recursive=True)
        child_pids = [child.pid for child in children if child.is_running()]

        logger.debug(f"Found {len(child_pids)} child processes for PID {parent_pid}: {child_pids}")

    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        logger.debug(f"Could not get children for PID {parent_pid}: {e}")
    except Exception as e:
        logger.warning(f"Error getting child PIDs for {parent_pid}: {e}")

    return child_pids


def kill_process_tree(root_pid: int, signal_num: int = signal.SIGKILL, timeout: float = 5.0) -> bool:
    """Kill an entire process tree (parent + all children).

    This is a backup method when process groups don't work properly.

    Args:
        root_pid: The root process PID
        signal_num: Signal to send (SIGTERM or SIGKILL)
        timeout: Time to wait after sending signals

    Returns:
        True if all processes were killed successfully
    """
    logger.debug(f"Killing process tree rooted at PID {root_pid} with signal {signal_num}")

    try:
        # Get all child PIDs first (before we start killing)
        all_pids = [root_pid] + get_child_pids(root_pid)

        if len(all_pids) > 1:
            logger.debug(f"Process tree has {len(all_pids)} processes: {all_pids}")

        # Send signal to all processes
        killed_count = 0
        for pid in all_pids:
            try:
                os.kill(pid, signal_num)
                killed_count += 1
                logger.debug(f"Sent signal {signal_num} to PID {pid}")
            except (OSError, ProcessLookupError):
                logger.debug(f"PID {pid} already dead or inaccessible")

        if killed_count == 0:
            logger.debug(f"No processes to kill in tree rooted at {root_pid}")
            return True

        # Wait for processes to die
        start_time = time.time()
        while time.time() - start_time < timeout:
            alive_count = 0
            for pid in all_pids:
                try:
                    os.kill(pid, 0)  # Check if still alive
                    alive_count += 1
                except (OSError, ProcessLookupError):
                    pass  # Process is dead

            if alive_count == 0:
                logger.debug(f"All processes in tree rooted at {root_pid} are dead")
                return True

            time.sleep(0.1)

        # Some processes are still alive
        logger.warning(f"Some processes in tree rooted at {root_pid} are still alive after {timeout}s")
        return False

    except Exception as e:
        logger.error(f"Error killing process tree rooted at {root_pid}: {e}")
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
    import os
    import signal
    import time

    logger.warning(f"Emergency PID kill requested for PID {pid}")

    try:
        # Check if process exists
        try:
            os.kill(pid, 0)  # Signal 0 checks existence
        except OSError:
            logger.debug(f"PID {pid} does not exist - already dead")
            return True

        # Send SIGKILL directly
        logger.debug(f"Sending SIGKILL to PID {pid}")
        os.kill(pid, signal.SIGKILL)

        # Wait for process to die
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                os.kill(pid, 0)  # Check if still exists
                time.sleep(0.1)
            except OSError:
                # Process is gone
                logger.info(f"Emergency PID kill succeeded for PID {pid}")
                return True

        # Process still exists after timeout
        logger.error(f"CRITICAL: PID {pid} still exists after SIGKILL and {timeout}s wait!")
        return False

    except Exception as e:
        logger.error(f"Error in emergency PID kill for {pid}: {e}")
        return False


def kill_all_supervised_processes() -> None:
    """Emergency function to kill all processes tracked by the supervisor.

    This bypasses normal cleanup and kills entire process trees immediately.
    Use only when normal shutdown has failed completely.
    """
    logger.warning("Emergency kill of all supervised processes (including children)")

    try:
        if hasattr(_process_supervisor, '_processes'):
            processes = dict(_process_supervisor._processes)  # Copy to avoid modification during iteration

            if processes:
                logger.warning(f"Emergency killing {len(processes)} supervised processes and their children")

                # Phase 1: Try to kill entire process trees with SIGTERM first
                logger.debug("Phase 1: Attempting SIGTERM on process trees")
                failed_trees = []

                for process_id, process in processes.items():
                    try:
                        pid = process.pid
                        logger.debug(f"Emergency SIGTERM for process tree {process_id} (root PID: {pid})")

                        if not kill_process_tree(pid, signal.SIGTERM, timeout=2.0):
                            failed_trees.append((process_id, pid))

                    except Exception as e:
                        logger.error(f"Error in SIGTERM phase for process {process_id}: {e}")
                        failed_trees.append((process_id, getattr(process, 'pid', None)))

                # Phase 2: Force kill any remaining process trees with SIGKILL
                if failed_trees:
                    logger.warning(f"Phase 2: Force killing {len(failed_trees)} stubborn process trees")

                    for process_id, pid in failed_trees:
                        if pid is not None:
                            try:
                                logger.debug(f"Emergency SIGKILL for process tree {process_id} (root PID: {pid})")

                                if not kill_process_tree(pid, signal.SIGKILL, timeout=2.0):
                                    logger.error(f"CRITICAL: Could not kill process tree {process_id} (PID: {pid}) even with SIGKILL")

                            except Exception as e:
                                logger.error(f"Error in SIGKILL phase for process {process_id}: {e}")

                # Clear all tracking
                _process_supervisor._processes.clear()
                _process_supervisor._process_info.clear()
                _process_supervisor._streaming_threads.clear()

                logger.warning("Emergency process tree kill completed")
            else:
                logger.debug("No supervised processes to kill")

    except Exception as e:
        logger.error(f"Error in emergency process tree kill: {e}")
        import traceback
        logger.error(f"Stack trace: {traceback.format_exc()}")


# Module-level instance for global usage
_process_supervisor = ProcessSupervisor()

