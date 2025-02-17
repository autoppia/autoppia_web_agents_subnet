# Web Agents Subnet: Demo Webs

This repository contains a collection of demo web applications designed for testing and evaluating the **Bittensor Subnet 36** validators. Each web application serves as a **testing ground** for web interaction and **analysis capabilities**.

## Overview

The demo webs are containerized applications, each with its own Docker configuration. They are designed to run independently and serve as validation targets for the subnet's validators.

## Requirements

- Ubuntu/Debian-based system
- Docker and Docker Compose v2
- Minimum 8GB RAM recommended
- Minimum 20GB free disk space
- Processor: 2+ cores recommended

## Project Structure

Each web demo is contained in its own directory with a complete Docker setup:
```
demo-webs/
├── web_1_demo_django_jobs/
│   ├── docker-compose.yml
│   └── ...
├── web_2_demo_.../
│   ├── docker-compose.yml
│   └── ...
└── scripts/
    ├── install_docker.sh
    └── setup.sh
```

## Port Configuration

The demo webs are configured to run on consecutive ports starting from 8000. Each web application's port is defined in its respective `docker-compose.yml`:

```yaml
ports:
  - "8000:8001"  # First demo web
  - "8001:8001"  # Second demo web
  # etc...
```

## Installation & Deployment

### 1. Install Docker

First, install Docker and Docker Compose:

```bash
chmod +x scripts/install_docker.sh
./scripts/install_docker.sh
```

### 2. Deploy Demo Webs

Once Docker is installed, deploy the demo webs:

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

### 3. Verify Installation

Verify that all containers are running:

```bash
docker ps
```

You should see each demo web listed with its respective port mapping.

## Accessing the Demo Webs

After deployment, the demo webs will be available at:
- Web 1: `http://localhost:8000`
- Web 2: `http://localhost:8001`
- etc...

## Troubleshooting

If you encounter any issues:

1. Check container status:
```bash
docker ps -a
```

2. View container logs:
```bash
docker logs <container_name>
```

3. Ensure all required ports are available and not in use by other services.

## Support

If you need assistance:
- Open an issue in this repository
- Contact the Subnet 36 team:
  - **@Daryxx** on Discord
  - **@Riiveer** on Discord
  - **@Miguelik** on Discord