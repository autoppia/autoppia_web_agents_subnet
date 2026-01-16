#!/usr/bin/env python3
"""Add dendrite_with_retries patch to integration tests"""

import re

files = [
    'tests/validator/integration/test_complete_round.py',
    'tests/validator/integration/test_multi_round.py'
]

for filepath in files:
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Pattern 1: Find patches that don't have dendrite_with_retries
    # Look for aggregate_scores_from_commitments patches without dendrite
    pattern1 = r"(with patch\('autoppia_web_agents_subnet\.validator\.settlement\.mixin\.aggregate_scores_from_commitments'\) as mock_aggregate:)\n(\s+)(mock_normalize\.return_value)"
    
    def add_dendrite_patch(match):
        patch_line = match.group(1)
        indent = match.group(2)
        next_line = match.group(3)
        return f"{patch_line}\n{indent}    with patch('autoppia_web_agents_subnet.validator.round_start.synapse_handler.dendrite_with_retries', new_callable=AsyncMock) as mock_dendrite:\n{indent}        {next_line}"
    
    new_content = re.sub(pattern1, add_dendrite_patch, content)
    
    # Add mock_dendrite.return_value = [] after mock_aggregate.return_value
    pattern2 = r"(mock_aggregate\.return_value = [^\n]+)\n(\s+)(# Run|await validator\._start_round)"
    
    def add_dendrite_return(match):
        aggregate_line = match.group(1)
        indent = match.group(2)
        next_line = match.group(3)
        # Check if mock_dendrite.return_value already exists
        if 'mock_dendrite.return_value' in content[max(0, match.start()-200):match.start()]:
            return match.group(0)
        return f"{aggregate_line}\n{indent}mock_dendrite.return_value = []  # No responses from miners\n{indent}\n{indent}{next_line}"
    
    new_content = re.sub(pattern2, add_dendrite_return, new_content)
    
    with open(filepath, 'w') as f:
        f.write(new_content)
    
    print(f"Updated {filepath}")
