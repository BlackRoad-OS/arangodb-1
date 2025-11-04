"""Domain primitives for server identification and diagnostics."""

from dataclasses import dataclass
from typing import Optional

from .types import ServerRole


@dataclass(frozen=True)
class ServerId:
    """Validated server identifier. Hashable for use as dictionary key."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValueError("ServerId cannot be empty")

        # Allow alphanumeric characters, underscores, and hyphens
        normalized = self.value.replace("_", "").replace("-", "")
        if not normalized.isalnum():
            raise ValueError(f"ServerId must be alphanumeric with _ or -: {self.value}")

    def __str__(self) -> str:
        return self.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, ServerId):
            return self.value == other.value
        return False


@dataclass(frozen=True)
class ServerContext:
    """Diagnostic snapshot combining server identity with runtime state.

    Separates identification (ServerId) from state tracking. Created on-demand
    for logging and error reporting where both logical ID and PID are needed.
    """

    server_id: ServerId
    role: ServerRole
    pid: Optional[int] = None
    port: Optional[int] = None

    def __str__(self) -> str:
        if self.pid is not None:
            return f"{self.server_id}[pid:{self.pid}]"
        return f"{self.server_id}[not running]"

    def is_running(self) -> bool:
        return self.pid is not None

    def is_agent(self) -> bool:
        return self.role == ServerRole.AGENT

    def is_coordinator(self) -> bool:
        return self.role == ServerRole.COORDINATOR

    def is_dbserver(self) -> bool:
        return self.role == ServerRole.DBSERVER

    def is_single(self) -> bool:
        return self.role == ServerRole.SINGLE


@dataclass(frozen=True)
class DeploymentId:
    """Validated deployment identifier. Hashable for use as dictionary key."""

    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise ValueError("DeploymentId cannot be empty")

        # Allow alphanumeric characters, underscores, and hyphens
        normalized = self.value.replace("_", "").replace("-", "")
        if not normalized.isalnum():
            raise ValueError(
                f"DeploymentId must be alphanumeric with _ or -: {self.value}"
            )

    def __str__(self) -> str:
        return self.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DeploymentId):
            return self.value == other.value
        return False
