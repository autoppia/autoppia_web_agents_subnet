#!/usr/bin/env python3
"""Script to add mixin bindings to integration tests"""

import re

files = [
    'tests/validator/integration/test_complete_round.py',
    'tests/validator/integration/test_multi_round.py'
]

for filepath in files:
    # Read the file
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Pattern to match async test methods that use validator_with_agents
    pattern = r'(    async def test_[^(]+\([^)]*validator_with_agents[^)]*\):\n)(        """[^"]+""")'
    
    def replacement(match):
        method_def = match.group(1)
        docstring = match.group(2)
        # Add the helper imports after the method definition and before docstring
        return f'{method_def}        from tests.conftest import _bind_evaluation_mixin, _bind_settlement_mixin, _bind_round_start_mixin\n        validator_with_agents = _bind_evaluation_mixin(validator_with_agents)\n        validator_with_agents = _bind_settlement_mixin(validator_with_agents)\n        validator_with_agents = _bind_round_start_mixin(validator_with_agents)\n        \n{docstring}'
    
    # Replace all occurrences
    new_content = re.sub(pattern, replacement, content)
    
    # Write back
    with open(filepath, 'w') as f:
        f.write(new_content)
    
    print(f"Updated {filepath}")
