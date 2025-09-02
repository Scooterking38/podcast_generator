#!/bin/bash
# This script runs the podcast generator TUI using the project's virtual environment.
# It must be run from the project root directory.

# The name of the virtual environment directory.
VENV_DIR="venv"

# Activate the virtual environment, run the command, and then deactivate upon exit.
source "${VENV_DIR}/bin/activate"
python3 podcast_generator_v5.py "$@"

# The deactivate command will run after the podcast-generator command finishes.
deactivate