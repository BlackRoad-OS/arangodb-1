"""Core enumerations for the Armadillo framework.

Separated from types.py to break circular dependencies. This module contains
only enum definitions with no dependencies on other core modules.
"""

from enum import Enum


class DeploymentMode(Enum):
    """ArangoDB deployment mode."""

    SINGLE_SERVER = "single_server"
    CLUSTER = "cluster"


class ServerRole(Enum):
    """ArangoDB server role."""

    SINGLE = "single"
    AGENT = "agent"
    DBSERVER = "dbserver"
    COORDINATOR = "coordinator"


class ExecutionOutcome(Enum):
    """Test execution outcome."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    TIMEOUT = "timeout"
    CRASHED = "crashed"
