#!/bin/bash
# setup.sh - Setup application: create/activate virtual environment, install Python dependencies, and modules.

set -e

handle_error() {
  echo -e "\e[31m[ERROR]\e[0m $1" >&2
  exit 1
}

success_msg() {
  echo -e "\e[32m[SUCCESS]\e[0m $1"
}

check_python_version() {
  echo -e "\e[34m[INFO]\e[0m Checking Python version..."
  python3.11 --version || handle_error "Python 3.11 is required. Please install it."
}

create_and_activate_venv() {
  VENV_DIR="validator_env"
  echo -e "\e[34m[INFO]\e[0m Creating virtual environment..."
  if [ ! -d "$VENV_DIR" ]; then
    python3.11 -m venv "$VENV_DIR" || handle_error "Failed to create virtual environment"
    success_msg "Virtual environment created successfully."
  else
    echo -e "\e[32m[INFO]\e[0m Virtual environment already exists. Skipping."
  fi

  echo -e "\e[34m[INFO]\e[0m Activating virtual environment..."
  # shellcheck source=/dev/null
  source "$VENV_DIR/bin/activate" || handle_error "Failed to activate virtual environment"
}

upgrade_pip_setuptools() {
  echo -e "\e[34m[INFO]\e[0m Upgrading pip and setuptools..."
  python3.11 -m ensurepip
  pip install --upgrade pip setuptools || handle_error "Failed to upgrade pip and setuptools"
  success_msg "pip and setuptools upgraded successfully."
}

install_python_requirements() {
  echo -e "\e[34m[INFO]\e[0m Installing Python dependencies and Playwright..."
  pip install -r requirements.txt || handle_error "Failed to install Python dependencies"
  
  if ! python3.11 -m pip show playwright > /dev/null 2>&1; then
    echo -e "\e[34m[INFO]\e[0m Installing Playwright..."
    pip install playwright || handle_error "Failed to install Playwright"
  fi
  
  python3.11 -m playwright install || handle_error "Failed to install Playwright"
  playwright install-deps || handle_error "Failed to install Playwright dependencies"
  success_msg "Python dependencies and Playwright installed successfully."
  playwright install 
  
}

install_current_module() {
  echo -e "\e[34m[INFO]\e[0m Installing current module in editable mode..."
  pip install -e . || handle_error "Failed to install the current module in editable mode"
  success_msg "Current module installed in editable mode."
}

install_autoppia_iwa() {
  echo -e "\e[34m[INFO]\e[0m Installing autoppia_iwa module..."
  if cd autoppia_iwa && pip install -e . && cd ..; then
    success_msg "autoppia_iwa installed successfully."
  else
    handle_error "Failed to install autoppia_iwa module"
  fi
}

install_bittensor() {
  echo -e "\e[34m[INFO]\e[0m Installing Bittensor..."
  git clone https://github.com/opentensor/bittensor.git && cd bittensor && pip install . && pip install bittensor==9.0.0 && cd .. && rm -rf bittensor
  success_msg "Bittensor installed successfully."
}

main() {
  check_python_version
  create_and_activate_venv
  upgrade_pip_setuptools
  install_python_requirements
  install_current_module
  install_autoppia_iwa
  install_bittensor
  success_msg "Setup completed successfully!"
}

main "$@"
