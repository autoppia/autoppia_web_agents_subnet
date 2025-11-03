import importlib

def test_validator_module_imports():
    module = importlib.import_module("neurons.validator")
    assert hasattr(module, "Validator")
