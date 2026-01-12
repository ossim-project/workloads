#!/bin/bash
set -euo pipefail

sudo apt-get update && sudo apt-get install -y \
    python3 python-is-python3 fio
