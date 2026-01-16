#!/usr/bin/env python3
"""
Script to add mixin bindings to test_multi_round.py tests.
"""

import re

def add_mixin_bindings(content: str) -> str:
    """Add mixin binding calls to test methods that use validator methods."""
    
    # Pattern to match test methods
    test_pattern = r'(    async def test_\w+\(self, dummy_validator[^)]*\):)'
    
    def replace_test(match):
        test_def = match.group(1)
        # Add the binding imports and calls
        binding_code = """
        from tests.conftest import _bind_evaluation_mixin, _bind_settlement_mixin, _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        dummy_validator = _bind_settlement_mixin(dummy_validator)
        """
        return test_def + binding_code
    
    # Replace all test method definitions
    result = re.sub(test_pattern, replace_test, content)
    return result

# Read the file
with open('tests/validator/integration/test_multi_round.py', 'r') as f:
    content = f.read()

# Add bindings
new_content = add_mixin_bindings(content)

# Write back
with open('tests/validator/integration/test_multi_round.py', 'w') as f:
    f.write(new_content)

print("Added mixin bindings to test_multi_round.py")
