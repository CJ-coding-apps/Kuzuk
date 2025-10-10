#!/usr/bin/env python3
"""
Test runner for Kuzuk with different test categories.
"""

import sys
import subprocess
import argparse
import os
from pathlib import Path


def run_command(cmd, description):
    """Run a command and report results."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print('='*60)
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=False)
        print(f"✅ {description} - PASSED")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} - FAILED (exit code: {e.returncode})")
        return False
    except FileNotFoundError:
        print(f"❌ {description} - FAILED (command not found)")
        return False


def main():
    parser = argparse.ArgumentParser(description="Run Kuzuk tests")
    parser.add_argument("--unit", action="store_true", help="Run unit tests only")
    parser.add_argument("--integration", action="store_true", help="Run integration tests")
    parser.add_argument("--performance", action="store_true", help="Run performance tests")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--coverage", action="store_true", help="Generate coverage report")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--fail-fast", "-x", action="store_true", help="Stop on first failure")
    
    args = parser.parse_args()
    
    # Default to unit tests if no specific category is selected
    if not any([args.unit, args.integration, args.performance, args.all]):
        args.unit = True
    
    # Change to project root directory
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    results = []
    
    # Base pytest command
    base_cmd = ["python", "-m", "pytest"]
    if args.verbose:
        base_cmd.append("-v")
    if args.fail_fast:
        base_cmd.append("-x")
    
    # Coverage options
    if args.coverage:
        base_cmd.extend([
            "--cov=kuzuk",
            "--cov-report=html",
            "--cov-report=term-missing",
            "--cov-fail-under=70"
        ])
    
    # Run unit tests
    if args.unit or args.all:
        cmd = base_cmd + ["-m", "unit", "tests/"]
        results.append(run_command(cmd, "Unit Tests"))
    
    # Run integration tests
    if args.integration or args.all:
        cmd = base_cmd + ["-m", "integration", "tests/"]
        results.append(run_command(cmd, "Integration Tests"))
    
    # Run performance tests
    if args.performance or args.all:
        cmd = base_cmd + ["-m", "performance", "--run-performance", "tests/"]
        results.append(run_command(cmd, "Performance Tests"))
    
    # Run import tests
    if args.all:
        cmd = ["python", "tests/test_package_structure.py"]
        results.append(run_command(cmd, "Package Structure Tests"))
    
    # Run code quality checks if available
    if args.all:
        quality_checks = [
            (["python", "-m", "black", "--check", "kuzuk/", "tests/"], "Code Formatting (Black)"),
            (["python", "-m", "isort", "--check-only", "kuzuk/", "tests/"], "Import Sorting (isort)"),
            (["python", "-m", "flake8", "kuzuk/"], "Linting (flake8)"),
            (["python", "-m", "mypy", "kuzuk/"], "Type Checking (mypy)"),
        ]
        
        for cmd, desc in quality_checks:
            try:
                # Check if tool is available
                tool = cmd[2]  # Extract tool name
                subprocess.run(["python", "-m", tool, "--version"], 
                             check=True, capture_output=True)
                results.append(run_command(cmd, desc))
            except (subprocess.CalledProcessError, FileNotFoundError):
                print(f"⚠️  {desc} - SKIPPED (tool not available)")
    
    # Print summary
    print(f"\n{'='*60}")
    print("TEST SUMMARY")
    print('='*60)
    
    passed = sum(results)
    total = len(results)
    
    if total == 0:
        print("No tests were run.")
        return 0
    
    for i, result in enumerate(results):
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"Test {i+1}: {status}")
    
    print(f"\nOverall: {passed}/{total} test categories passed")
    
    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print("💥 Some tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())