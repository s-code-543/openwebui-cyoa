#!/bin/bash
# Run CYOA game server tests
#
# Usage:
#   ./run_tests.sh                    # Run all tests
#   ./run_tests.sh -v                 # Verbose output
#   ./run_tests.sh -k admin           # Run only admin tests
#   ./run_tests.sh -m unit            # Run only unit tests
#   ./run_tests.sh -m integration     # Run only integration tests
#   ./run_tests.sh --cov              # Run with coverage report
#   ./run_tests.sh -x                 # Stop on first failure

set -e

cd "$(dirname "$0")"

# Ensure we're in the right directory
if [ ! -f "manage.py" ]; then
    echo "Error: Must run from cyoa-game-server directory"
    exit 1
fi

# Check if pytest is installed
if ! python3 -c "import pytest" 2>/dev/null; then
    echo "Installing test dependencies..."
    pip3 install pytest pytest-django pytest-cov pytest-mock factory-boy freezegun responses
fi

# Default arguments
PYTEST_ARGS="-v --tb=short"

# Check for coverage flag
if [[ " $@ " =~ " --cov " ]]; then
    PYTEST_ARGS="$PYTEST_ARGS --cov=game --cov-report=html --cov-report=term-missing"
    # Remove --cov from passed arguments
    set -- "${@/--cov/}"
fi

echo "========================================"
echo "  CYOA Game Server Test Suite"
echo "========================================"
echo ""

# Run pytest with all arguments
python3 -m pytest $PYTEST_ARGS "$@"

# If coverage was run, show location of report
if [[ " $PYTEST_ARGS " =~ " --cov " ]]; then
    echo ""
    echo "Coverage report generated at: htmlcov/index.html"
fi
