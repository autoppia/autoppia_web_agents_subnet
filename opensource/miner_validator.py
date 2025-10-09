"""
Validation system for miner repository structure and compliance.
"""
import asyncio
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import structlog
from git import Repo, GitCommandError

logger = structlog.get_logger(__name__)


class MinerRepositoryValidator:
    """Validates miner repositories against the Autoppia standard."""

    def __init__(self):
        self.validation_rules = {
            "required_files": [
                "docker-compose.yml",
                "agent/Dockerfile",
                "agent/main.py",
                "agent/requirements.txt",
                "README.md"
            ],
            "required_directories": [
                "agent"
            ],
            "docker_compose_requirements": {
                "services": ["agent"],
                "agent_service": {
                    "ports": ["8000:8000"],
                    "healthcheck": True,
                    "labels": ["autoppia.miner=true"],
                    "networks": ["deployer_network"]
                }
            },
            "api_endpoints": [
                "/health",
                "/api/task",
                "/api/info"
            ]
        }

    async def validate_repository(self, github_url: str, branch: str = "main") -> Dict:
        """
        Validate a miner repository against the Autoppia standard.

        Returns:
            Dict with validation results and detailed feedback
        """
        validation_result = {
            "valid": False,
            "github_url": github_url,
            "branch": branch,
            "checks": {},
            "errors": [],
            "warnings": [],
            "suggestions": []
        }

        temp_dir = None
        try:
            # Clone repository to temporary directory
            temp_dir = tempfile.mkdtemp(prefix="miner_validation_")
            repo_dir = Path(temp_dir)

            logger.info("Cloning repository for validation", 
                        github_url=github_url, 
                        branch=branch,
                        temp_dir=temp_dir)

            repo = Repo.clone_from(github_url, repo_dir, branch=branch)
            commit_sha = repo.head.commit.hexsha

            validation_result["commit_sha"] = commit_sha

            # Run all validation checks
            await self._check_required_files(repo_dir, validation_result)
            await self._check_required_directories(repo_dir, validation_result)
            await self._check_docker_compose(repo_dir, validation_result)
            await self._check_agent_structure(repo_dir, validation_result)
            await self._check_readme(repo_dir, validation_result)

            # Determine overall validity
            validation_result["valid"] = len(validation_result["errors"]) == 0

            logger.info("Repository validation completed", 
                        github_url=github_url,
                        valid=validation_result["valid"],
                        errors=len(validation_result["errors"]),
                        warnings=len(validation_result["warnings"]))

        except GitCommandError as e:
            validation_result["errors"].append(f"Failed to clone repository: {e}")
            logger.error("Failed to clone repository for validation", 
                         github_url=github_url, 
                         error=str(e))
        except Exception as e:
            validation_result["errors"].append(f"Validation error: {e}")
            logger.error("Repository validation failed", 
                         github_url=github_url, 
                         error=str(e))
        finally:
            # Clean up temporary directory
            if temp_dir:
                import shutil
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    logger.warning("Failed to clean up temp directory", 
                                   temp_dir=temp_dir, 
                                   error=str(e))

        return validation_result

    async def _check_required_files(self, repo_dir: Path, result: Dict):
        """Check for required files."""
        check_name = "required_files"
        result["checks"][check_name] = {"passed": True, "details": {}}

        for file_path in self.validation_rules["required_files"]:
            full_path = repo_dir / file_path
            exists = full_path.exists()
            result["checks"][check_name]["details"][file_path] = exists

            if not exists:
                result["checks"][check_name]["passed"] = False
                result["errors"].append(f"Required file missing: {file_path}")

    async def _check_required_directories(self, repo_dir: Path, result: Dict):
        """Check for required directories."""
        check_name = "required_directories"
        result["checks"][check_name] = {"passed": True, "details": {}}

        for dir_path in self.validation_rules["required_directories"]:
            full_path = repo_dir / dir_path
            exists = full_path.exists() and full_path.is_dir()
            result["checks"][check_name]["details"][dir_path] = exists

            if not exists:
                result["checks"][check_name]["passed"] = False
                result["errors"].append(f"Required directory missing: {dir_path}")

    async def _check_docker_compose(self, repo_dir: Path, result: Dict):
        """Check docker-compose.yml structure."""
        check_name = "docker_compose"
        result["checks"][check_name] = {"passed": True, "details": {}}

        compose_file = repo_dir / "docker-compose.yml"
        if not compose_file.exists():
            result["checks"][check_name]["passed"] = False
            result["errors"].append("docker-compose.yml not found")
            return

        try:
            import yaml
            with open(compose_file, 'r') as f:
                compose_config = yaml.safe_load(f)

            # Check services
            services = compose_config.get('services', {})
            result["checks"][check_name]["details"]["has_services"] = bool(services)

            if not services:
                result["checks"][check_name]["passed"] = False
                result["errors"].append("No services defined in docker-compose.yml")
                return

            # Check agent service
            agent_service = services.get('agent')
            result["checks"][check_name]["details"]["has_agent_service"] = agent_service is not None

            if not agent_service:
                result["checks"][check_name]["passed"] = False
                result["errors"].append("Agent service not found in docker-compose.yml")
                return

            # Check port mapping
            ports = agent_service.get('ports', [])
            port_8000_mapped = any('8000:8000' in str(port) for port in ports)
            result["checks"][check_name]["details"]["port_8000_mapped"] = port_8000_mapped

            if not port_8000_mapped:
                result["checks"][check_name]["passed"] = False
                result["errors"].append("Port 8000 not mapped in agent service")

            # Check health check
            has_healthcheck = 'healthcheck' in agent_service
            result["checks"][check_name]["details"]["has_healthcheck"] = has_healthcheck

            if not has_healthcheck:
                result["checks"][check_name]["passed"] = False
                result["errors"].append("Health check not configured in agent service")

            # Check labels
            labels = agent_service.get('labels', [])
            has_autoppia_label = any('autoppia.miner=true' in str(label) for label in labels)
            result["checks"][check_name]["details"]["has_autoppia_label"] = has_autoppia_label

            if not has_autoppia_label:
                result["checks"][check_name]["passed"] = False
                result["errors"].append("Missing 'autoppia.miner=true' label in agent service")

            # Check networks
            networks = agent_service.get('networks', [])
            has_deployer_network = 'deployer_network' in str(networks)
            result["checks"][check_name]["details"]["has_deployer_network"] = has_deployer_network

            if not has_deployer_network:
                result["checks"][check_name]["passed"] = False
                result["errors"].append("Agent service not configured to use deployer_network")

        except yaml.YAMLError as e:
            result["checks"][check_name]["passed"] = False
            result["errors"].append(f"Invalid YAML in docker-compose.yml: {e}")
        except Exception as e:
            result["checks"][check_name]["passed"] = False
            result["errors"].append(f"Error parsing docker-compose.yml: {e}")

    async def _check_agent_structure(self, repo_dir: Path, result: Dict):
        """Check agent directory structure and files."""
        check_name = "agent_structure"
        result["checks"][check_name] = {"passed": True, "details": {}}

        agent_dir = repo_dir / "agent"
        if not agent_dir.exists():
            result["checks"][check_name]["passed"] = False
            result["errors"].append("Agent directory not found")
            return

        # Check Dockerfile
        dockerfile = agent_dir / "Dockerfile"
        has_dockerfile = dockerfile.exists()
        result["checks"][check_name]["details"]["has_dockerfile"] = has_dockerfile

        if has_dockerfile:
            # Check Dockerfile content
            try:
                with open(dockerfile, 'r') as f:
                    dockerfile_content = f.read()

                # Check for required elements
                exposes_8000 = "EXPOSE 8000" in dockerfile_content
                result["checks"][check_name]["details"]["exposes_port_8000"] = exposes_8000

                if not exposes_8000:
                    result["warnings"].append("Dockerfile should expose port 8000")

                has_healthcheck = "HEALTHCHECK" in dockerfile_content
                result["checks"][check_name]["details"]["has_healthcheck"] = has_healthcheck

                if not has_healthcheck:
                    result["warnings"].append("Dockerfile should include health check")

            except Exception as e:
                result["warnings"].append(f"Could not read Dockerfile: {e}")

        # Check main.py
        main_py = agent_dir / "main.py"
        has_main_py = main_py.exists()
        result["checks"][check_name]["details"]["has_main_py"] = has_main_py

        if has_main_py:
            # Check for required API endpoints
            try:
                with open(main_py, 'r') as f:
                    main_content = f.read()

                # Check for FastAPI app
                has_fastapi = "FastAPI" in main_content or "from fastapi" in main_content
                result["checks"][check_name]["details"]["uses_fastapi"] = has_fastapi

                if not has_fastapi:
                    result["warnings"].append("main.py should use FastAPI")

                # Check for required endpoints
                for endpoint in self.validation_rules["api_endpoints"]:
                    endpoint_check = f'"{endpoint}"' in main_content or f"'{endpoint}'" in main_content
                    result["checks"][check_name]["details"][f"has_{endpoint.replace('/', '_').replace('.', '_')}"] = endpoint_check

                    if not endpoint_check:
                        result["warnings"].append(f"main.py should implement {endpoint} endpoint")

            except Exception as e:
                result["warnings"].append(f"Could not read main.py: {e}")

        # Check requirements.txt
        requirements = agent_dir / "requirements.txt"
        has_requirements = requirements.exists()
        result["checks"][check_name]["details"]["has_requirements"] = has_requirements

        if has_requirements:
            try:
                with open(requirements, 'r') as f:
                    requirements_content = f.read()

                # Check for common dependencies
                has_fastapi = "fastapi" in requirements_content.lower()
                result["checks"][check_name]["details"]["has_fastapi_dependency"] = has_fastapi

                if not has_fastapi:
                    result["warnings"].append("requirements.txt should include fastapi")

            except Exception as e:
                result["warnings"].append(f"Could not read requirements.txt: {e}")

    async def _check_readme(self, repo_dir: Path, result: Dict):
        """Check README.md content."""
        check_name = "readme"
        result["checks"][check_name] = {"passed": True, "details": {}}

        readme_file = repo_dir / "README.md"
        if not readme_file.exists():
            result["checks"][check_name]["passed"] = False
            result["errors"].append("README.md not found")
            return

        try:
            with open(readme_file, 'r') as f:
                readme_content = f.read()

            # Check for required sections
            has_description = len(readme_content.strip()) > 50
            result["checks"][check_name]["details"]["has_description"] = has_description

            if not has_description:
                result["warnings"].append("README.md should include a description")

            has_quick_start = "quick start" in readme_content.lower() or "docker-compose" in readme_content.lower()
            result["checks"][check_name]["details"]["has_quick_start"] = has_quick_start

            if not has_quick_start:
                result["warnings"].append("README.md should include quick start instructions")

            has_api_docs = "api" in readme_content.lower() or "endpoint" in readme_content.lower()
            result["checks"][check_name]["details"]["has_api_docs"] = has_api_docs

            if not has_api_docs:
                result["warnings"].append("README.md should document API endpoints")

        except Exception as e:
            result["warnings"].append(f"Could not read README.md: {e}")

    def generate_validation_report(self, validation_result: Dict) -> str:
        """Generate a human-readable validation report."""
        report = []
        report.append("=" * 60)
        report.append("AUTOPPIA MINER REPOSITORY VALIDATION REPORT")
        report.append("=" * 60)
        report.append(f"Repository: {validation_result['github_url']}")
        report.append(f"Branch: {validation_result['branch']}")
        if 'commit_sha' in validation_result:
            report.append(f"Commit: {validation_result['commit_sha']}")
        report.append(f"Valid: {'✅ YES' if validation_result['valid'] else '❌ NO'}")
        report.append("")

        # Summary
        report.append("SUMMARY:")
        report.append(f"  Errors: {len(validation_result['errors'])}")
        report.append(f"  Warnings: {len(validation_result['warnings'])}")
        report.append(f"  Suggestions: {len(validation_result['suggestions'])}")
        report.append("")

        # Check results
        report.append("CHECK RESULTS:")
        for check_name, check_result in validation_result['checks'].items():
            status = "✅ PASS" if check_result['passed'] else "❌ FAIL"
            report.append(f"  {check_name}: {status}")

            if 'details' in check_result:
                for detail_name, detail_result in check_result['details'].items():
                    detail_status = "✅" if detail_result else "❌"
                    report.append(f"    {detail_name}: {detail_status}")
        report.append("")

        # Errors
        if validation_result['errors']:
            report.append("ERRORS:")
            for error in validation_result['errors']:
                report.append(f"  ❌ {error}")
            report.append("")

        # Warnings
        if validation_result['warnings']:
            report.append("WARNINGS:")
            for warning in validation_result['warnings']:
                report.append(f"  ⚠️  {warning}")
            report.append("")

        # Suggestions
        if validation_result['suggestions']:
            report.append("SUGGESTIONS:")
            for suggestion in validation_result['suggestions']:
                report.append(f"  💡 {suggestion}")
            report.append("")

        # Next steps
        if not validation_result['valid']:
            report.append("NEXT STEPS:")
            report.append("  1. Fix all errors listed above")
            report.append("  2. Review warnings and suggestions")
            report.append("  3. Follow the Autoppia Miner Repository Standard")
            report.append("  4. Test locally with: docker-compose up")
            report.append("  5. Re-validate your repository")
        else:
            report.append("CONGRATULATIONS!")
            report.append("  Your repository is compliant with the Autoppia standard.")
            report.append("  You can now submit it for evaluation.")

        report.append("=" * 60)

        return "\n".join(report)
