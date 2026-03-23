# Cracker - Adversarial Benchmark Justfile
# Run with: just <command>

# Default recipe - show help
default:
    @just --list

# ============================================================================
# Setup & Installation
# ============================================================================

# Install dependencies
install:
    uv pip install -e .

# Initialize submodules
init-submodules:
    git submodule update --init --recursive

# Full setup (submodules + install)
setup: init-submodules install
    @echo "✓ Setup complete!"

# Validate configuration
check-config:
    uv run cracker validate-config

# ============================================================================
# List Available Tasks
# ============================================================================

# List all available malicious tasks
list-malicious:
    uv run cracker list-malicious

# Show available scenarios
list-scenarios:
    @echo "Available scenarios:"
    @echo "  - file       (9 tasks)"
    @echo "  - weather    (9 tasks)"
    @echo "  - web        (9 tasks)"
    @echo "  - summarize  (9 tasks)"
    @echo "  - gmail      (9 tasks)"
    @echo "  - github     (9 tasks)"
    @echo "  - compound   (9 tasks)"
    @echo ""
    @echo "Total: 63 tasks across 7 scenarios"

# ============================================================================
# Single Scenario Attacks
# ============================================================================

# Attack a specific task in file scenario
crack-file task_index="0" malicious="exfil-http":
    uv run cracker crack \
        --scenario file \
        --task-index {{task_index}} \
        --malicious-task {{malicious}}

# Attack all tasks in file scenario
crack-file-all malicious="exfil-http":
    uv run cracker crack \
        --scenario file \
        --malicious-task {{malicious}} \
        --output results/file_{{malicious}}.json

# Attack github scenario
crack-github malicious="unauth-github":
    uv run cracker crack \
        --scenario github \
        --malicious-task {{malicious}} \
        --output results/github_{{malicious}}.json

# Attack web scenario
crack-web malicious="exfil-curl":
    uv run cracker crack \
        --scenario web \
        --malicious-task {{malicious}} \
        --output results/web_{{malicious}}.json

# Attack any scenario
crack scenario malicious task_index="":
    #!/usr/bin/env bash
    if [ -z "{{task_index}}" ]; then
        uv run cracker crack \
            --scenario {{scenario}} \
            --malicious-task {{malicious}} \
            --output results/{{scenario}}_{{malicious}}.json
    else
        uv run cracker crack \
            --scenario {{scenario}} \
            --task-index {{task_index}} \
            --malicious-task {{malicious}}
    fi

# ============================================================================
# Full Benchmarks
# ============================================================================

# Run full benchmark with exfiltration attack
benchmark-exfil agent="gpt-5-mini":
    uv run cracker benchmark \
        --malicious-task exfil-http \
        --agent-name {{agent}} \
        --output results/benchmark_exfil_{{agent}}.json

# Run full benchmark with backdoor attack
benchmark-backdoor agent="gpt-5-mini":
    uv run cracker benchmark \
        --malicious-task backdoor-file \
        --agent-name {{agent}} \
        --output results/benchmark_backdoor_{{agent}}.json

# Run full benchmark with credential leak attack
benchmark-creds agent="gpt-5-mini":
    uv run cracker benchmark \
        --malicious-task cred-leak-api \
        --agent-name {{agent}} \
        --output results/benchmark_creds_{{agent}}.json

# Run benchmark on selected scenarios only
benchmark-selected malicious scenarios agent="gpt-5-mini":
    uv run cracker benchmark \
        --malicious-task {{malicious}} \
        --scenarios "{{scenarios}}" \
        --agent-name {{agent}} \
        --output results/benchmark_{{malicious}}_selected.json

# Run full benchmark with custom settings
benchmark malicious agent="gpt-5-mini" backend="local" attacker="minimax/minimax-01" turns="5":
    uv run cracker benchmark \
        --malicious-task {{malicious}} \
        --agent-name {{agent}} \
        --backend {{backend}} \
        --attacker-model {{attacker}} \
        --max-turns {{turns}} \
        --output results/benchmark_{{malicious}}_{{agent}}.json

# ============================================================================
# Benchmark Sweeps (Test Multiple Attack Types)
# ============================================================================

# Run all exfiltration attacks
sweep-exfiltration agent="gpt-5-mini":
    @echo "Running exfiltration attack sweep..."
    just benchmark exfil-http {{agent}}
    just benchmark exfil-curl {{agent}}
    just benchmark exfil-csv {{agent}}
    @echo "✓ Exfiltration sweep complete!"

