#!/bin/bash

# Install QEMU and related tools
sudo apt-get update && sudo apt-get install -y \
    qemu-system-x86 \
    guestfish \
    qemu-utils \
    cloud-image-utils \
    dnsmasq

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
