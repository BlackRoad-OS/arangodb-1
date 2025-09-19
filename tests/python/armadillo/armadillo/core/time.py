"""Layered timeout management with global deadlines, per-test timeouts, and watchdog enforcement."""

import time
import threading
import signal
import asyncio
from typing import Optional, Dict, Any
from dataclasses import dataclass
from contextlib import contextmanager, asynccontextmanager

from .errors import TimeoutError, DeadlineExceededError
from .log import get_logger

logger = get_logger(__name__)


@dataclass
class TimeoutScope:
    """Represents a timeout scope with deadline tracking."""
    name: str
    deadline: float
    parent: Optional['TimeoutScope'] = None
    watchdog_timeout: Optional[float] = None

    def remaining(self) -> float:
        """Get remaining time until deadline."""
        return max(0.0, self.deadline - time.time())

    def is_expired(self) -> bool:
        """Check if this scope has expired."""
        return time.time() >= self.deadline

    def effective_deadline(self) -> float:
        """Get the most restrictive deadline in the scope chain."""
        current_deadline = self.deadline
        if self.parent:
            parent_deadline = self.parent.effective_deadline()
            current_deadline = min(current_deadline, parent_deadline)
        return current_deadline

    def effective_remaining(self) -> float:
        """Get remaining time until the most restrictive deadline."""
        return max(0.0, self.effective_deadline() - time.time())


class TimeoutManager:
    """Manages layered timeout scopes with watchdog enforcement."""

    def __init__(self) -> None:
        self._local = threading.local()
        self._watchdog_thread: Optional[threading.Thread] = None
        self._watchdog_stop_event = threading.Event()
        self._global_deadline: Optional[float] = None
        self._test_timeouts: Dict[str, float] = {}

    def set_global_deadline(self, timeout: float) -> None:
        """Set the global test run deadline."""
        self._global_deadline = time.time() + timeout
        logger.info(f"Global deadline set to {timeout}s from now")

        # Start watchdog if not running
        if self._watchdog_thread is None or not self._watchdog_thread.is_alive():
            self._start_watchdog()

    def set_test_timeout(self, test_name: str, timeout: float) -> None:
        """Set timeout for a specific test."""
        self._test_timeouts[test_name] = timeout

    def get_test_timeout(self, test_name: str, default: float = 900.0) -> float:
        """Get timeout for a specific test."""
        return self._test_timeouts.get(test_name, default)

    def clamp_timeout(self, requested_timeout: Optional[float],
                     scope_name: str = "operation") -> float:
        """Clamp a requested timeout to current scope constraints."""
        current_scope = self._get_current_scope()

        if current_scope:
            remaining = current_scope.effective_remaining()
            if requested_timeout is None:
                return remaining
            return min(requested_timeout, remaining)
        elif self._global_deadline:
            global_remaining = max(0.0, self._global_deadline - time.time())
            if requested_timeout is None:
                return global_remaining
            return min(requested_timeout, global_remaining)
        else:
            return requested_timeout or 30.0  # Default fallback

    @contextmanager
    def timeout_scope(self, timeout: float, name: str = "scope",
                     watchdog_timeout: Optional[float] = None):
        """Create a timeout scope context manager."""
        start_time = time.time()
        deadline = start_time + timeout

        # Check global deadline constraint
        if self._global_deadline and deadline > self._global_deadline:
            deadline = self._global_deadline
            logger.warning(f"Timeout scope '{name}' clamped by global deadline")

        parent_scope = self._get_current_scope()
        scope = TimeoutScope(name, deadline, parent_scope, watchdog_timeout)

        self._set_current_scope(scope)
        logger.debug(f"Entering timeout scope '{name}' with deadline {timeout}s")

        try:
            yield scope
        except Exception as e:
            if scope.is_expired():
                elapsed = time.time() - start_time
                raise DeadlineExceededError(
                    f"Timeout scope '{name}' exceeded deadline",
                    deadline=deadline,
                    elapsed=elapsed
                ) from e
            raise
        finally:
            self._set_current_scope(parent_scope)
            elapsed = time.time() - start_time
            logger.debug(f"Exiting timeout scope '{name}' after {elapsed:.2f}s")

    @asynccontextmanager
    async def async_timeout_scope(self, timeout: float, name: str = "async_scope"):
        """Create an async timeout scope context manager."""
        clamped_timeout = self.clamp_timeout(timeout, name)

        try:
            async with asyncio.timeout(clamped_timeout):
                with self.timeout_scope(clamped_timeout, name) as scope:
                    yield scope
        except asyncio.TimeoutError as e:
            raise DeadlineExceededError(
                f"Async timeout scope '{name}' exceeded deadline",
                deadline=time.time() + clamped_timeout,
                elapsed=clamped_timeout
            ) from e

    def _get_current_scope(self) -> Optional[TimeoutScope]:
        """Get current timeout scope for this thread."""
        return getattr(self._local, 'current_scope', None)

    def _set_current_scope(self, scope: Optional[TimeoutScope]) -> None:
        """Set current timeout scope for this thread."""
        self._local.current_scope = scope

    def _start_watchdog(self) -> None:
        """Start the watchdog thread for timeout enforcement."""
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return

        self._watchdog_stop_event.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="TimeoutWatchdog",
            daemon=True
        )
        self._watchdog_thread.start()
        logger.debug("Timeout watchdog started")

    def _watchdog_loop(self) -> None:
        """Watchdog thread main loop."""
        while not self._watchdog_stop_event.is_set():
            try:
                # Check global deadline
                if self._global_deadline and time.time() >= self._global_deadline:
                    logger.error("Global deadline exceeded - triggering emergency shutdown")
                    self._trigger_watchdog_timeout("global_deadline")
                    break

                # Sleep for watchdog interval
                if self._watchdog_stop_event.wait(1.0):
                    break

            except Exception as e:
                logger.error(f"Watchdog error: {e}")
                continue

    def _trigger_watchdog_timeout(self, reason: str) -> None:
        """Trigger watchdog timeout with escalating signals."""
        logger.critical(f"Watchdog timeout triggered: {reason}")

        try:
            # Log structured event
            from .log import log_event
            log_event(logger, 'timeout', f"Watchdog fired: {reason}",
                     event='timeout.watchdog.fired', reason=reason)
        except Exception:
            pass  # Don't let logging errors prevent timeout handling

        # Send SIGTERM first (graceful)
        try:
            import os
            os.kill(os.getpid(), signal.SIGTERM)

            # Wait briefly for graceful shutdown
            time.sleep(2.0)

            # If still alive, send SIGKILL
            os.kill(os.getpid(), signal.SIGKILL)
        except Exception as e:
            logger.error(f"Failed to send timeout signals: {e}")

    def stop_watchdog(self) -> None:
        """Stop the watchdog thread."""
        if self._watchdog_thread:
            self._watchdog_stop_event.set()
            self._watchdog_thread.join(timeout=5.0)
            logger.debug("Timeout watchdog stopped")

    def get_status(self) -> Dict[str, Any]:
        """Get current timeout manager status."""
        current_time = time.time()
        status = {
            'current_time': current_time,
            'watchdog_active': self._watchdog_thread and self._watchdog_thread.is_alive(),
        }

        if self._global_deadline:
            status['global_deadline'] = self._global_deadline
            status['global_remaining'] = max(0.0, self._global_deadline - current_time)

        current_scope = self._get_current_scope()
        if current_scope:
            status['current_scope'] = {
                'name': current_scope.name,
                'deadline': current_scope.deadline,
                'remaining': current_scope.remaining(),
                'effective_remaining': current_scope.effective_remaining(),
            }

        return status


