#!/usr/bin/env python3
"""
Simplified simulation script to test the pre-generation and dynamic loop system.

This script simulates the complete validator behavior WITHOUT bittensor dependencies:
1. Pre-generates all tasks at the beginning
2. Simulates local miners that respond
3. Executes the dynamic loop with time checking
4. Accumulates scores and applies WTA
5. Shows detailed statistics

Usage:
    python3 scripts/test_forward_simple.py --num-tasks 20 --num-miners 5 --round-epochs 2
"""

import asyncio
import argparse
import time
from typing import List, Dict, Tuple
import numpy as np
from dataclasses import dataclass


@dataclass
class SimulationConfig:
    """Simulation configuration"""
    num_tasks: int = 30             # Number of tasks to pre-generate
    num_miners: int = 4              # Number of simulated miners
    round_size_epochs: int = 2       # Round duration in epochs (reduced for testing)
    avg_task_duration: float = 120    # Average task duration in seconds (reduced)
    safety_buffer_epochs: float = 0.2  # Safety buffer
    prompts_per_usecase: int = 1     # Prompts per use case
    task_execution_time: float = 20   # Real execution time per task (simulated)


class MockTask:
    """Simulates a task"""

    def __init__(self, task_id: int, project: str):
        self.id = f"task_{task_id}"
        self.prompt = f"Task {task_id}: Perform action on {project}"
        self.project = project
        self.url = f"http://{project}.com"


class MockAction:
    """Simulates a miner action"""

    def __init__(self, action_type: str, target: str, value: str = ""):
        self.action_type = action_type  # "click", "type", "scroll", etc.
        self.target = target           # Element selector
        self.value = value             # Value for input actions


class MockMiner:
    """Simulates a miner with different skill levels"""

    def __init__(self, uid: int, skill_level: float):
        self.uid = uid
        self.skill_level = skill_level  # 0.0 to 1.0
        self.total_tasks = 0
        self.total_score = 0.0

    def solve_task(self, task: MockTask) -> List[MockAction]:
        """
        Simulates generating actions based on skill level
        """
        # Simulate generating actions based on skill level
        num_actions = np.random.randint(3, 8)
        actions = []

        for i in range(num_actions):
            # More skilled miners generate better actions
            if self.skill_level > 0.7:
                action_types = ["click", "type", "scroll", "wait"]
                targets = ["button", "input", "link", "form"]
            elif self.skill_level > 0.4:
                action_types = ["click", "type", "scroll"]
                targets = ["button", "input", "link"]
            else:
                action_types = ["click", "type"]
                targets = ["button", "input"]

            action_type = np.random.choice(action_types)
            target = np.random.choice(targets)
            value = f"value_{i}" if action_type == "type" else ""

            actions.append(MockAction(action_type, target, value))

        return actions


class MockEvaluator:
    """Simulates the evaluator that scores miner actions"""

    def evaluate_actions(self, miner_uid: int, task: MockTask, actions: List[MockAction], skill_level: float) -> Dict:
        """
        Evaluates miner actions and returns the score
        """
        # Simulate execution time based on number of actions
        execution_time = len(actions) * np.random.uniform(0.1, 0.3)

        # Calculate score based on:
        # 1. Miner skill level
        # 2. Number of actions (fewer is better)
        # 3. Action quality (simulated)

        base_score = skill_level

        # Penalize excessive actions
        if len(actions) > 6:
            base_score *= 0.9
        elif len(actions) < 4:
            base_score *= 1.1

        # Add realistic noise
        noise = np.random.normal(0, 0.08)

        # Adjust range to be more realistic
        if skill_level > 0.7:
            # Skilled miners: 0.75 - 0.99
            final_score = max(0.75, min(0.99, base_score + noise))
        elif skill_level > 0.5:
            # Medium miners: 0.60 - 0.85
            final_score = max(0.60, min(0.85, base_score + noise))
        else:
            # Less skilled miners: 0.40 - 0.75
            final_score = max(0.40, min(0.75, base_score + noise))

        return {
            'uid': miner_uid,
            'score': final_score,
            'execution_time': execution_time,
            'num_actions': len(actions)
        }


