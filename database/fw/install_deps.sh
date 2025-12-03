#!/bin/bash
# Install dependencies for running big data frameworks with Docker
set -euo pipefail

echo "=== Installing dependencies ==="

# Install Python 3
if command -v python3 &> /dev/null; then
    echo "Python 3 is already installed: $(python3 --version)"
else
    echo "Installing Python 3..."
    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y python3
    elif command -v dnf &> /dev/null; then
        sudo dnf install -y python3
    elif command -v yum &> /dev/null; then
        sudo yum install -y python3
    else
        echo "Error: Unsupported package manager"
        exit 1
    fi
    echo "Python 3 installed: $(python3 --version)"
fi

# Install Docker
if command -v docker &> /dev/null; then
    echo "Docker is already installed: $(docker --version)"
else
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed: $(docker --version)"
    echo "NOTE: Log out and back in for group changes to take effect"
fi

echo ""
echo "=== Done ==="
