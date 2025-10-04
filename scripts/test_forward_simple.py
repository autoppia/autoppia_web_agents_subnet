#!/usr/bin/env python3
"""
Script de simulación SIMPLIFICADO para testear el sistema de pre-generación y loop dinámico.

Este script simula el comportamiento completo del validator SIN dependencias de bittensor:
1. Pre-genera todas las tasks al inicio
2. Simula miners locales que responden
3. Ejecuta el loop dinámico con checkeo de tiempo
4. Acumula scores y aplica WTA
5. Muestra estadísticas detalladas

Uso:
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
    """Configuración de la simulación"""
    num_tasks: int = 30             # Número de tasks a pre-generar
    num_miners: int = 4              # Número de miners simulados
    round_size_epochs: int = 2       # Duración del round en epochs (reducido para testing)
    avg_task_duration: float = 120    # Duración promedio de una task en segundos (reducido)
    safety_buffer_epochs: float = 0.2  # Buffer de seguridad
    prompts_per_usecase: int = 1     # Prompts por use case
    task_execution_time: float = 20   # Tiempo real de ejecución por task (simulado)


class MockTask:
    """Simula una task"""

    def __init__(self, task_id: int, project: str):
        self.id = f"task_{task_id}"
        self.prompt = f"Task {task_id}: Perform action on {project}"
        self.project = project
        self.url = f"http://{project}.com"


class MockAction:
    """Simula una acción del miner"""

    def __init__(self, action_type: str, target: str, value: str = ""):
        self.action_type = action_type  # "click", "type", "scroll", etc.
        self.target = target           # selector, xpath, etc.
        self.value = value            # texto a escribir, etc.


class MockMiner:
    """Simula un miner con comportamiento realista"""

    def __init__(self, uid: int, skill_level: float):
        self.uid = uid
        self.skill_level = skill_level  # 0.0 - 1.0

    def solve_task(self, task: MockTask) -> List[MockAction]:
        """
        Simula la resolución de una task - DEVUELVE LISTA DE ACCIONES
        El evaluator será quien calcule el score basado en estas acciones
        """
        # Generar acciones basadas en el skill level
        num_actions = np.random.randint(3, 8)  # Entre 3-7 acciones
        actions = []

        # Miners más hábiles generan acciones más precisas
        for i in range(num_actions):
            if self.skill_level > 0.7:
                # Miners hábiles: acciones más precisas
                action_types = ["click", "type", "wait", "scroll"]
                targets = [f"button-{i}", f"input-{i}", f"div-{i}"]
            elif self.skill_level > 0.5:
                # Miners medios: acciones normales
                action_types = ["click", "type", "scroll"]
                targets = [f"element-{i}", f"field-{i}"]
            else:
                # Miners menos hábiles: acciones más básicas
                action_types = ["click", "scroll"]
                targets = [f"item-{i}", f"box-{i}"]

            action_type = np.random.choice(action_types)
            target = np.random.choice(targets)
            value = f"value-{i}" if action_type == "type" else ""

            actions.append(MockAction(action_type, target, value))

        return actions


class MockEvaluator:
    """Simula el evaluator que califica las acciones de los miners"""

    def evaluate_actions(self, miner_uid: int, task: MockTask, actions: List[MockAction], skill_level: float) -> Dict:
        """
        Evalúa las acciones del miner y devuelve el score
        """
        # Simular tiempo de ejecución basado en número de acciones
        execution_time = len(actions) * np.random.uniform(0.1, 0.3)

        # Calcular score basado en:
        # 1. Skill level del miner
        # 2. Número de acciones (menos es mejor)
        # 3. Calidad de las acciones (simulado)

        base_score = skill_level

        # Penalizar acciones excesivas
        if len(actions) > 6:
            base_score *= 0.9
        elif len(actions) < 4:
            base_score *= 1.1

        # Añadir ruido realista
        noise = np.random.normal(0, 0.08)

        # Ajustar el rango para que sea más realista
        if skill_level > 0.7:
            # Miners hábiles: 0.75 - 0.99
            final_score = max(0.75, min(0.99, base_score + noise))
        elif skill_level > 0.5:
            # Miners medios: 0.60 - 0.85
            final_score = max(0.60, min(0.85, base_score + noise))
        else:
            # Miners menos hábiles: 0.40 - 0.75
            final_score = max(0.40, min(0.75, base_score + noise))

        return {
            'uid': miner_uid,
            'score': final_score,
            'execution_time': execution_time,
            'num_actions': len(actions)
        }


class RoundCalculator:
    """
    Calcula automáticamente cuántas tasks se pueden ejecutar en un round completo.
    Versión simplificada sin dependencias de bittensor.
    """

    # Constantes de Bittensor
    BLOCKS_PER_EPOCH = 360
    SECONDS_PER_BLOCK = 12

    def __init__(
        self,
        round_size_epochs: int,
        avg_task_duration_seconds: float,
        safety_buffer_epochs: float,
    ):
        self.round_size_epochs = round_size_epochs
        self.avg_task_duration_seconds = avg_task_duration_seconds
        self.safety_buffer_epochs = safety_buffer_epochs

    def block_to_epoch(self, block: int) -> float:
        """Convierte número de bloque a epoch"""
        return block / self.BLOCKS_PER_EPOCH

    def get_round_boundaries(self, start_block: int) -> Dict:
        """Calcula los límites del round actual"""
        current_epoch = self.block_to_epoch(start_block)

        # Encontrar el inicio del round (múltiplo de round_size_epochs)
        round_start_epoch = int(current_epoch // self.round_size_epochs) * self.round_size_epochs

        # Calcular target epoch (final del round)
        target_epoch = round_start_epoch + self.round_size_epochs - 1

        # Convertir a bloques
        round_start_block = round_start_epoch * self.BLOCKS_PER_EPOCH
        target_block = target_epoch * self.BLOCKS_PER_EPOCH

        return {
            "round_start_epoch": round_start_epoch,
            "target_epoch": target_epoch,
            "round_start_block": round_start_block,
            "target_block": target_block,
        }

    def should_send_next_task(self, current_block: int, start_block: int) -> bool:
        """
        Determina si hay tiempo suficiente para enviar otra task.

        Checkea dinámicamente:
        1. Calcula límite absoluto (start + round_size - safety_buffer)
        2. Compara current_block con ese límite
        3. Verifica si hay tiempo para avg_task_duration
        """
        boundaries = self.get_round_boundaries(start_block)

        # Calcular límite absoluto: start + round_size - safety_buffer
        total_round_blocks = self.round_size_epochs * self.BLOCKS_PER_EPOCH
        safety_buffer_blocks = self.safety_buffer_epochs * self.BLOCKS_PER_EPOCH
        absolute_limit_block = start_block + total_round_blocks - safety_buffer_blocks

        # ¿Hemos alcanzado el límite absoluto?
        if current_block >= absolute_limit_block:
            return False

        # ¿Hay tiempo para otra task desde ahora hasta el límite?
        blocks_until_limit = absolute_limit_block - current_block
        seconds_until_limit = blocks_until_limit * self.SECONDS_PER_BLOCK

        has_time = seconds_until_limit >= self.avg_task_duration_seconds

        return has_time

    def get_wait_info(self, current_block: int, start_block: int) -> Dict:
        """Información detallada sobre el tiempo restante"""
        boundaries = self.get_round_boundaries(start_block)
        current_epoch = self.block_to_epoch(current_block)

        blocks_remaining = boundaries["target_block"] - current_block
        seconds_remaining = blocks_remaining * self.SECONDS_PER_BLOCK
        minutes_remaining = seconds_remaining / 60

        reached_target = current_block >= boundaries["target_block"]

        return {
            "current_epoch": current_epoch,
            "target_epoch": boundaries["target_epoch"],
            "blocks_remaining": blocks_remaining,
            "seconds_remaining": seconds_remaining,
            "minutes_remaining": minutes_remaining,
            "reached_target": reached_target,
        }

    def log_calculation_summary(self, start_block: int):
        """Log del resumen de cálculos iniciales"""
        boundaries = self.get_round_boundaries(start_block)
        wait_info = self.get_wait_info(start_block, start_block)

        print("📊 ROUND CALCULATION SUMMARY")
        print("=" * 80)
        print(f"   Round size: {self.round_size_epochs} epochs")
        print(f"   Start epoch: {boundaries['round_start_epoch']}")
        print(f"   Target epoch: {boundaries['target_epoch']}")
        print(f"   Total time: {wait_info['minutes_remaining']:.1f} minutes")
        print(f"   Avg task duration: {self.avg_task_duration_seconds}s")
        print(f"   Safety buffer: {self.safety_buffer_epochs} epochs")

        # Estimación de tasks posibles
        estimated_tasks = int(wait_info['seconds_remaining'] / self.avg_task_duration_seconds)
        print(f"   Estimated tasks possible: ~{estimated_tasks}")
        print("=" * 80 + "\n")


def reduce_rewards_to_averages(rewards_sum: np.ndarray, counts: np.ndarray) -> np.ndarray:
    """Calcula promedios de rewards"""
    # Evitar división por cero
    safe_counts = np.where(counts == 0, 1, counts)
    return rewards_sum / safe_counts


def wta_rewards(avg_rewards: np.ndarray) -> np.ndarray:
    """Aplica Winner Takes It All a los rewards promedio"""
    max_score = np.max(avg_rewards)
    wta_scores = np.where(avg_rewards == max_score, 1.0, 0.0)
    return wta_scores


class ForwardSimulator:
    """Simula el comportamiento completo del forward con pre-generación"""

    def __init__(self, config: SimulationConfig):
        self.config = config

        # Inicializar round calculator
        self.round_calculator = RoundCalculator(
            round_size_epochs=config.round_size_epochs,
            avg_task_duration_seconds=config.avg_task_duration,
            safety_buffer_epochs=config.safety_buffer_epochs,
        )

        # Crear miners simulados con diferentes skill levels
        self.miners = [
            MockMiner(uid=i, skill_level=np.random.uniform(0.3, 0.9))
            for i in range(config.num_miners)
        ]

        # Crear evaluator
        self.evaluator = MockEvaluator()

        # Estado de simulación
        self.current_block = 0
        self.blocks_per_epoch = 360
        self.seconds_per_block = 12

        # Acumuladores
        self.rewards_sum = np.zeros(config.num_miners)
        self.counts = np.zeros(config.num_miners)

        print("\n" + "=" * 80)
        print("🎮 FORWARD SIMULATION INITIALIZED")
        print("=" * 80)
        print(f"   Miners: {config.num_miners}")
        print(f"   Pre-generated tasks: {config.num_tasks}")
        print(f"   Round size: {config.round_size_epochs} epochs")
        print(f"   Avg task duration: {config.avg_task_duration}s")
        print(f"   Safety buffer: {config.safety_buffer_epochs} epochs")
        print("\n   Miner skills:")
        for miner in self.miners:
            print(f"      Miner {miner.uid}: skill={miner.skill_level:.2f}")
        print("=" * 80 + "\n")

    def pre_generate_tasks(self) -> List[MockTask]:
        """
        PRE-GENERATION PHASE: Generar todas las tasks al inicio
        """
        print("🔄 PRE-GENERATING TASKS")
        print("=" * 80)

        pre_generation_start = time.time()
        all_tasks = []

        # Simular proyectos
        projects = ["movies", "books", "autozone", "dining", "crm", "mail", "delivery", "lodge", "connect", "work", "calendar"]

        # Generar todas las tasks
        for i in range(self.config.num_tasks):
            project = projects[i % len(projects)]
            task = MockTask(i + 1, project)
            all_tasks.append(task)

        pre_generation_elapsed = time.time() - pre_generation_start
        print(f"✅ Pre-generation complete: {len(all_tasks)} tasks in {pre_generation_elapsed:.3f}s")
        print("=" * 80 + "\n")

        return all_tasks

    def simulate_block_advance(self):
        """Simula el avance de bloques en la blockchain"""
        # Avanzar más bloques para simular que las tasks tardan más
        # Esto nos permitirá ver el safety buffer en acción
        blocks_per_task = int(self.config.task_execution_time / self.seconds_per_block)
        # Multiplicar por 3 para que avance más rápido y se acerque al límite
        self.current_block += max(10, blocks_per_task * 3)

    def should_continue(self, start_block: int) -> bool:
        """Checkeo dinámico: ¿hay tiempo para otra task?"""
        return self.round_calculator.should_send_next_task(self.current_block, start_block)

    async def execute_task(self, task: MockTask, task_index: int) -> Dict:
        """
        Simula la ejecución de una task:
        1. Enviar a miners
        2. Miners devuelven acciones
        3. Evaluator evalúa las acciones
        4. Calcular rewards
        """
        # Simular tiempo de ejecución
        await asyncio.sleep(self.config.task_execution_time / 10)  # Reducido para simulación

        # PASO 1: Cada miner resuelve la task (devuelve acciones)
        miner_actions = []
        for miner in self.miners:
            actions = miner.solve_task(task)
            miner_actions.append((miner.uid, actions))

        # PASO 2: Evaluator evalúa las acciones de cada miner
        results = []
        for miner_uid, actions in miner_actions:
            miner = next(m for m in self.miners if m.uid == miner_uid)
            evaluation = self.evaluator.evaluate_actions(
                miner_uid=miner_uid,
                task=task,
                actions=actions,
                skill_level=miner.skill_level
            )
            results.append(evaluation)

        # PASO 3: Calcular rewards (usando los scores del evaluator)
        rewards = np.array([r['score'] for r in results])

        return {
            'rewards': rewards,
            'results': results,
            'miner_actions': miner_actions  # Para debugging
        }

    async def run_dynamic_loop(self, all_tasks: List[MockTask], start_block: int):
        """
        MAIN LOOP: Sistema dinámico con tasks pre-generadas
        """
        print("🎯 STARTING DYNAMIC TASK EXECUTION")
        print(f"   Total pre-generated tasks: {len(all_tasks)}")
        print("=" * 80 + "\n")

        tasks_completed = 0
        task_index = 0

        # Loop dinámico: consume tasks pre-generadas y checkea DESPUÉS de evaluar
        while task_index < len(all_tasks):
            iteration_start = time.time()

            # Progress logging
            current_epoch = self.round_calculator.block_to_epoch(self.current_block)
            boundaries = self.round_calculator.get_round_boundaries(start_block)
            wait_info = self.round_calculator.get_wait_info(self.current_block, start_block)

            print("")
            print("━" * 80)
            print(
                f"📍 TASK {task_index + 1}/{len(all_tasks)} | "
                f"Epoch {current_epoch:.2f}/{boundaries['target_epoch']} | "
                f"Time remaining: {wait_info['minutes_remaining']:.1f} min"
            )
            print("━" * 80)

            # 1. Coger siguiente task pre-generada
            task = all_tasks[task_index]
            print(f"   Task: {task.prompt}")

            # 2. Enviar task a miners (simulado)
            print(f"   Sending to {len(self.miners)} miners...")

            # 3. Ejecutar task (simulado)
            task_results = await self.execute_task(task, task_index)

            # 4. Acumular rewards
            self.rewards_sum += task_results['rewards']
            self.counts += 1

            # 5. Mostrar resultados
            top_miner = np.argmax(task_results['rewards'])
            print(f"   🏆 Best miner: {top_miner} (score: {task_results['rewards'][top_miner]:.3f})")

            # Mostrar todos los scores para esta task
            print(f"   📊 Task scores:")
            for i, (result, reward) in enumerate(zip(task_results['results'], task_results['rewards'])):
                print(f"      Miner {i}: {reward:.3f} (exec_time: {result['execution_time']:.1f}s, actions: {result['num_actions']})")

            # Mostrar acciones del miner ganador (para debugging)
            if task_index < 3:  # Solo mostrar para las primeras 3 tasks
                winner_actions = task_results['miner_actions'][top_miner][1]
                print(f"   🔍 Winner actions: {[f'{a.action_type}({a.target})' for a in winner_actions[:3]]}...")

            # Update counters
            tasks_completed += 1
            task_index += 1

            # Simular avance de bloques
            self.simulate_block_advance()

            iteration_elapsed = time.time() - iteration_start
            print(f"✅ Completed task {task_index}/{len(all_tasks)} in {iteration_elapsed:.1f}s")

            # Log top 3 miners cada 5 tasks
            if tasks_completed % 5 == 0:
                avg_so_far = reduce_rewards_to_averages(self.rewards_sum, self.counts)
                top_3 = np.argsort(avg_so_far)[-3:][::-1]
                print(f"\n   📊 Current top 3:")
                for i in top_3:
                    print(f"      Miner {i}: avg={avg_so_far[i]:.3f}, skill={self.miners[i].skill_level:.3f}")

            # ⚡ CHECKEO DINÁMICO: ¿Hay tiempo para otra task DESPUÉS de evaluar?
            if not self.should_continue(start_block):
                print("")
                print("🛑 STOPPING TASK EXECUTION - SAFETY BUFFER REACHED")
                print(f"   Reason: Insufficient time remaining for another task")
                print(f"   Current epoch: {current_epoch:.2f}")
                print(f"   Time remaining: {wait_info['seconds_remaining']:.0f}s")
                print(f"   Safety buffer: {self.config.safety_buffer_epochs} epochs")
                print(f"   Tasks completed: {tasks_completed}/{len(all_tasks)}")
                print(f"   ⏳ Now waiting for target epoch to set weights...")
                break

        return tasks_completed

    async def wait_for_target_epoch(self, start_block: int):
        """Espera al target epoch para setear weights"""
        print("\n" + "=" * 80)
        print("⏳ WAITING FOR TARGET EPOCH")
        print("=" * 80)

        boundaries = self.round_calculator.get_round_boundaries(start_block)
        target_epoch = boundaries['target_epoch']

        while True:
            current_epoch = self.round_calculator.block_to_epoch(self.current_block)
            wait_info = self.round_calculator.get_wait_info(self.current_block, start_block)

            if wait_info["reached_target"]:
                print(f"🎯 Target epoch {target_epoch} REACHED!")
                print(f"   Current epoch: {current_epoch:.2f}")
                break

            print(f"⏳ Waiting... Current: {current_epoch:.2f}, Target: {target_epoch}, Remaining: {wait_info['minutes_remaining']:.1f} min")

            # Simular avance de tiempo
            await asyncio.sleep(0.1)  # Reducido para simulación
            self.current_block += 10  # Avanzar más rápido en wait phase

        print("=" * 80 + "\n")

    def calculate_final_scores(self) -> np.ndarray:
        """Calcula los scores finales y aplica WTA"""
        # Calcular promedios
        avg_rewards = reduce_rewards_to_averages(self.rewards_sum, self.counts)

        print("\n" + "=" * 80)
        print("📊 AVERAGE SCORES (before WTA)")
        print("=" * 80)
        for i, (avg, count) in enumerate(zip(avg_rewards, self.counts)):
            print(f"   Miner {i}: avg={avg:.3f}, tasks={int(count)}, skill={self.miners[i].skill_level:.3f}")

        # Aplicar WTA
        wta_scores = wta_rewards(avg_rewards)

        print("\n" + "=" * 80)
        print("🏆 WTA RESULTS")
        print("=" * 80)
        winner = np.argmax(wta_scores)
        print(f"   🥇 WINNER: Miner {winner}")
        print(f"      Score: {wta_scores[winner]:.3f}")
        print(f"      Skill: {self.miners[winner].skill_level:.3f}")
        print(f"      Tasks completed: {int(self.counts[winner])}")
        print("\n   All WTA scores:")
        for i, score in enumerate(wta_scores):
            symbol = "🥇" if i == winner else "  "
            print(f"      {symbol} Miner {i}: {score:.3f}")
        print("=" * 80 + "\n")

        return wta_scores

    async def run_simulation(self):
        """Ejecuta la simulación completa"""
        print("\n" + "=" * 80)
        print("🚀 STARTING FULL ROUND SIMULATION")
        print("=" * 80 + "\n")

        # Inicializar bloques
        start_block = self.current_block
        boundaries = self.round_calculator.get_round_boundaries(start_block)

        print(f"   Start block: {start_block} (epoch {boundaries['round_start_epoch']})")
        print(f"   Target block: {boundaries['target_block']} (epoch {boundaries['target_epoch']})")
        print("")

        # Mostrar cálculos iniciales
        self.round_calculator.log_calculation_summary(start_block)

        # PHASE 1: Pre-generación
        all_tasks = self.pre_generate_tasks()

        # PHASE 2: Loop dinámico
        tasks_completed = await self.run_dynamic_loop(all_tasks, start_block)

        # PHASE 3: Wait for target epoch (si no se alcanzó)
        if tasks_completed < len(all_tasks):
            await self.wait_for_target_epoch(start_block)

        # PHASE 4: Calcular scores finales
        final_scores = self.calculate_final_scores()

        # Summary
        print("=" * 80)
        print("✅ SIMULATION COMPLETE")
        print("=" * 80)
        print(f"   Total tasks pre-generated: {len(all_tasks)}")
        print(f"   Tasks completed: {tasks_completed}")
        print(f"   Completion rate: {tasks_completed/len(all_tasks)*100:.1f}%")
        print(f"   Final epoch: {self.round_calculator.block_to_epoch(self.current_block):.2f}")
        print("=" * 80 + "\n")


async def main():
    parser = argparse.ArgumentParser(description="Simulate validator forward with pre-generation")
    parser.add_argument("--num-tasks", type=int, default=100, help="Number of tasks to pre-generate")
    parser.add_argument("--num-miners", type=int, default=5, help="Number of miners to simulate")
    parser.add_argument("--round-epochs", type=int, default=2, help="Round duration in epochs")
    parser.add_argument("--avg-duration", type=float, default=120, help="Average task duration in seconds")
    parser.add_argument("--task-time", type=float, default=20, help="Real execution time per task (simulation)")

    args = parser.parse_args()

    config = SimulationConfig(
        num_tasks=args.num_tasks,
        num_miners=args.num_miners,
        round_size_epochs=args.round_epochs,
        avg_task_duration=args.avg_duration,
        task_execution_time=args.task_time,
    )

    simulator = ForwardSimulator(config)
    await simulator.run_simulation()


if __name__ == "__main__":
    asyncio.run(main())
