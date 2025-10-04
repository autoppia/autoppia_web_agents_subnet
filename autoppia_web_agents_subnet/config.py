import os
from distutils.util import strtobool
from pathlib import Path


# ╭─────────────────────────── Environment ─────────────────────────────╮

EPOCH_LENGTH_OVERRIDE = 0 
TESTING = False

# ╭─────────────────────────── Rounds (Epoch-based System) ─────────────────────────────╮

# Round = 1 forward completo que dura ROUND_SIZE_EPOCHS epochs
# Todos los validators sincronizan: empiezan en epoch múltiplo de ROUND_SIZE_EPOCHS
# y setean weights al llegar al target epoch

ROUND_SIZE_EPOCHS = 20              # Duración del round en epochs (~24h = 20 epochs)
# 1 epoch = 360 bloques ≈ 72 minutos
# 20 epochs = 7200 bloques ≈ 24 horas

SAFETY_BUFFER_EPOCHS = 0.5          # Buffer de seguridad en epochs antes del target
# Si quedan menos de 0.5 epochs, no envía más tasks
# 0.5 epochs ≈ 36 minutos (suficiente para última task)

AVG_TASK_DURATION_SECONDS = 600     # ⚠️ AJUSTAR ESTE VALOR según tiempo real medido
# Tiempo promedio para: enviar + evaluar 1 task (sin generación)
# Valor por defecto: 600s (10 minutos)
# Medir en producción y actualizar
# Este valor se usa para estimar si hay tiempo para otra task

PRE_GENERATED_TASKS = 120           # Número de tasks a pre-generar al inicio del round
# Se generan todas al principio para evitar errores on-the-fly
# Ajustar según estimación: (tiempo_disponible / avg_duration) + margen

# ╭─────────────────────────── Task Settings ─────────────────────────────╮

PROMPTS_PER_USECASE = 1             # Número de prompts a generar por use case
MAX_ACTIONS_LENGTH = 30             # Máximo número de acciones por solución

TIMEOUT = 60 * 2                    # 2 min: timeout para recibir respuesta de miners
FEEDBACK_TIMEOUT = 60               # 1 min: timeout para enviar feedback a miners

# ╭─────────────────────────── Rewards ─────────────────────────────╮

EVAL_SCORE_WEIGHT = 0.85            # Peso del score de evaluación (0-1)
TIME_WEIGHT = 0.15                  # Peso del tiempo de ejecución (0-1)


# ╭─────────────────────────── Leaderboard ─────────────────────────────╮

LEADERBOARD_ENDPOINT = os.getenv("LEADERBOARD_ENDPOINT", "https://leaderboard-api.autoppia.com")
LEADERBOARD_TASKS_ENDPOINT = "https://api-leaderboard.autoppia.com/tasks"
LEADERBOARD_VALIDATOR_RUNS_ENDPOINT = "https://api-leaderboard.autoppia.com/validator-runs"

SAVE_SUCCESSFUL_TASK_IN_JSON = bool(strtobool(os.getenv("SAVE_SUCCESSFUL_TASK_IN_JSON", "false")))

# ╭─────────────────────────── Stats ─────────────────────────────╮
STATS_FILE = Path("coldkey_web_usecase_stats.json")  # snapshot
