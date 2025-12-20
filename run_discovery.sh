#!/bin/bash
#
# Run vision discovery on Greater Boston towns
#
# Usage:
#   ./run_discovery.sh              # Run all towns
#   ./run_discovery.sh --push       # Run all and push results to API
#   ./run_discovery.sh Newton       # Run single town
#   ./run_discovery.sh --start 10   # Start from line 10 (skip first 9 towns)
#

CSV_FILE="greater_boston_cities.csv"
STATE="MA"
PUSH_FLAG=""
START_LINE=1

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --push)
            PUSH_FLAG="--push"
            shift
            ;;
        --start)
            START_LINE="$2"
            shift 2
            ;;
        *)
            # Single town mode
            SINGLE_TOWN="$1"
            shift
            ;;
    esac
done

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Check Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "ERROR: Ollama is not running. Start it with: ollama serve"
    exit 1
fi

# Single town mode
if [ -n "$SINGLE_TOWN" ]; then
    echo "Processing single town: $SINGLE_TOWN"
    python discover.py "$SINGLE_TOWN" "$STATE" $PUSH_FLAG
    exit $?
fi

# Count total towns (excluding header)
TOTAL=$(tail -n +2 "$CSV_FILE" | grep -c .)
echo "========================================"
echo "Greater Boston Discovery Runner"
echo "========================================"
echo "Total towns: $TOTAL"
echo "Starting from: $START_LINE"
echo "Push to API: ${PUSH_FLAG:-no}"
echo "========================================"
echo ""

# Process each town
COUNT=0
PROCESSED=0
FAILED=0

tail -n +2 "$CSV_FILE" | while read -r TOWN; do
    COUNT=$((COUNT + 1))

    # Skip if before start line
    if [ $COUNT -lt $START_LINE ]; then
        continue
    fi

    # Skip empty lines
    if [ -z "$TOWN" ]; then
        continue
    fi

    PROCESSED=$((PROCESSED + 1))

    echo ""
    echo "========================================"
    echo "[$COUNT/$TOTAL] Processing: $TOWN, $STATE"
    echo "========================================"

    # Run discovery
    if python discover.py "$TOWN" "$STATE" $PUSH_FLAG; then
        echo "✓ Completed: $TOWN"
    else
        echo "✗ Failed: $TOWN"
        FAILED=$((FAILED + 1))
    fi

    # Small delay between towns to be nice to search engines
    echo "Waiting 5 seconds before next town..."
    sleep 5
done

echo ""
echo "========================================"
echo "DISCOVERY COMPLETE"
echo "========================================"
echo "Towns processed: $PROCESSED"
echo "Failed: $FAILED"
