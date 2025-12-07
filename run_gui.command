#!/bin/bash

# Get the directory where the script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Check if venv exists
if [ ! -d "$DIR/venv" ]; then
    echo "Virtual environment not found. Please run ./install.command first."
    exit 1
fi

# Run the GUI using the python in the venv
"$DIR/venv/bin/python" "$DIR/gui.py"
