"""Advanced test management for Armadillo framework."""

from .selector import (
    TestSelector,
    TestFilter,
    FilterCriteria,
    SelectionResult,
    FilterType,
    FilterOperation,
    create_marker_selector,
    create_pattern_selector,
    create_suite_selector,
)

# TODO: Import other modules when implemented
# from .organizer import (
#     TestSuiteOrganizer,
#     TestSuite,
#     SuiteConfig,
# )
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
    # Test Selection (currently implemented)
    'TestSelector',
    'TestFilter', 
    'FilterCriteria',
    'SelectionResult',
    'FilterType',
    'FilterOperation',
    'create_marker_selector',
    'create_pattern_selector',
    'create_suite_selector',
    
    # TODO: Add when implemented
    # # Test Organization
    # 'TestSuiteOrganizer',
    # 'TestSuite',
    # 'SuiteConfig',
    # 
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
