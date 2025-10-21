#!/usr/bin/env python3
"""
Script simplificado para entender cómo funciona get_task_collection.
Muestra el flujo lógico sin ejecutar la generación real de tareas.
"""
import math


def split_tasks_evenly(total_tasks: int, num_projects: int) -> list:
    """Distribute tasks evenly across projects."""
    base = total_tasks // num_projects
    remainder = total_tasks % num_projects

    distribution = [base] * num_projects
    # Distribute remainder from the end
    for i in range(remainder):
        distribution[-(i + 1)] += 1

    return distribution


def simulate_get_task_collection(num_demo_projects: int, prompts_per_use_case: int):
    """
    Simula la lógica de get_task_collection sin ejecutar código real.
    """
    print("=" * 80)
    print(f"🧪 SIMULATING get_task_collection()")
    print(f"   Demo projects available: {num_demo_projects}")
    print(f"   Prompts per use case: {prompts_per_use_case}")
    print("=" * 80)
    print()

    # Lógica actual de get_task_collection
    total_prompts = num_demo_projects  # línea 92: total_prompts = num_projects

    print(f"📊 CALCULATION:")
    print(f"   total_prompts = num_projects = {total_prompts}")
    print()

    if total_prompts <= 0:
        print("⚠️  total_prompts <= 0 -> returning empty TaskPlan")
        return

    if num_demo_projects == 0:
        print("⚠️  no demo_web_projects found -> returning empty TaskPlan")
        return

    # Distribute tasks evenly
    task_distribution = split_tasks_evenly(total_prompts, num_demo_projects)

    print(f"📦 TASK DISTRIBUTION:")
    print(f"   {task_distribution}")
    print(f"   (distributing {total_prompts} tasks across {num_demo_projects} projects)")
    print()

    # Calculate use cases per project
    use_cases_per_project = max(1, math.ceil(total_prompts / max(1, num_demo_projects)))

    print(f"🎯 USE CASES PER PROJECT:")
    print(f"   use_cases_per_project = max(1, ceil({total_prompts} / {num_demo_projects}))")
    print(f"   use_cases_per_project = {use_cases_per_project}")
    print()

    print(f"🔧 WHAT HAPPENS NEXT (for each project):")
    print(f"   For each project, _generate_tasks_limited_use_cases() is called with:")
    print()

    for i, num_tasks in enumerate(task_distribution, 1):
        project_name = f"Project_{i}"
        print(f"   📁 {project_name}:")
        print(f"      - total_tasks: {num_tasks}")
        print(f"      - prompts_per_use_case: {prompts_per_use_case}")
        print(f"      - num_use_cases: {use_cases_per_project}")
        print(f"      → Generates up to {num_tasks} tasks using {use_cases_per_project} use-cases")
        print(f"        with {prompts_per_use_case} prompts per use-case")
        print()

    print(f"📋 RESULT:")
    print(f"   TaskInterleaver with {num_demo_projects} projects (one ProjectTasks per project)")
    print(f"   Each ProjectTasks contains the generated tasks for that project")
    print(f"   Tasks are shuffled within each project for variety")
    print()

    print(f"🔀 INTERLEAVED ITERATION:")
    print(f"   When iterating with iter_interleaved(), tasks are fetched")
    print(f"   in round-robin fashion from all projects:")
    print(f"   Project_1[task1] → Project_2[task1] → ... → Project_N[task1] →")
    print(f"   Project_1[task2] → Project_2[task2] → ...")
    print(f"   This ensures variety by alternating between different projects.")
    print()


def main():
    """Run simulations with different scenarios."""

    # Scenario 1: Real case with 8 demo projects
    print("\n" + "█" * 80)
    print("SCENARIO 1: Real case (8 demo projects, 2 prompts per use case)")
    print("█" * 80 + "\n")
    simulate_get_task_collection(num_demo_projects=8, prompts_per_use_case=2)

    # Scenario 2: Different prompts per use case
    print("\n" + "█" * 80)
    print("SCENARIO 2: Real case (8 demo projects, 3 prompts per use case)")
    print("█" * 80 + "\n")
    simulate_get_task_collection(num_demo_projects=8, prompts_per_use_case=3)

    # Scenario 3: Fewer projects
    print("\n" + "█" * 80)
    print("SCENARIO 3: Fewer projects (3 demo projects, 2 prompts per use case)")
    print("█" * 80 + "\n")
    simulate_get_task_collection(num_demo_projects=3, prompts_per_use_case=2)

    print("\n" + "=" * 80)
    print("✅ SIMULATION COMPLETE")
    print("=" * 80)
    print()
    print("💡 KEY INSIGHTS:")
    print("   1. total_prompts always equals num_projects (one task per project)")
    print("   2. Tasks are distributed evenly across all projects")
    print("   3. Each project generates tasks using a limited number of use-cases")
    print("   4. prompts_per_use_case controls how many prompts each use-case generates")
    print("   5. Tasks are interleaved when iterating for variety")
    print()


if __name__ == "__main__":
    main()
