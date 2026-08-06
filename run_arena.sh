#!/bin/bash
source .venv/bin/activate

if [ -z "$VALURA_API_KEY" ]; then
    echo "Error: VALURA_API_KEY environment variable is not set."
    echo "Usage: VALURA_API_KEY=your_key_here ./run_arena.sh"
    exit 1
fi

echo "Starting SUBMISSION mode..."
python client.py --key "$VALURA_API_KEY" --mode submission --seconds 4000 > submission.log 2>&1
echo "Starting FINAL mode..."
python client.py --key "$VALURA_API_KEY" --mode final --seconds 5000 > final.log 2>&1
echo "All done."
