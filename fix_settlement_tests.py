#!/usr/bin/env python3
"""Script to add _bind_settlement_mixin helper to all test methods in test_settlement_mixin.py"""

import re

# Read the file
with open('tests/validator/unit/test_settlement_mixin.py', 'r') as f:
    content = f.read()

# Pattern to match async test methods that don't already have the helper
pattern = r'(    async def test_[^(]+\([^)]+\):\n)(        """[^"]+""")'

def replacement(match):
    method_def = match.group(1)
    docstring = match.group(2)
    # Add the helper import after the method definition and before docstring
    return f'{method_def}        from tests.conftest import _bind_settlement_mixin\n        dummy_validator = _bind_settlement_mixin(dummy_validator)\n        \n{docstring}'

# Replace all occurrences
new_content = re.sub(pattern, replacement, content)

# Write back
with open('tests/validator/unit/test_settlement_mixin.py', 'w') as f:
    f.write(new_content)

print("Updated test_settlement_mixin.py")
