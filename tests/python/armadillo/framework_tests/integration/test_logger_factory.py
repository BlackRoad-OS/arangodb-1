"""Integration tests for LoggerFactory and IsolatedLogManager.

These tests verify real-world behavior including thread isolation,
which requires actual threading (not mocked).
"""

import threading
import time

from armadillo.core.logger_factory import IsolatedLogManager


class TestIsolatedLogManagerThreadIsolation:
    """Test thread isolation in IsolatedLogManager."""

    def setup_method(self) -> None:
        """Set up test environment."""
        self.manager = IsolatedLogManager("test")

    def teardown_method(self) -> None:
        """Clean up after test."""
        self.manager.shutdown()

    def test_thread_isolation(self) -> None:
        """Test that context is isolated between threads."""
        self.manager.configure(enable_json=False, enable_console=False)

        contexts: dict[int, dict] = {}
        barrier = threading.Barrier(2)

        def thread_worker(thread_id: int) -> None:
            self.manager.set_context(thread_id=thread_id)
            barrier.wait()  # Synchronize
            time.sleep(0.01)  # Small delay
            contexts[thread_id] = self.manager.get_context()

        thread1 = threading.Thread(target=thread_worker, args=(1,))
        thread2 = threading.Thread(target=thread_worker, args=(2,))

        thread1.start()
        thread2.start()
        thread1.join()
        thread2.join()

        # Each thread should have its own context
        assert contexts[1]["thread_id"] == 1
        assert contexts[2]["thread_id"] == 2
