#!/bin/bash
# Activation script for the agent analyzer
# Usage: source run.sh  (or . run.sh)

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install python-dotenv tree-sitter tree-sitter-python networkx anthropic click rich
else
    source venv/bin/activate
fi

echo "✅ Virtual environment activated!"
echo "You can now run: python analyze.py <path-to-agent>"
