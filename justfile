# Cracker — Prompt Injection Benchmark
# Run with: just <recipe>

default:
    @just --list

# ============================================================================
# Setup
# ============================================================================

# Install dependencies
install:
    uv sync

# Validate .env and configuration
check:
    uv run cracker validate-config

# List all available scenarios
list:
    uv run cracker list

# ============================================================================
# Run Scenarios
# ============================================================================

# Run a single scenario (static mode)
run scenario_id:
    uv run cracker scenario --scenario {{scenario_id}}

# Run a single scenario with adaptive attacker
run-adaptive scenario_id:
    uv run cracker scenario --scenario {{scenario_id}} --adaptive

# Run all scenarios (static)
run-all:
    uv run cracker scenario

# Run all scenarios (adaptive)
run-all-adaptive:
    uv run cracker scenario --adaptive

# Run all scenarios for a specific attack vector (file, tool, skill)
run-vector vector:
    uv run cracker scenario --vector {{vector}}

# Run a vector with adaptive attacker
run-vector-adaptive vector:
    uv run cracker scenario --vector {{vector}} --adaptive

# ============================================================================
# Adaptive Attacker Options
# ============================================================================

# Run with custom attacker model and turns
run-custom scenario_id attacker_model max_turns="5":
    uv run cracker scenario \
        --scenario {{scenario_id}} \
        --adaptive \
        --attacker-model {{attacker_model}} \
        --max-turns {{max_turns}}

# Stress test: many attacker turns against one scenario
stress scenario_id turns="10":
    uv run cracker scenario \
        --scenario {{scenario_id}} \
        --adaptive \
        --max-turns {{turns}}

# ============================================================================
# Backend: Daytona (cloud sandbox)
# ============================================================================

# Run scenario on Daytona with a specific model under test
run-daytona scenario_id model:
    uv run cracker scenario \
        --scenario {{scenario_id}} \
        --backend daytona \
        --model {{model}}

# Run all scenarios on Daytona
run-all-daytona model:
    uv run cracker scenario \
        --backend daytona \
        --model {{model}}

# Adaptive on Daytona
run-daytona-adaptive scenario_id model:
    uv run cracker scenario \
        --scenario {{scenario_id}} \
        --backend daytona \
        --model {{model}} \
        --adaptive

# ============================================================================
# Results
# ============================================================================

# Run all and save results to JSON
benchmark output="results/benchmark.json":
    @mkdir -p results
    uv run cracker scenario --adaptive --output {{output}}

# Run a vector and save results
benchmark-vector vector output="":
    #!/usr/bin/env bash
    mkdir -p results
    out="{{output}}"
    if [ -z "$out" ]; then out="results/{{vector}}.json"; fi
    uv run cracker scenario --vector {{vector}} --adaptive --output "$out"

# Show saved results
results:
    @ls -lht results/*.json 2>/dev/null || echo "No results yet. Run: just benchmark"

# Clean results
clean-results:
    rm -rf results/*.json
    @echo "Results cleaned"

# Archive results with timestamp
archive:
    #!/usr/bin/env bash
    ts=$(date +%Y%m%d_%H%M%S)
    mkdir -p archives
    tar -czf archives/results_${ts}.tar.gz results/
    echo "Archived to archives/results_${ts}.tar.gz"

# ============================================================================
# Development
# ============================================================================

# Run with verbose logging
debug scenario_id:
    uv run cracker --verbose scenario --scenario {{scenario_id}}

# Debug adaptive mode
debug-adaptive scenario_id:
    uv run cracker --verbose scenario --scenario {{scenario_id}} --adaptive

# Format code
fmt:
    uv run ruff format src/

# Lint code
lint:
    uv run ruff check src/

# Clean Python cache
clean-cache:
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    @echo "Cache cleaned"

# Full cleanup
clean: clean-cache clean-results
    @echo "Cleanup complete"

# ============================================================================
# Quick Reference
# ============================================================================

# Show example commands
examples:
    @echo "Quick start:"
    @echo "  just run file-naive              # single scenario, static"
    @echo "  just run-adaptive file-naive      # single scenario, adaptive attacker"
    @echo "  just run-vector file              # all file scenarios"
    @echo "  just run-all                      # everything"
    @echo ""
    @echo "Adaptive options:"
    @echo "  just stress file-naive 10         # 10 attacker turns"
    @echo "  just run-custom file-naive deepseek/deepseek-v3.2 8"
    @echo ""
    @echo "Daytona (cloud):"
    @echo "  just run-daytona file-naive moonshotai/kimi-k2.5"
    @echo ""
    @echo "Results:"
    @echo "  just benchmark                    # run all + save JSON"
    @echo "  just benchmark-vector file        # run file vector + save"
    @echo "  just results                      # list saved results"
