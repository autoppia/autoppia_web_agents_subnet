#!/usr/bin/env python3
"""
Test file for topk.py behavior fingerprinting logic.
Tests the similarity detection between solutions.
"""

import sys
import os
from dataclasses import dataclass
from typing import List

# Add the validator directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from topk import compare_solutions, get_similarity_score, fingerprint_solution

# =========================
# Mock classes for testing
# =========================


@dataclass
class MockSelector:
    type: str = None
    attribute: str = None
    value: str = None


@dataclass
class MockAction:
    type: str
    selector: MockSelector = None
    text: str = None
    value: str = None
    url: str = None
    x: int = None
    y: int = None
    up: bool = False
    down: bool = False
    left: bool = False
    right: bool = False
    time_seconds: float = None


@dataclass
class MockSolution:
    miner_id: str
    task_id: str
    actions: List[MockAction]

# =========================
# Test data creation
# =========================


def create_identical_solutions():
    """Create two solutions that are essentially identical (should have high similarity)"""

    # Common actions for both solutions
    actions = [
        MockAction(
            type="clickaction",
            selector=MockSelector(type="attribute", attribute="data-testid", value="login-button")
        ),
        MockAction(
            type="typeaction",
            selector=MockSelector(type="attribute", attribute="name", value="username"),
            text="testuser"
        ),
        MockAction(
            type="typeaction", 
            selector=MockSelector(type="attribute", attribute="name", value="password"),
            text="password123"
        ),
        MockAction(
            type="clickaction",
            selector=MockSelector(type="attribute", attribute="data-testid", value="submit-btn")
        ),
        MockAction(
            type="waitaction",
            time_seconds=1.5
        )
    ]

    sol1 = MockSolution(miner_id="miner_1", task_id="task_login", actions=actions.copy())
    sol2 = MockSolution(miner_id="miner_2", task_id="task_login", actions=actions.copy())

    return sol1, sol2


def create_similar_solutions():
    """Create two solutions that are similar but with minor differences (should have medium similarity)"""

    # Base actions
    base_actions = [
        MockAction(
            type="clickaction",
            selector=MockSelector(type="attribute", attribute="data-testid", value="search-button")
        ),
        MockAction(
            type="typeaction",
            selector=MockSelector(type="attribute", attribute="name", value="query"),
            text="python tutorial"
        ),
        MockAction(
            type="clickaction",
            selector=MockSelector(type="attribute", attribute="data-testid", value="submit-search")
        )
    ]

    # Solution 1: with wait
    actions1 = base_actions + [
        MockAction(type="waitaction", time_seconds=2.0)
    ]

    # Solution 2: with scroll instead of wait
    actions2 = base_actions + [
        MockAction(type="scrollaction", down=True)
    ]

    sol1 = MockSolution(miner_id="miner_3", task_id="task_search", actions=actions1)
    sol2 = MockSolution(miner_id="miner_4", task_id="task_search", actions=actions2)

    return sol1, sol2


def create_different_solutions():
    """Create two solutions that are completely different (should have low similarity)"""

    # Solution 1: Login flow
    actions1 = [
        MockAction(
            type="navigateaction",
            url="https://example.com/login"
        ),
        MockAction(
            type="typeaction",
            selector=MockSelector(type="attribute", attribute="id", value="email"),
            text="user@example.com"
        ),
        MockAction(
            type="clickaction",
            selector=MockSelector(type="attribute", attribute="id", value="login-btn")
        )
    ]

    # Solution 2: Shopping flow
    actions2 = [
        MockAction(
            type="navigateaction",
            url="https://shop.example.com"
        ),
        MockAction(
            type="clickaction",
            selector=MockSelector(type="attribute", attribute="class", value="product-card")
        ),
        MockAction(
            type="clickaction",
            selector=MockSelector(type="attribute", attribute="data-testid", value="add-to-cart")
        ),
        MockAction(
            type="clickaction",
            selector=MockSelector(type="attribute", attribute="data-testid", value="checkout")
        )
    ]

    sol1 = MockSolution(miner_id="miner_5", task_id="task_different_1", actions=actions1)
    sol2 = MockSolution(miner_id="miner_6", task_id="task_different_2", actions=actions2)

    return sol1, sol2


def create_camouflaged_solutions():
    """Create solutions that try to hide similarity with minor variations (should still detect similarity)"""

    # Base pattern
    base_actions = [
        MockAction(
            type="clickaction",
            selector=MockSelector(type="attribute", attribute="data-testid", value="menu-button")
        ),
        MockAction(
            type="typeaction",
            selector=MockSelector(type="attribute", attribute="name", value="search"),
            text="test query"
        )
    ]

    # Solution 1: Original
    actions1 = base_actions + [
        MockAction(type="waitaction", time_seconds=1.0),
        MockAction(
            type="clickaction",
            selector=MockSelector(type="attribute", attribute="data-testid", value="search-btn")
        )
    ]

    # Solution 2: Camouflaged (different wait time, slightly different text)
    actions2 = base_actions + [
        MockAction(type="waitaction", time_seconds=1.2),  # Different wait time
        MockAction(
            type="clickaction",
            selector=MockSelector(type="attribute", attribute="data-testid", value="search-btn")
        )
    ]

    sol1 = MockSolution(miner_id="miner_7", task_id="task_camouflage", actions=actions1)
    sol2 = MockSolution(miner_id="miner_8", task_id="task_camouflage", actions=actions2)

    return sol1, sol2

# =========================
# Test functions
# =========================


