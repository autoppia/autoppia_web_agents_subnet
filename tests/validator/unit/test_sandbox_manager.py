"""
Unit tests for SandboxManager.

Tests agent deployment, health checks, and cleanup.
Note: Some tests require Docker and are marked with @pytest.mark.requires_docker
"""

import pytest
from unittest.mock import Mock, patch, MagicMock


@pytest.mark.unit
class TestAgentDeployment:
    """Test agent deployment logic."""

    @pytest.mark.requires_docker
    def test_deploy_agent_clones_repo_and_starts_container(self):
        """Test that deploy_agent clones repo and starts container."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager
        
        with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.get_client') as mock_client:
            with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.ensure_network'):
                with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.clone_repo'):
                    with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.temp_workdir') as mock_temp:
                        mock_temp.return_value = "/tmp/test"
                        mock_docker = MagicMock()
                        mock_client.return_value = mock_docker
                        
                        # Mock container
                        mock_container = Mock()
                        mock_container.attrs = {
                            "NetworkSettings": {
                                "Ports": {
                                    "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8001"}]
                                }
                            }
                        }
                        mock_docker.containers.run.return_value = mock_container
                        
                        manager = SandboxManager()
                        agent = manager.deploy_agent(1, "https://github.com/test/agent")
                        
                        assert agent is not None
                        assert agent.uid == 1

    @pytest.mark.requires_docker
    def test_deployment_handles_clone_timeout(self):
        """Test that deployment handles clone timeout gracefully."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager
        
        with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.get_client') as mock_client:
            with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.ensure_network'):
                with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.clone_repo') as mock_clone:
                    mock_clone.side_effect = TimeoutError("Clone timeout")
                    mock_docker = MagicMock()
                    mock_client.return_value = mock_docker
                    
                    manager = SandboxManager()
                    agent = manager.deploy_agent(1, "https://github.com/test/agent")
                    
                    # Should return None on failure
                    assert agent is None

    @pytest.mark.requires_docker
    def test_deployment_configures_environment_variables(self):
        """Test that deployment configures correct environment variables."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager
        
        with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.get_client') as mock_client:
            with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.ensure_network'):
                with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.clone_repo'):
                    with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.temp_workdir') as mock_temp:
                        mock_temp.return_value = "/tmp/test"
                        mock_docker = MagicMock()
                        mock_client.return_value = mock_docker
                        
                        mock_container = Mock()
                        mock_container.attrs = {"NetworkSettings": {}}
                        mock_docker.containers.run.return_value = mock_container
                        
                        manager = SandboxManager()
                        manager.deploy_agent(1, "https://github.com/test/agent")
                        
                        # Check that environment variables were set
                        call_kwargs = mock_docker.containers.run.call_args[1]
                        env = call_kwargs['environment']
                        assert 'SANDBOX_GATEWAY_URL' in env
                        assert 'HTTP_PROXY' in env
                        assert 'HTTPS_PROXY' in env

    @pytest.mark.requires_docker
    def test_deployment_exposes_correct_port(self):
        """Test that deployment exposes the agent port."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager
        
        with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.get_client') as mock_client:
            with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.ensure_network'):
                with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.clone_repo'):
                    with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.temp_workdir') as mock_temp:
                        mock_temp.return_value = "/tmp/test"
                        mock_docker = MagicMock()
                        mock_client.return_value = mock_docker
                        
                        mock_container = Mock()
                        mock_container.attrs = {"NetworkSettings": {}}
                        mock_docker.containers.run.return_value = mock_container
                        
                        manager = SandboxManager()
                        manager.deploy_agent(1, "https://github.com/test/agent")
                        
                        # Check that port was exposed
                        call_kwargs = mock_docker.containers.run.call_args[1]
                        assert '8000/tcp' in call_kwargs['ports']


