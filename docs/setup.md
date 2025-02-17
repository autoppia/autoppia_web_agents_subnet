# Development Environment Setup

Script to setup Python development environment and install required modules.

## Requirements

- Python 3.11
- Git

## What it installs

1. Python environment:

   - Virtual environment in **/validator_env**
   - Updated pip and setuptools
   - Requirements from requirements.txt

2. Required modules:
   - Playwright
   - Current module in editable mode
   - autoppia_iwa module
   - Bittensor v9.0.0

## How to use

1. Make it executable:

```bash
chmod +x setup.sh
```

2. Run the script:

```bash
./setup.sh
```

## Important notes

- Creates and activates Python virtual environment
- Installs all Python dependencies
- Installs Playwright and its dependencies
- Clones and installs Bittensor from GitHub
