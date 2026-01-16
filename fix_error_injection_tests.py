#!/usr/bin/env python3
"""
Script to add mixin bindings to error_injection tests.
"""

import re

def add_mixin_bindings(content: str) -> str:
    """Add mixin binding calls to test methods that use validator methods."""
    
    # Pattern to match test methods that use _run_evaluation_phase
    eval_pattern = r'(    async def test_\w+\(self[^)]*validator_with_agents[^)]*\):)\n(        """[^"]*""")\n(        # Setup)'
    
    def replace_eval_test(match):
        test_def = match.group(1)
        docstring = match.group(2)
        setup_comment = match.group(3)
        # Add the binding imports and calls
        binding_code = f"""{test_def}
{docstring}
        from tests.conftest import _bind_evaluation_mixin
        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)
        
{setup_comment}"""
        return binding_code
    
    # Pattern for handshake tests
    handshake_pattern = r'(    async def test_\w+\(self[^)]*dummy_validator[^)]*\):)\n(        """[^"]*""")\n(        # Mock)'
    
    def replace_handshake_test(match):
        test_def = match.group(1)
        docstring = match.group(2)
        mock_comment = match.group(3)
        binding_code = f"""{test_def}
{docstring}
        from tests.conftest import _bind_round_start_mixin
        dummy_validator = _bind_round_start_mixin(dummy_validator)
        
{mock_comment}"""
        return binding_code
    
    # Apply replacements
    result = re.sub(eval_pattern, replace_eval_test, content)
    result = re.sub(handshake_pattern, replace_handshake_test, result)
    return result

# Read the file
with open('tests/validator/error_handling/test_error_injection.py', 'r') as f:
    content = f.read()

# Add bindings
new_content = add_mixin_bindings(content)

# Write back
with open('tests/validator/error_handling/test_error_injection.py', 'w') as f:
    f.write(new_content)

print("Added mixin bindings to test_error_injection.py")
