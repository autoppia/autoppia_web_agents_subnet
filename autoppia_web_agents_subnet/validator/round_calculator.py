# autoppia_web_agents_subnet/validator/round_calculator.py
from __future__ import annotations
import bittensor as bt
from typing import Dict, Any


class RoundCalculator:
    """
    Calcula automáticamente cuántas tasks se pueden ejecutar en un round completo.

    Un round = ROUND_SIZE_EPOCHS epochs de Bittensor
    Todos los validators sincronizan en epochs múltiplos de ROUND_SIZE_EPOCHS.

    Ejemplo:
        Si ROUND_SIZE_EPOCHS = 20:
        - Round 1: epochs 0-19 (target: 19)
        - Round 2: epochs 20-39 (target: 39)
        - Round 3: epochs 40-59 (target: 59)
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
        """
        Args:
            round_size_epochs: Duración del round en epochs (ej: 20 = ~24h)
            avg_task_duration_seconds: Tiempo promedio para completar 1 task
            safety_buffer_epochs: Buffer de seguridad en epochs (ej: 0.5 = 36 min)
        """
        self.round_size_epochs = round_size_epochs
        self.avg_task_duration_seconds = avg_task_duration_seconds
        self.safety_buffer_epochs = safety_buffer_epochs

    @classmethod
    def block_to_epoch(cls, block: int) -> int:
        """Convierte block number a epoch number."""
        return block // cls.BLOCKS_PER_EPOCH

    @classmethod
    def epoch_to_block(cls, epoch: int) -> int:
        """Convierte epoch number al primer bloque de ese epoch."""
        return epoch * cls.BLOCKS_PER_EPOCH

    def get_round_boundaries(self, current_block: int) -> Dict[str, int]:
        """
        Calcula las boundaries del round actual basado en el bloque actual.

        Los rounds empiezan en epochs múltiplos de round_size_epochs.
        Ejemplo con round_size_epochs=20:
            - Epoch 0-19 → round_start=0, round_end=20
            - Epoch 20-39 → round_start=20, round_end=40
            - Epoch 233 → round_start=220, round_end=240

        Args:
            current_block: Bloque actual de la blockchain

        Returns:
            Dict con boundaries del round
        """
        current_epoch = self.block_to_epoch(current_block)

        # Calcular inicio del round (epoch múltiplo de round_size_epochs)
        round_start_epoch = (current_epoch // self.round_size_epochs) * self.round_size_epochs

        # Target epoch es el último del round
        target_epoch = round_start_epoch + self.round_size_epochs - 1

        # Convertir a bloques
        round_start_block = self.epoch_to_block(round_start_epoch)
        target_block = self.epoch_to_block(target_epoch)

        return {
            "current_block": current_block,
            "current_epoch": current_epoch,
            "round_start_epoch": round_start_epoch,
            "round_start_block": round_start_block,
            "target_epoch": target_epoch,
            "target_block": target_block,
        }

    def should_send_next_task(self, current_block: int, start_block: int) -> bool:
        """
        Determina si hay tiempo suficiente para enviar otra task.

        Checkea dinámicamente:
        1. Calcula límite absoluto (start + round_size - safety_buffer)
        2. Compara current_block con ese límite
        3. Verifica si hay tiempo para avg_task_duration

        Args:
            current_block: Bloque actual de la blockchain
            start_block: Bloque donde inició el round

        Returns:
            True si hay tiempo para otra task, False si ya no
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

    def get_calculation_summary(self) -> Dict[str, Any]:
        """
        Devuelve un resumen de la configuración del round.

        Returns:
            Dict con info de configuración
        """
        total_blocks = self.round_size_epochs * self.BLOCKS_PER_EPOCH
        total_seconds = total_blocks * self.SECONDS_PER_BLOCK

        # Estimación inicial (meramente informativa)
        safety_buffer_seconds = self.safety_buffer_epochs * self.BLOCKS_PER_EPOCH * self.SECONDS_PER_BLOCK
        available_time = total_seconds - safety_buffer_seconds
        estimated_tasks = int(available_time / self.avg_task_duration_seconds)

        return {
            # Round config
            "round_size_epochs": self.round_size_epochs,
            "avg_task_duration_seconds": self.avg_task_duration_seconds,
            "safety_buffer_epochs": self.safety_buffer_epochs,
            "safety_buffer_seconds": int(safety_buffer_seconds),

            # Time calculations
            "total_blocks": total_blocks,
            "total_seconds": total_seconds,
            "total_hours": round(total_seconds / 3600, 2),
            "available_seconds": int(available_time),
            "available_hours": round(available_time / 3600, 2),

            # Estimación inicial (no es el máximo real, solo referencia)
            "estimated_tasks": estimated_tasks,
        }

    def should_wait_for_target(self, current_block: int, start_block: int) -> bool:
        """
        Determina si debe esperar al target epoch.

        Args:
            current_block: Bloque actual
            start_block: Bloque donde inició el round

        Returns:
            True si ya alcanzamos o pasamos el target epoch
        """
        boundaries = self.get_round_boundaries(start_block)
        current_epoch = self.block_to_epoch(current_block)

        return current_epoch >= boundaries["target_epoch"]

    def get_wait_info(self, current_block: int, start_block: int) -> Dict[str, Any]:
        """
        Info de cuánto falta para el target epoch.

        Args:
            current_block: Bloque actual
            start_block: Bloque donde inició el round

        Returns:
            Dict con info de espera
        """
        boundaries = self.get_round_boundaries(start_block)
        current_epoch = self.block_to_epoch(current_block)

        epochs_remaining = boundaries["target_epoch"] - current_epoch
        blocks_remaining = boundaries["target_block"] - current_block
        seconds_remaining = blocks_remaining * self.SECONDS_PER_BLOCK

        return {
            "current_epoch": current_epoch,
            "target_epoch": boundaries["target_epoch"],
            "epochs_remaining": epochs_remaining,
            "blocks_remaining": blocks_remaining,
            "seconds_remaining": seconds_remaining,
            "minutes_remaining": round(seconds_remaining / 60, 1),
            "reached_target": epochs_remaining <= 0,
        }

    def log_calculation_summary(self) -> None:
        """Log un resumen de la configuración del round."""
        summary = self.get_calculation_summary()

        bt.logging.info("=" * 80)
        bt.logging.info("📊 ROUND CONFIGURATION")
        bt.logging.info("=" * 80)
        bt.logging.info(f"Round Duration:")
        bt.logging.info(f"  • {summary['round_size_epochs']} epochs = {summary['total_hours']}h")
        bt.logging.info(f"  • Total blocks: {summary['total_blocks']:,}")
        bt.logging.info(f"  • Total time: {summary['total_seconds']:,}s")
        bt.logging.info("")
        bt.logging.info(f"Task Configuration (Dynamic):")
        bt.logging.info(f"  • Avg duration per task: {summary['avg_task_duration_seconds']}s ({summary['avg_task_duration_seconds']/60:.1f}min)")
        bt.logging.info(f"  • Safety buffer: {summary['safety_buffer_epochs']} epochs ({summary['safety_buffer_seconds']}s)")
        bt.logging.info(f"  • Available time: {summary['available_hours']:.1f}h ({summary['available_seconds']:,}s)")
        bt.logging.info("")
        bt.logging.info(f"Dynamic System:")
        bt.logging.info(f"  • Tasks are sent one by one")
        bt.logging.info(f"  • Before each task: checks if there's time remaining")
        bt.logging.info(f"  • Stops when: time_remaining < avg_task_duration + safety_buffer")
        bt.logging.info(f"  • Estimated tasks (reference): ~{summary['estimated_tasks']}")
        bt.logging.info("=" * 80)
