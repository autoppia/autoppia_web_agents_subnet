import importlib
import os
import sys
from contextlib import contextmanager


@contextmanager
def _env(**overrides: str | None):
    backup = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _reload_config():
    module_name = "autoppia_web_agents_subnet.validator.config"
    sys.modules.pop(module_name, None)
    cfg = importlib.import_module(module_name)
    importlib.reload(cfg)
    return cfg


def test_round_fetch_fraction_default_prod():
    with _env(TESTING="false"):
        cfg = _reload_config()
        assert isinstance(cfg.FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION, float)
        assert cfg.FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION == 0.95
        assert cfg.STOP_TASK_EVALUATION_AT_ROUND_FRACTION == 0.90


def test_round_fetch_fraction_override_prod():
    with _env(TESTING="false", FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION="0.4"):
        cfg = _reload_config()
        assert cfg.FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION == 0.4


def test_round_fetch_fraction_override_testing():
    with _env(TESTING="true", TEST_FETCH_TASK_FRACTION="0.8"):
        cfg = _reload_config()
        assert cfg.TESTING is True
        assert cfg.FETCH_IPFS_VALIDATOR_PAYLOADS_AT_ROUND_FRACTION == 0.8


def test_skip_round_fraction_override():
    with _env(TESTING="false", SKIP_ROUND_IF_STARTED_AFTER_FRACTION="0.5"):
        cfg = _reload_config()
        assert cfg.SKIP_ROUND_IF_STARTED_AFTER_FRACTION == 0.5
