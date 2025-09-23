"""Advanced test management for Armadillo framework."""

from .selector import (
    Selector,
    Filter,
    FilterCriteria,
    SelectionResult,
    FilterType,
    FilterOperation,
    create_marker_selector,
    create_pattern_selector,
    create_suite_selector,
)

from .organizer import (
    SuiteOrganizer,
    Suite,
    SuiteConfig,
    SuitePriority,
    SuiteStatus,
    create_marker_suite,
    create_pattern_suite,
    create_priority_suite,
)

# from .parallel import (
#     ParallelExecutor,
#     ExecutionPlan,
#     ResourceCoordinator,
# )
# from .background import (
#     BackgroundProcessManager,
#     BackgroundProcess,
#     ProcessConfig,
# )

__all__ = [
    # Test Selection
    "Selector",
    "Filter",
    "FilterCriteria",
    "SelectionResult",
    "FilterType",
    "FilterOperation",
    "create_marker_selector",
    "create_pattern_selector",
    "create_suite_selector",
    # Test Organization
    "SuiteOrganizer",
    "Suite",
    "SuiteConfig",
    "SuitePriority",
    "SuiteStatus",
    "create_marker_suite",
    "create_pattern_suite",
    "create_priority_suite",
    # TODO: Add when implemented
    # # Parallel Execution
    # 'ParallelExecutor',
    # 'ExecutionPlan',
    # 'ResourceCoordinator',
    #
    # # Background Processes
    # 'BackgroundProcessManager',
    # 'BackgroundProcess',
    # 'ProcessConfig',
]