# Global timeout manager instance
_timeout_manager = TimeoutManager()


def set_global_deadline(timeout: float) -> None:
    """Set global test run deadline."""
    _timeout_manager.set_global_deadline(timeout)


def set_test_timeout(test_name: str, timeout: float) -> None:
    """Set timeout for specific test."""
    _timeout_manager.set_test_timeout(test_name, timeout)


def get_test_timeout(test_name: str, default: float = 900.0) -> float:
    """Get timeout for specific test."""
    return _timeout_manager.get_test_timeout(test_name, default)


def clamp_timeout(requested_timeout: Optional[float],
                 scope_name: str = "operation") -> float:
    """Clamp timeout to current scope constraints."""
    return _timeout_manager.clamp_timeout(requested_timeout, scope_name)


def timeout_scope(timeout: float, name: str = "scope",
                 watchdog_timeout: Optional[float] = None):
    """Create timeout scope context manager."""
    return _timeout_manager.timeout_scope(timeout, name, watchdog_timeout)


def async_timeout_scope(timeout: float, name: str = "async_scope"):
    """Create async timeout scope context manager."""
    return _timeout_manager.async_timeout_scope(timeout, name)


def stop_watchdog() -> None:
    """Stop timeout watchdog."""
    _timeout_manager.stop_watchdog()


def get_timeout_status() -> Dict[str, Any]:
    """Get timeout manager status."""
    return _timeout_manager.get_status()