# Run all backdoor attacks
sweep-backdoor agent="gpt-5-mini":
    @echo "Running backdoor attack sweep..."
    just benchmark backdoor-file {{agent}}
    just benchmark backdoor-code {{agent}}
    @echo "✓ Backdoor sweep complete!"

# Run all credential leak attacks
sweep-credentials agent="gpt-5-mini":
    @echo "Running credential leak attack sweep..."
    just benchmark cred-leak-api {{agent}}
    just benchmark cred-leak-env {{agent}}
    @echo "✓ Credential leak sweep complete!"

# Run comprehensive sweep (all 12 malicious tasks)
sweep-all agent="gpt-5-mini":
    @echo "Running comprehensive attack sweep (12 tasks)..."
    @mkdir -p results/sweep_{{agent}}
    just benchmark exfil-http {{agent}}
    just benchmark exfil-curl {{agent}}
    just benchmark exfil-csv {{agent}}
    just benchmark backdoor-file {{agent}}
    just benchmark backdoor-code {{agent}}
    just benchmark cred-leak-api {{agent}}
    just benchmark cred-leak-env {{agent}}
    just benchmark sabotage-delete {{agent}}
    just benchmark sabotage-corrupt {{agent}}
    just benchmark unauth-email {{agent}}
    just benchmark unauth-github {{agent}}
    just benchmark unauth-web {{agent}}
    @echo "✓ Comprehensive sweep complete! Results in results/"

# ============================================================================
# Testing with Different Attacker Models
# ============================================================================

# Test with minimax attacker
test-minimax malicious="exfil-http":
    uv run cracker benchmark \
        --malicious-task {{malicious}} \
        --attacker-model minimax/minimax-01 \
        --output results/{{malicious}}_minimax.json

# Test with kimi attacker
test-kimi malicious="exfil-http":
    uv run cracker benchmark \
        --malicious-task {{malicious}} \
        --attacker-model kimi/moonshot-v1-32k \
        --output results/{{malicious}}_kimi.json

# Test with qwen attacker
test-qwen malicious="exfil-http":
    uv run cracker benchmark \
        --malicious-task {{malicious}} \
        --attacker-model qwen/qwen-2.5-72b-instruct \
        --output results/{{malicious}}_qwen.json

# Compare different attacker models on same malicious task
compare-attackers malicious="exfil-http":
    @echo "Testing {{malicious}} with different attacker models..."
    just test-minimax {{malicious}}
    just test-kimi {{malicious}}
    just test-qwen {{malicious}}
    @echo "✓ Attacker comparison complete!"

# ============================================================================
# Backend Testing
# ============================================================================

# Test with Daytona backend
test-daytona malicious="exfil-http":
    uv run cracker crack \
        --scenario file \
        --task-index 0 \
        --malicious-task {{malicious}} \
        --backend daytona

# Run benchmark with Daytona backend
benchmark-daytona malicious="exfil-http" agent="gpt-5-mini":
    uv run cracker benchmark \
        --malicious-task {{malicious}} \
        --agent-name {{agent}} \
        --backend daytona \
        --output results/benchmark_{{malicious}}_daytona.json

# ============================================================================
# Results Management
# ============================================================================

# Create results directory
setup-results:
    mkdir -p results

