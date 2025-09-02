#!/bin/bash
# This script sets up the environment for the Podcast Generator.

# Change to the directory where the script is located to ensure paths are correct
cd "$(dirname "$0")"

# Exit on any error
set -e

VENV_DIR="venv"

if [ -d "$VENV_DIR" ]; then
    echo "--- Virtual environment already exists. Skipping creation. ---"
else
    echo "--- Setting up virtual environment in ./${VENV_DIR} ---"
    python3 -m venv $VENV_DIR
fi

echo "--- Activating virtual environment and installing dependencies... ---"
source "${VENV_DIR}/bin/activate"

# Install the project and its dependencies
pip install .

deactivate

echo ""
echo "--- Setup complete! ---"
echo "To run the application, execute the following command from the project directory:"
echo "./run.sh"