def test_identical_solutions():
    """Test that identical solutions have high similarity"""
    print("=== Testing Identical Solutions ===")
    sol1, sol2 = create_identical_solutions()

    similarity = get_similarity_score(sol1, sol2)
    print(f"Similarity between identical solutions: {similarity:.4f}")

    # Should be very high similarity (> 0.8)
    assert similarity > 0.8, f"Expected high similarity for identical solutions, got {similarity}"
    print("✓ Identical solutions correctly identified as similar")
    return similarity


def test_similar_solutions():
    """Test that similar solutions have medium similarity"""
    print("\n=== Testing Similar Solutions ===")
    sol1, sol2 = create_similar_solutions()

    similarity = get_similarity_score(sol1, sol2)
    print(f"Similarity between similar solutions: {similarity:.4f}")

    # Should have medium similarity (0.3 - 0.8)
    assert 0.3 <= similarity <= 0.8, f"Expected medium similarity for similar solutions, got {similarity}"
    print("✓ Similar solutions correctly identified with medium similarity")
    return similarity


def test_different_solutions():
    """Test that different solutions have low similarity"""
    print("\n=== Testing Different Solutions ===")
    sol1, sol2 = create_different_solutions()

    similarity = get_similarity_score(sol1, sol2)
    print(f"Similarity between different solutions: {similarity:.4f}")

    # Should have low similarity (< 0.5)
    assert similarity < 0.5, f"Expected low similarity for different solutions, got {similarity}"
    print("✓ Different solutions correctly identified with low similarity")
    return similarity


def test_camouflaged_solutions():
    """Test that camouflaged solutions are still detected as similar"""
    print("\n=== Testing Camouflaged Solutions ===")
    sol1, sol2 = create_camouflaged_solutions()

    similarity = get_similarity_score(sol1, sol2)
    print(f"Similarity between camouflaged solutions: {similarity:.4f}")

    # Should still detect similarity despite camouflage (> 0.6)
    assert similarity > 0.6, f"Expected high similarity for camouflaged solutions, got {similarity}"
    print("✓ Camouflaged solutions correctly identified as similar")
    return similarity


def test_clustering():
    """Test the full clustering functionality"""
    print("\n=== Testing Clustering Functionality ===")

    # Create multiple solutions for clustering
    solutions = []

    # Add identical solutions (should cluster together)
    sol1, sol2 = create_identical_solutions()
    solutions.extend([sol1, sol2])

    # Add similar solutions (should cluster together)
    sol3, sol4 = create_similar_solutions()
    solutions.extend([sol3, sol4])

    # Add different solutions (should not cluster)
    sol5, sol6 = create_different_solutions()
    solutions.extend([sol5, sol6])

    # Add camouflaged solutions (should cluster together)
    sol7, sol8 = create_camouflaged_solutions()
    solutions.extend([sol7, sol8])

    # Run clustering
    clusters = compare_solutions(solutions, min_shared_tasks=1, tau=0.7)

    print("Clustering results:")
    for miner_id, cluster in clusters.items():
        print(f"  {miner_id}: {cluster}")

    # Check that identical solutions are clustered together
    miner_1_cluster = clusters.get("miner_1", [])
    miner_2_cluster = clusters.get("miner_2", [])

    assert "miner_2" in miner_1_cluster, "Identical solutions should be clustered together"
    assert "miner_1" in miner_2_cluster, "Identical solutions should be clustered together"
    print("✓ Clustering correctly groups identical solutions")

    return clusters


def test_fingerprint_details():
    """Test fingerprint generation and show details"""
    print("\n=== Testing Fingerprint Details ===")

    sol1, sol2 = create_identical_solutions()

    fp1 = fingerprint_solution(sol1)
    fp2 = fingerprint_solution(sol2)

    print(f"Solution 1 tokens: {len(fp1.tokens)}")
    print(f"Solution 2 tokens: {len(fp2.tokens)}")
    print(f"Solution 1 shingles: {len(fp1.shingles)}")
    print(f"Solution 2 shingles: {len(fp2.shingles)}")

    # Show first few tokens
    print(f"First 3 tokens from sol1: {fp1.tokens[:3]}")
    print(f"First 3 tokens from sol2: {fp2.tokens[:3]}")

    # Check if tokens are identical
    tokens_identical = fp1.tokens == fp2.tokens
    print(f"Tokens are identical: {tokens_identical}")

    if tokens_identical:
        print("✓ Canonicalization working correctly - identical actions produce identical tokens")
    else:
        print("⚠ Canonicalization may need adjustment")


def main():
    """Run all tests"""
    print("Starting behavior fingerprinting tests...\n")

    try:
        # Test individual similarity scores
        sim_identical = test_identical_solutions()
        sim_similar = test_similar_solutions()
        sim_different = test_different_solutions()
        sim_camouflaged = test_camouflaged_solutions()

        # Test clustering
        clusters = test_clustering()

        # Test fingerprint details
        test_fingerprint_details()

        # Summary
        print("\n=== Test Summary ===")
        print(f"Identical solutions similarity: {sim_identical:.4f}")
        print(f"Similar solutions similarity: {sim_similar:.4f}")
        print(f"Different solutions similarity: {sim_different:.4f}")
        print(f"Camouflaged solutions similarity: {sim_camouflaged:.4f}")
        print(f"Number of clusters found: {len(set(tuple(sorted(c)) for c in clusters.values()))}")

        print("\n✅ All tests passed! The behavior fingerprinting logic is working correctly.")

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