class MockRoundCalculator:
    """
    Calculates how many tasks can be executed in a complete round.
    Simplified version without bittensor dependencies.
    """

    # Bittensor constants
    BLOCKS_PER_EPOCH = 360
    SECONDS_PER_BLOCK = 12

    def __init__(self, round_size_epochs: int, avg_task_duration_seconds: float, safety_buffer_epochs: float):
        self.round_size_epochs = round_size_epochs
        self.avg_task_duration_seconds = avg_task_duration_seconds
        self.safety_buffer_epochs = safety_buffer_epochs

    def block_to_epoch(self, block: int) -> float:
        """Convert block to epoch (simplified)"""
        return block / self.BLOCKS_PER_EPOCH

    def epoch_to_block(self, epoch: float) -> int:
        """Convert epoch to block (simplified)"""
        return int(epoch * self.BLOCKS_PER_EPOCH)

    def get_round_boundaries(self, current_block: int) -> Dict:
        """Calculate round boundaries"""
        current_epoch = self.block_to_epoch(current_block)

        # Calculate round start (epoch multiple of round_size_epochs)
        round_start_epoch = (current_epoch // self.round_size_epochs) * self.round_size_epochs
        # Target epoch is the end of the round
        target_epoch = round_start_epoch + self.round_size_epochs

        # Convert to blocks
        round_start_block = self.epoch_to_block(round_start_epoch)
        target_block = self.epoch_to_block(target_epoch)

        return {
            'round_start_epoch': round_start_epoch,
            'target_epoch': target_epoch,
            'round_start_block': round_start_block,
            'target_block': target_block
        }

    def should_send_next_task(self, current_block: int, start_block: int) -> bool:
        """Check if there's enough time to send another task"""
        boundaries = self.get_round_boundaries(start_block)
        total_round_blocks = self.round_size_epochs * self.BLOCKS_PER_EPOCH
        safety_buffer_blocks = self.safety_buffer_epochs * self.BLOCKS_PER_EPOCH
        absolute_limit_block = start_block + total_round_blocks - safety_buffer_blocks

        if current_block >= absolute_limit_block:
            return False

        blocks_until_limit = absolute_limit_block - current_block
        seconds_until_limit = blocks_until_limit * self.SECONDS_PER_BLOCK
        has_time = seconds_until_limit >= self.avg_task_duration_seconds

        return has_time

    def get_wait_info(self, current_block: int, start_block: int) -> Dict:
        """Get wait information"""
        boundaries = self.get_round_boundaries(start_block)
        target_epoch = boundaries['target_epoch']
        current_epoch = self.block_to_epoch(current_block)

        blocks_remaining = boundaries['target_block'] - current_block
        seconds_remaining = blocks_remaining * self.SECONDS_PER_BLOCK
        minutes_remaining = seconds_remaining / 60

        return {
            'current_epoch': current_epoch,
            'target_epoch': target_epoch,
            'blocks_remaining': blocks_remaining,
            'seconds_remaining': seconds_remaining,
            'minutes_remaining': minutes_remaining,
            'reached_target': current_epoch >= target_epoch
        }

    def log_calculation_summary(self):
        """Log calculation summary"""
        print(f"📊 Round Calculator Configuration:")
        print(f"   Round size: {self.round_size_epochs} epochs")
        print(f"   Safety buffer: {self.safety_buffer_epochs} epochs")
        print(f"   Avg task duration: {self.avg_task_duration_seconds}s")
        print(f"   Blocks per epoch: {self.BLOCKS_PER_EPOCH}")
        print(f"   Seconds per block: {self.SECONDS_PER_BLOCK}s")


class MockValidator:
    """Simulates the validator with the new integrated structure"""

    def __init__(self, config: SimulationConfig):
        self.config = config
        self.round_calculator = MockRoundCalculator(
            round_size_epochs=config.round_size_epochs,
            avg_task_duration_seconds=config.avg_task_duration,
            safety_buffer_epochs=config.safety_buffer_epochs
        )

        # Round system components
        self.round_scores = {}  # {miner_uid: [score1, score2, ...]}
        self.round_times = {}   # {miner_uid: [time1, time2, ...]}

        # Simulate miners with different skill levels
        self.miners = [
            MockMiner(uid=i, skill_level=np.random.uniform(0.3, 0.9))
            for i in range(config.num_miners)
        ]

        self.evaluator = MockEvaluator()

    async def simulate_forward(self):
        """Simulate the complete forward loop"""
        print("")
        print("🚀 STARTING ROUND-BASED FORWARD SIMULATION")
        print("=" * 80)

        # Simulate current block
        current_block = 1000
        boundaries = self.round_calculator.get_round_boundaries(current_block)

        print(f"Round boundaries: start={boundaries['round_start_epoch']}, target={boundaries['target_epoch']}")

        # Log configuration summary
        self.round_calculator.log_calculation_summary()

        # ═══════════════════════════════════════════════════════
        # PRE-GENERATION: Generate all tasks at the beginning
        # ═══════════════════════════════════════════════════════
        print("")
        print("🔄 PRE-GENERATING TASKS")
        print("=" * 80)

        pre_generation_start = time.time()
        all_tasks = []

        # Generate all tasks
        projects = ["ecommerce", "blog", "portfolio", "dashboard", "landing"]
        for i in range(self.config.num_tasks):
            project = projects[i % len(projects)]
            task = MockTask(task_id=i + 1, project=project)
            all_tasks.append((project, task))

        pre_generation_elapsed = time.time() - pre_generation_start
        print(f"✅ Pre-generation complete: {len(all_tasks)} tasks in {pre_generation_elapsed:.1f}s")
        print("=" * 80)

        # ═══════════════════════════════════════════════════════
        # DYNAMIC LOOP: Execute tasks one by one based on time
        # ═══════════════════════════════════════════════════════
        print("")
        print("🔄 STARTING DYNAMIC TASK EXECUTION")
        print("=" * 80)

        start_block = current_block
        task_index = 0
        tasks_completed = 0

        # Dynamic loop: consume pre-generated tasks and check AFTER evaluating
        while task_index < len(all_tasks):
            current_block = self.simulate_block_advance(current_block)
            current_epoch = self.round_calculator.block_to_epoch(current_block)
            boundaries = self.round_calculator.get_round_boundaries(start_block)
            wait_info = self.round_calculator.get_wait_info(current_block, start_block)

            print(f"📍 TASK {task_index + 1}/{len(all_tasks)} | "
                  f"Epoch {current_epoch:.2f}/{boundaries['target_epoch']} | "
                  f"Time remaining: {wait_info['minutes_remaining']:.1f} min")

            # Execute single task
            success = await self.simulate_execute_single_task(all_tasks[task_index], task_index, start_block)
            if success:
                tasks_completed += 1
            task_index += 1

            # Dynamic check: should we send another task?
            if not self.round_calculator.should_send_next_task(current_block, start_block):
                print("")
                print("🛑 STOPPING TASK EXECUTION - SAFETY BUFFER REACHED")
                print(f"   Reason: Insufficient time remaining for another task")
                print(f"   Current epoch: {current_epoch:.2f}")
                print(f"   Time remaining: {wait_info['seconds_remaining']:.0f}s")
                print(f"   Safety buffer: {self.config.safety_buffer_epochs} epochs")
                print(f"   Tasks completed: {tasks_completed}/{len(all_tasks)}")
                print(f"   ⏳ Now waiting for target epoch to set weights...")
                break

        # ═══════════════════════════════════════════════════════
        # WAIT FOR TARGET EPOCH: Wait until the round ends
        # ═══════════════════════════════════════════════════════
        if tasks_completed < len(all_tasks):
            await self.simulate_wait_for_target_epoch(start_block)

        # ═══════════════════════════════════════════════════════
        # FINAL WEIGHTS: Calculate averages, apply WTA, set weights
        # ═══════════════════════════════════════════════════════
        await self.simulate_calculate_final_weights(tasks_completed)

    def simulate_block_advance(self, current_block: int) -> int:
        """Simulate block advancement (more aggressive for testing)"""
        # Advance blocks more aggressively to test safety buffer
        return current_block + int(self.config.task_execution_time / 12)  # 12 seconds per block

    async def simulate_execute_single_task(self, task_data, task_index: int, start_block: int) -> bool:
        """Simulate executing a single task and accumulating results"""
        project, task = task_data

        try:
            # Simulate task execution time
            await asyncio.sleep(0.1)  # Simulate processing time

            # Get active miners (simulate random selection)
            active_miners = np.random.choice(self.miners, size=min(3, len(self.miners)), replace=False)

            # Simulate miner responses
            for miner in active_miners:
                # Miner solves task
                actions = miner.solve_task(task)

                # Evaluator scores the actions
                eval_result = self.evaluator.evaluate_actions(
                    miner.uid, task, actions, miner.skill_level
                )

                # Accumulate scores for the round
                if miner.uid not in self.round_scores:
                    self.round_scores[miner.uid] = []
                    self.round_times[miner.uid] = []

                self.round_scores[miner.uid].append(eval_result['score'])
                self.round_times[miner.uid].append(eval_result['execution_time'])

                # Update miner stats
                miner.total_tasks += 1
                miner.total_score += eval_result['score']

            print(f"✅ Task {task_index + 1} completed")
            return True

        except Exception as e:
            print(f"❌ Task execution failed: {e}")
            return False

    async def simulate_wait_for_target_epoch(self, start_block: int):
        """Simulate waiting for target epoch"""
        print("")
        print("⏳ WAITING FOR TARGET EPOCH")
        print("=" * 80)

        boundaries = self.round_calculator.get_round_boundaries(start_block)
        target_epoch = boundaries['target_epoch']

        # Simulate waiting (just log, don't actually wait)
        print(f"🎯 Target epoch {target_epoch} REACHED!")
        print("=" * 80)

    async def simulate_calculate_final_weights(self, tasks_completed: int):
        """Simulate calculating final weights"""
        print("")
        print("🏁 CALCULATING FINAL WEIGHTS")
        print("=" * 80)

        # Calculate average scores for each miner
        avg_scores = {}
        for uid, scores in self.round_scores.items():
            if scores:
                avg_scores[uid] = sum(scores) / len(scores)
            else:
                avg_scores[uid] = 0.0

        print(f"Round scores: {len(avg_scores)} miners with scores")
        for uid, score in avg_scores.items():
            print(f"  Miner {uid}: {score:.3f} (from {len(self.round_scores[uid])} tasks)")

        # Apply WTA to get final weights
        final_weights = self.simulate_wta_rewards(avg_scores)

        print("")
        print("🎯 FINAL WEIGHTS (WTA)")
        print("=" * 80)
        for uid, weight in final_weights.items():
            if weight > 0:
                print(f"  🏆 Miner {uid}: {weight:.3f}")
            else:
                print(f"  ❌ Miner {uid}: {weight:.3f}")

        print("")
        print("✅ ROUND COMPLETE")
        print("=" * 80)
        print(f"Tasks completed: {tasks_completed}")
        print(f"Miners evaluated: {len(avg_scores)}")
        print(f"Winner: {max(avg_scores, key=avg_scores.get) if avg_scores else 'None'}")

    def simulate_wta_rewards(self, avg_scores: Dict[int, float]) -> Dict[int, float]:
        """Simulate Winner Takes All rewards"""
        if not avg_scores:
            return {}

        # Find the highest score
        max_score = max(avg_scores.values())

        # Only miners with the highest score get rewards
        final_weights = {}
        for uid, score in avg_scores.items():
            if score == max_score:
                final_weights[uid] = 1.0  # Winner gets full weight
            else:
                final_weights[uid] = 0.0  # Others get nothing

        return final_weights


async def main():
    """Main simulation function"""
    parser = argparse.ArgumentParser(description="Test forward simulation")
    parser.add_argument("--num-tasks", type=int, default=30, help="Number of tasks to pre-generate")
    parser.add_argument("--num-miners", type=int, default=4, help="Number of simulated miners")
    parser.add_argument("--round-epochs", type=int, default=2, help="Round duration in epochs")
    parser.add_argument("--task-duration", type=float, default=120, help="Average task duration in seconds")
    parser.add_argument("--safety-buffer", type=float, default=0.2, help="Safety buffer in epochs")

    args = parser.parse_args()

    config = SimulationConfig(
        num_tasks=args.num_tasks,
        num_miners=args.num_miners,
        round_size_epochs=args.round_epochs,
        avg_task_duration=args.task_duration,
        safety_buffer_epochs=args.safety_buffer
    )

    print(f"🎯 Starting simulation with:")
    print(f"   Tasks: {config.num_tasks}")
    print(f"   Miners: {config.num_miners}")
    print(f"   Round epochs: {config.round_size_epochs}")
    print(f"   Task duration: {config.avg_task_duration}s")
    print(f"   Safety buffer: {config.safety_buffer_epochs} epochs")
    print("")

    validator = MockValidator(config)
    await validator.simulate_forward()


if __name__ == "__main__":
    asyncio.run(main())
