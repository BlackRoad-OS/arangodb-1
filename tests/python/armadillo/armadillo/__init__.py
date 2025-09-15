"""
Armadillo: Modern ArangoDB Testing Framework

A modern Python testing framework built on pytest that replaces ArangoDB's
legacy JavaScript testing framework. Provides sophisticated functionality
including distributed system orchestration, advanced crash analysis,
comprehensive monitoring, and result processing.
"""

__version__ = "1.0.0"

# Core exports
from .core.types import (
    DeploymentMode,
    ServerRole,
    ExecutionOutcome,
    ServerConfig,
    ClusterConfig,
    MonitoringConfig,
    ArmadilloConfig,
)

__all__ = [
    "__version__",
    "DeploymentMode",
    "ServerRole",
    "ExecutionOutcome",
    "ServerConfig",
    "ClusterConfig",
    "MonitoringConfig",
    "ArmadilloConfig",
]

