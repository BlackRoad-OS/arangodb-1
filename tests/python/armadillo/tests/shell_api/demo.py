#!/usr/bin/env python3
"""Demo script showing how to run shell API tests with Armadillo framework.

This script demonstrates the integration between the converted JavaScript tests
and the Armadillo framework's test management capabilities.
"""

import sys
from pathlib import Path

# Add armadillo to path for demo
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from armadillo.test_management import TestSuiteOrganizer, create_marker_selector
from .suite import setup_shell_api_tests


def main():
    """Demo the shell API test suite setup and organization."""
    print("🦔 Armadillo Shell API Test Suite Demo")
    print("=" * 50)

    # Set up the shell API test suite
    organizer = setup_shell_api_tests()

    # Export comprehensive summary
    summary = organizer.export_summary()

    print(f"📊 Test Suite Statistics:")
    stats = summary['statistics']
    print(f"  • Total suites: {stats['total_suites']}")
    print(f"  • Root suites: {stats['root_suites']}")
    print(f"  • Max hierarchy depth: {stats['max_hierarchy_depth']}")
    print(f"  • Has dependencies: {stats['has_dependencies']}")
    print(f"  • Has conflicts: {stats['has_conflicts']}")

    print(f"\n🎯 Execution Order:")
    for i, suite_name in enumerate(summary['execution_order'], 1):
        print(f"  {i}. {suite_name}")

    print(f"\n📋 Suite Details:")
    for suite_name, suite_info in summary['suites'].items():
        print(f"  📁 {suite_name}")
        print(f"     Description: {suite_info['description']}")
        print(f"     Status: {suite_info['status']}")
        print(f"     Priority: {suite_info['priority']}")
        if suite_info['tags']:
            print(f"     Tags: {', '.join(suite_info['tags'])}")
        if suite_info['children_count'] > 0:
            print(f"     Children: {suite_info['children_count']}")
        if suite_name in summary['suites'] and 'metadata' in organizer.get_suite(suite_name).config.metadata:
            metadata = organizer.get_suite(suite_name).config.metadata
            if 'endpoints_tested' in metadata:
                print(f"     Endpoints: {', '.join(metadata['endpoints_tested'])}")
        print()

    print(f"🏗️  Suite Hierarchy:")
    hierarchy = summary['hierarchy']
    if hierarchy['roots']:
        for root in hierarchy['roots']:
            print_hierarchy(root, indent=2)

    # Validation
    validation_errors = summary['validation_errors']
    if validation_errors:
        print(f"⚠️  Validation Issues:")
        for error in validation_errors:
            print(f"  • {error}")
    else:
        print("✅ All suite validations passed!")

    print(f"\n🔄 Test Integration:")
    print("  The tests are ready to run with:")
    print("  • pytest tests/shell_api/test_statistics.py")
    print("  • armadillo test run tests/shell_api/")
    print("  • Integration with Armadillo pytest plugin")

    print(f"\n🚀 Converted Features:")
    print("  ✅ JavaScript /_admin/statistics-description tests")
    print("  ✅ JavaScript /_admin/statistics tests")
    print("  ✅ Error handling (404 responses)")
    print("  ✅ Async request counting (with bug fix)")
    print("  ✅ Armadillo test suite organization")
    print("  ✅ Pytest markers and fixtures")
    print("  ✅ Python-arango and requests integration")

    print(f"\n📈 Next Steps:")
    print("  • Convert more JS test files from tests/js/client/shell/api/")
    print("  • Add version API tests")
    print("  • Add database management tests")
    print("  • Integrate with Armadillo server management")
    print("  • Add performance benchmarking")


def print_hierarchy(node, indent=0):
    """Print hierarchical tree structure."""
    prefix = "  " * indent + "├─ " if indent > 0 else ""
    print(f"{prefix}{node['name']} ({node['test_count']} tests, {node['status']})")

    for child in node.get('children', []):
        print_hierarchy(child, indent + 1)


if __name__ == "__main__":
    main()