@pytest.mark.unit
class TestHealthCheck:
    """Test health check logic."""

    def test_health_check_verifies_health_endpoint(self):
        """Test that health_check verifies /health endpoint."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import AgentInstance
        
        mock_container = Mock()
        mock_container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8001"}]
                }
            }
        }
        agent = AgentInstance(uid=1, container=mock_container, temp_dir="/tmp/test", port=8000)
        
        with patch('httpx.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager
            manager = SandboxManager.__new__(SandboxManager)
            
            result = manager.health_check(agent, timeout=5)
            
            assert result is True
            mock_get.assert_called()

    def test_health_check_retries_with_timeout(self):
        """Test that health_check retries until timeout."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import AgentInstance
        
        mock_container = Mock()
        mock_container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8001"}]
                }
            }
        }
        agent = AgentInstance(uid=1, container=mock_container, temp_dir="/tmp/test", port=8000)
        
        with patch('httpx.get') as mock_get:
            with patch('time.sleep'):
                with patch('time.time', side_effect=[0, 1, 2, 3, 4, 5, 6]):
                    mock_get.side_effect = Exception("Connection refused")
                    
                    from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager
                    manager = SandboxManager.__new__(SandboxManager)
                    
                    result = manager.health_check(agent, timeout=5)
                    
                    assert result is False

    def test_health_check_returns_false_on_failure(self):
        """Test that health_check returns False when endpoint fails."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import AgentInstance
        
        mock_container = Mock()
        mock_container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8001"}]
                }
            }
        }
        agent = AgentInstance(uid=1, container=mock_container, temp_dir="/tmp/test", port=8000)
        
        with patch('httpx.get') as mock_get:
            with patch('time.sleep'):
                with patch('time.time', side_effect=[0, 1, 2, 3, 4, 5, 6]):
                    mock_response = Mock()
                    mock_response.status_code = 500
                    mock_get.return_value = mock_response
                    
                    from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager
                    manager = SandboxManager.__new__(SandboxManager)
                    
                    result = manager.health_check(agent, timeout=5)
                    
                    assert result is False


@pytest.mark.unit
class TestCleanup:
    """Test cleanup logic."""

    def test_cleanup_agent_stops_container_and_removes_files(self):
        """Test that cleanup_agent stops container and removes temp directory."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager, AgentInstance
        
        with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.get_client') as mock_client:
            with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.ensure_network'):
                with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.stop_and_remove') as mock_stop:
                    with patch('shutil.rmtree') as mock_rmtree:
                        mock_docker = MagicMock()
                        mock_client.return_value = mock_docker
                        
                        manager = SandboxManager()
                        
                        # Add an agent
                        mock_container = Mock()
                        agent = AgentInstance(uid=1, container=mock_container, temp_dir="/tmp/test", port=8000)
                        manager._agents[1] = agent
                        
                        manager.cleanup_agent(1)
                        
                        # Should have stopped container and removed files
                        mock_stop.assert_called_once_with(mock_container)
                        mock_rmtree.assert_called_once_with("/tmp/test", ignore_errors=True)

    def test_cleanup_all_agents_cleans_up_all_agents(self):
        """Test that cleanup_all_agents cleans up all deployed agents."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager, AgentInstance
        
        with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.get_client') as mock_client:
            with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.ensure_network'):
                with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.stop_and_remove'):
                    with patch('shutil.rmtree'):
                        mock_docker = MagicMock()
                        mock_client.return_value = mock_docker
                        
                        manager = SandboxManager()
                        
                        # Add multiple agents
                        for uid in [1, 2, 3]:
                            mock_container = Mock()
                            agent = AgentInstance(uid=uid, container=mock_container, temp_dir=f"/tmp/test{uid}", port=8000)
                            manager._agents[uid] = agent
                        
                        manager.cleanup_all_agents()
                        
                        # All agents should be removed
                        assert len(manager._agents) == 0

    def test_cleanup_handles_missing_agents_gracefully(self):
        """Test that cleanup handles missing agents without errors."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager
        
        with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.get_client') as mock_client:
            with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.ensure_network'):
                mock_docker = MagicMock()
                mock_client.return_value = mock_docker
                
                manager = SandboxManager()
                
                # Try to cleanup non-existent agent
                manager.cleanup_agent(999)  # Should not raise exception


@pytest.mark.unit
class TestBaseUrl:
    """Test base_url property logic."""

    def test_base_url_prefers_host_port_mapping(self):
        """Test that base_url prefers host port mapping."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import AgentInstance
        
        mock_container = Mock()
        mock_container.attrs = {
            "NetworkSettings": {
                "Ports": {
                    "8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8001"}]
                },
                "Networks": {
                    "sandbox-network": {"IPAddress": "172.18.0.5"}
                }
            }
        }
        
        agent = AgentInstance(uid=1, container=mock_container, temp_dir="/tmp/test", port=8000)
        
        # Should prefer host port mapping
        assert agent.base_url == "http://127.0.0.1:8001"

    def test_base_url_falls_back_to_container_ip(self):
        """Test that base_url falls back to container IP when no port mapping."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import AgentInstance
        
        mock_container = Mock()
        mock_container.attrs = {
            "NetworkSettings": {
                "Ports": {},
                "Networks": {
                    "sandbox-network": {"IPAddress": "172.18.0.5"}
                }
            }
        }
        
        agent = AgentInstance(uid=1, container=mock_container, temp_dir="/tmp/test", port=8000)
        
        # Should use container IP
        assert agent.base_url == "http://172.18.0.5:8000"


@pytest.mark.unit
class TestGateway:
    """Test gateway initialization."""

    def test_gateway_is_initialized_with_correct_target(self):
        """Test that gateway is initialized with correct target URL."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager
        
        with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.get_client') as mock_client:
            with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.ensure_network'):
                with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.cleanup_containers'):
                    mock_docker = MagicMock()
                    mock_client.return_value = mock_docker
                    
                    # Mock image exists
                    mock_docker.images.get.return_value = Mock()
                    
                    manager = SandboxManager()
                    
                    # Should have created gateway container
                    mock_docker.containers.run.assert_called()
                    call_kwargs = mock_docker.containers.run.call_args[1]
                    assert call_kwargs['name'] == 'sandbox-gateway'

    def test_gateway_container_is_created_on_sandbox_network(self):
        """Test that gateway container is created on sandbox network."""
        from autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager import SandboxManager
        
        with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.get_client') as mock_client:
            with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.ensure_network'):
                with patch('autoppia_web_agents_subnet.opensource.sandbox.sandbox_manager.cleanup_containers'):
                    mock_docker = MagicMock()
                    mock_client.return_value = mock_docker
                    
                    # Mock image exists
                    mock_docker.images.get.return_value = Mock()
                    
                    manager = SandboxManager()
                    
                    # Check network configuration
                    call_kwargs = mock_docker.containers.run.call_args[1]
                    assert call_kwargs['network'] == 'sandbox-network'