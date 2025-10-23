import importlib
import os
import sys


def reload_config_with_env(env: dict[str, str]):
    # Backup and set env vars
    backup = {k: os.environ.get(k) for k in env}
    try:
        for k, v in env.items():
            if v is None and k in os.environ:
                del os.environ[k]
            elif v is not None:
                os.environ[k] = v
        # Reload module
        if 'autoppia_web_agents_subnet.validator.config' in sys.modules:
            del sys.modules['autoppia_web_agents_subnet.validator.config']
        import autoppia_web_agents_subnet.validator.config as cfg
        importlib.reload(cfg)
        return cfg
    finally:
        # Restore env
        for k, v in backup.items():
            if v is None and k in os.environ:
                del os.environ[k]
            elif v is not None:
                os.environ[k] = v


def test_settlement_fetch_fraction_defaults():
    cfg = reload_config_with_env({
        'TESTING': 'false',
        'FETCH_IPFS_VALIDATOR_PAYLOADS_AT_SETTLEMENT_FRACTION': None,
    })
    assert isinstance(cfg.FETCH_IPFS_VALIDATOR_PAYLOADS_AT_SETTLEMENT_FRACTION, float)
    assert abs(cfg.FETCH_IPFS_VALIDATOR_PAYLOADS_AT_SETTLEMENT_FRACTION - 0.5) < 1e-9


def test_settlement_fetch_fraction_override_prod():
    cfg = reload_config_with_env({
        'TESTING': 'false',
        'FETCH_IPFS_VALIDATOR_PAYLOADS_AT_SETTLEMENT_FRACTION': '0.3',
    })
    assert abs(cfg.FETCH_IPFS_VALIDATOR_PAYLOADS_AT_SETTLEMENT_FRACTION - 0.3) < 1e-9


def test_settlement_fetch_fraction_override_test():
    cfg = reload_config_with_env({
        'TESTING': 'true',
        'FETCH_IPFS_VALIDATOR_PAYLOADS_AT_SETTLEMENT_FRACTION': '0.5',
        'TEST_SETTLEMENT_FETCH_FRACTION': '0.7',
    })
    assert abs(cfg.FETCH_IPFS_VALIDATOR_PAYLOADS_AT_SETTLEMENT_FRACTION - 0.7) < 1e-9
