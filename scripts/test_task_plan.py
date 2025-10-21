#!/usr/bin/env python3
"""
Script de prueba para ver cómo funciona get_task_collection y qué devuelve.
Simula el proceso de generación de tareas sin necesitar Bittensor completo.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class MockLogger:
    """Mock logger para simular bittensor logging."""
    @staticmethod
    def info(msg): print(f"ℹ️  INFO: {msg}")
    @staticmethod
    def warning(msg): print(f"⚠️  WARNING: {msg}")
    @staticmethod
    def error(msg): print(f"❌ ERROR: {msg}")


# Mock bittensor logging
import bittensor as bt
if not hasattr(bt, 'logging'):
    bt.logging = MockLogger()


async def main():
    """Test get_task_collection function."""
    print("=" * 80)
    print("🧪 TESTING get_task_collection()")
    print("=" * 80)
    print()

    try:
        # ⭐ IMPORTANT: Initialize DIContainer before using any IWA functionality
        print("🔧 Initializing Dependency Injection Container...")
        from autoppia_iwa.src.bootstrap import AppBootstrap
        bootstrap = AppBootstrap()
        print("✅ DIContainer initialized successfully!")
        print()

        # Import the function
        from autoppia_web_agents_subnet.validator.tasks import get_task_collection
        from autoppia_iwa.src.demo_webs.config import demo_web_projects

        print(f"📊 Demo web projects found: {len(demo_web_projects)}")
        print()

        # List projects
        for i, project in enumerate(demo_web_projects, 1):
            project_name = getattr(project, 'name', 'unknown')
            print(f"  {i}. {project_name}")
        print()

        # Test with different prompts_per_use_case values
        test_values = [1]

        for prompts_per_use_case in test_values:
            print("─" * 80)
            print(f"🔬 TEST: prompts_per_use_case = {prompts_per_use_case}")
            print("─" * 80)

            try:
                task_collection = await get_task_collection(prompts_per_use_case=prompts_per_use_case)

                print(f"\n✅ TaskInterleaver generated successfully!")
                print(f"   Total projects: {len(task_collection.projects_tasks)}")
                print(f"   Total tasks: {len(task_collection)}")
                print(f"   Is empty: {task_collection.empty()}")
                print()

                # Show ALL tasks with FULL details
                task_counter = 0
                for i, project_tasks in enumerate(task_collection.projects_tasks, 1):
                    project_name = getattr(project_tasks.project, 'name', 'unknown')
                    print("=" * 80)
                    print(f"📦 PROJECT {i}: {project_name}")
                    print(f"   Total tasks: {len(project_tasks.tasks)}")
                    print("=" * 80)

                    # Show ALL tasks for this project
                    for j, task in enumerate(project_tasks.tasks, 1):
                        task_counter += 1
                        prompt = getattr(task, 'prompt', 'N/A')
                        url = getattr(task, 'url', 'N/A')
                        task_id = getattr(task, 'id', 'N/A')
                        tests = getattr(task, 'tests', [])
                        use_case = getattr(task, 'use_case', None)
                        use_case_name = getattr(use_case, 'name', 'N/A') if use_case else 'N/A'

                        print(f"\n   🎯 Task {task_counter} (Project {i}, Task {j}):")
                        print(f"      ID: {task_id}")
                        print(f"      URL: {url}")
                        print(f"      Use Case: {use_case_name}")
                        print(f"      Prompt: {prompt}")
                        print(f"      Tests: {len(tests)} test(s)")

                        # Show test details
                        for k, test in enumerate(tests, 1):
                            test_type = getattr(test, 'type', 'Unknown')
                            print(f"         Test {k}: {test_type}")
                            if hasattr(test, 'event_name'):
                                print(f"            Event: {test.event_name}")
                            if hasattr(test, 'event_criteria') and test.event_criteria:
                                print(f"            Criteria: {test.event_criteria}")
                    print()
                print()

                # Test interleaved iteration
                print("   🔀 Testing interleaved iteration (first 5):")
                for idx, (project, task) in enumerate(task_collection.iter_interleaved()):
                    if idx >= 5:
                        break
                    project_name = getattr(project, 'name', 'unknown')
                    task_id = getattr(task, 'id', 'N/A')
                    prompt = getattr(task, 'prompt', 'N/A')[:50]
                    print(f"      {idx+1}. [{project_name}] Task {task_id}: {prompt}...")
                print()

            except Exception as e:
                print(f"\n❌ Error generating TaskInterleaver: {e}")
                import traceback
                traceback.print_exc()
                print()

        print("=" * 80)
        print("✅ Test completed!")
        print("=" * 80)

    except ImportError as e:
        print(f"\n❌ Import error: {e}")
        print("\nMake sure you have installed the project:")
        print("  cd /path/to/autoppia_web_agents_subnet")
        print("  pip install -e .")
        print("  cd autoppia_iwa_module")
        print("  pip install -e .")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
