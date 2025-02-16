# System Dependencies Installation

Script to automatically install all required system dependencies for the development environment.

## Requirements

- Ubuntu (tested on Jammy and Noble)
- Sudo privileges

## What it installs

1. System packages:

   - Python 3.11 with development tools
   - Build tools (cmake, build-essential)
   - Browser dependencies
   - Multimedia libraries

2. Node.js tools:

   - npm
   - PM2 process manager

3. Browser tools:
   - Chrome
   - ChromeDriver

## How to use

1. Make it executable:

```bash
chmod +x install_dependencies.sh
```

2. Run the script:

```bash
./install_dependencies.sh
```

## Important notes

- The script will update your system packages
- Chrome version: 127.0.6533.72
- Installations are done in:
  - Chrome: **/opt/chrome**
  - ChromeDriver: **/opt/chromedriver**