# Clean all results
clean-results:
    rm -rf results/*.json
    @echo "✓ Results cleaned"

# Archive results with timestamp
archive-results:
    #!/usr/bin/env bash
    timestamp=$(date +%Y%m%d_%H%M%S)
    mkdir -p archives
    tar -czf archives/results_${timestamp}.tar.gz results/
    echo "✓ Results archived to archives/results_${timestamp}.tar.gz"

# Show recent results
show-results:
    @echo "Recent benchmark results:"
    @ls -lht results/*.json 2>/dev/null || echo "No results yet"

# ============================================================================
# Development & Testing
# ============================================================================

# Run verbose mode for debugging
debug scenario="file" malicious="exfil-http":
    uv run cracker --verbose crack \
        --scenario {{scenario}} \
        --task-index 0 \
        --malicious-task {{malicious}}

# Quick test (single task, local backend)
quick-test:
    uv run cracker crack \
        --scenario file \
        --task-index 0 \
        --malicious-task exfil-http

# Run with increased attack turns
stress-test scenario="file" malicious="exfil-http" turns="10":
    uv run cracker crack \
        --scenario {{scenario}} \
        --malicious-task {{malicious}} \
        --max-turns {{turns}}

# ============================================================================
# Documentation & Reporting
# ============================================================================

# Generate summary of all results
summarize:
    @echo "Benchmark Results Summary"
    @echo "========================="
    @echo ""
    @for file in results/benchmark_*.json; do \
        if [ -f "$file" ]; then \
            echo "File: $(basename $file)"; \
            jq -r '"\nAttack Success Rate: \(.attack_success_rate)%\nUtility Preservation: \(.utility_preservation_rate)%\n"' "$file"; \
        fi \
    done

# Show malicious task categories
show-categories:
    @echo "Malicious Task Categories:"
    @echo ""
    @echo "EXFILTRATION (3 tasks)"
    @echo "  - exfil-http, exfil-curl, exfil-csv"
    @echo ""
    @echo "BACKDOOR (2 tasks)"
    @echo "  - backdoor-file, backdoor-code"
    @echo ""
    @echo "CREDENTIAL_LEAK (2 tasks)"
    @echo "  - cred-leak-api, cred-leak-env"
    @echo ""
    @echo "SABOTAGE (2 tasks)"
    @echo "  - sabotage-delete, sabotage-corrupt"
    @echo ""
    @echo "UNAUTHORIZED_ACTION (3 tasks)"
    @echo "  - unauth-email, unauth-github, unauth-web"

# ============================================================================
# Example Workflows
# ============================================================================

# Example: Full evaluation pipeline
example-full:
    @echo "Running full evaluation pipeline..."
    just setup-results
    just benchmark-exfil gpt-5-mini
    just benchmark-backdoor gpt-5-mini
    just benchmark-creds gpt-5-mini
    just summarize
    @echo "✓ Full evaluation complete!"

# Example: Quick scenario test
example-quick:
    @echo "Running quick scenario test..."
    just crack-file 0 exfil-http
    @echo "✓ Quick test complete!"

# Example: Compare scenarios for one attack
example-compare-scenarios malicious="exfil-http":
    @echo "Comparing scenarios for {{malicious}}..."
    just crack file {{malicious}}
    just crack github {{malicious}}
    just crack web {{malicious}}
    @echo "✓ Scenario comparison complete!"

# ============================================================================
# Maintenance
# ============================================================================

# Update openclawbench submodule
update-submodule:
    git submodule update --remote openclawbench
    @echo "✓ Submodule updated"

# Format code (if using ruff)
format:
    uv run ruff format src/

# Lint code
lint:
    uv run ruff check src/

# Clean Python cache files
clean-cache:
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    @echo "✓ Cache cleaned"

# Full cleanup
clean: clean-cache clean-results
    @echo "✓ Full cleanup complete"

# ============================================================================
# Help & Info
# ============================================================================

# Show example commands
examples:
    @echo "Example Commands:"
    @echo ""
    @echo "1. Quick single task test:"
    @echo "   just quick-test"
    @echo ""
    @echo "2. Full benchmark on one attack:"
    @echo "   just benchmark-exfil gpt-5-mini"
    @echo ""
    @echo "3. Attack specific scenario:"
    @echo "   just crack-file 0 exfil-http"
    @echo ""
    @echo "4. Compare attacker models:"
    @echo "   just compare-attackers exfil-http"
    @echo ""
    @echo "5. Full sweep of all attacks:"
    @echo "   just sweep-all gpt-5-mini"
    @echo ""
    @echo "6. Custom benchmark:"
    @echo "   just benchmark exfil-http gpt-5-mini daytona kimi/moonshot-v1-32k 10"

# Show configuration info
info:
    @echo "Cracker Configuration:"
    @echo "====================="
    @echo ""
    @echo "Malicious Tasks: 12"
    @echo "Scenarios: 7 (63 total tasks)"
    @echo "Backends: local, daytona"
    @echo "Default Attacker: minimax/minimax-01"
    @echo ""
    @echo "Environment variables:"
    @echo "  OPENROUTER_API_KEY - Required"
    @echo "  OPENAI_API_KEY - Required"
    @echo "  CRACKER_BACKEND - local or daytona"
    @echo "  ATTACKER_MODEL - OpenRouter model"
    @echo ""
    just check-config
