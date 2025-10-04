# 🚀 Quick Start: Sistema de Rounds

## ✅ ¿Qué se ha implementado?

Se ha creado un sistema completo donde:

1. **1 Forward = 1 Round completo = ~24 horas (20 epochs)**
2. **Cálculo automático** de cuántas tasks hacer basado en tiempo disponible
3. **Sincronización** entre validators en el mismo epoch
4. **WTA al final del round** sobre el promedio de todas las tasks

---

## 📁 Archivos Creados/Modificados

### ✅ Modificados:

- `autoppia_web_agents_subnet/config.py` → Nuevos parámetros configurables
- `autoppia_web_agents_subnet/validator/forward.py` → Reescrito completamente

### ✅ Creados:

- `autoppia_web_agents_subnet/validator/round_calculator.py` → Lógica de cálculo
- `docs/ROUND_CALIBRATION_GUIDE.md` → Guía para calibrar el sistema
- `docs/CHANGELOG_ROUND_SYSTEM.md` → Changelog detallado

---

## ⚙️ Configuración (solo en `config.py`)

```python
# autoppia_web_agents_subnet/config.py

# ════════════════════════════════════════════════
# PARÁMETROS DEL SISTEMA DE ROUNDS
# ════════════════════════════════════════════════

ROUND_SIZE_EPOCHS = 20              # Duración: 20 epochs ≈ 24 horas
                                     # (solo cambiar si quieres rounds más cortos/largos)

AVG_TASK_DURATION_SECONDS = 600     # ⚠️ ESTE ES EL QUE DEBES AJUSTAR
                                     # Tiempo promedio por batch de tasks
                                     # Valor inicial: 600s (10 min)
                                     # Después del primer round, mide tiempos
                                     # reales y ajusta este valor

SAFETY_MARGIN_TASKS = 15            # Margen de seguridad (tasks menos del teórico)
                                     # Aumentar si llegas justo al límite
                                     # Reducir si sobra mucho tiempo

TASKS_PER_BATCH = 11                # Tasks por batch (1 por cada web)
                                     # Solo cambiar si añades/quitas webs
```

**Eso es todo.** El resto se calcula automáticamente.

---

## 🎯 Cómo Funciona

### Cálculo Automático (ejemplo con valores por defecto):

```
Entrada (config.py):
  ROUND_SIZE_EPOCHS = 20
  AVG_TASK_DURATION_SECONDS = 600
  SAFETY_MARGIN_TASKS = 15
  TASKS_PER_BATCH = 11

↓ El sistema calcula automáticamente:

  Tiempo disponible: 20 epochs × 360 bloques × 12s = 86,400s (24h)
  Batches teóricos: 86,400s / 600s = 144 batches
  Tasks teóricas: 144 × 11 = 1,584 tasks
  Con margen: 1,584 - 15 = 1,569 tasks
  Batches finales: 1,569 / 11 = 142 batches

✅ Resultado: 142 batches × 11 tasks = 1,562 tasks en el round

Tiempo estimado: 142 × 600s = 85,200s (23.67h)
Buffer: 86,400 - 85,200 = 1,200s (20 minutos)
```

---

## 📊 Timeline de un Round

```
Epoch 233 (START)
│
├─ [00:00] Cálculo automático: 142 batches
│
├─ [00:00-23:40] EJECUTAR BATCHES
│  ├─ Batch 1/142: 11 tasks → acumula scores
│  ├─ Batch 2/142: 11 tasks → acumula scores
│  ├─ ...
│  └─ Batch 142/142: 11 tasks → acumula scores
│
├─ [23:40-24:00] ESPERAR TARGET EPOCH
│  └─ Esperando a que llegue epoch 253...
│
└─ Epoch 253 (TARGET)
   ├─ Calcula promedio de 1,562 tasks
   ├─ Aplica WTA → Miner 17 gana
   ├─ ⚡ SET WEIGHTS ON-CHAIN
   └─ 🔄 Empieza nuevo round (epoch 253-273)
```

---

## 🔧 Primer Uso: Paso a Paso

### 1. Revisar config.py

```bash
cd /home/tecnoturis/Escritorio/proyectos/autoppia/new_subnet/autoppia_web_agents_subnet
nano autoppia_web_agents_subnet/config.py
```

Verificar:

```python
ROUND_SIZE_EPOCHS = 20
AVG_TASK_DURATION_SECONDS = 600  # Valor inicial (ajustar después)
SAFETY_MARGIN_TASKS = 15
TASKS_PER_BATCH = 11
```

### 2. Iniciar validator

```bash
python neurons/validator.py
```

### 3. Observar logs iniciales

Verás algo como:

```
════════════════════════════════════════════════════════════
🚀 STARTING ROUND #1
   Round ID: Round-1
   Start epoch: 233 (block 83880)
   Target epoch: 252 (block 90720)
════════════════════════════════════════════════════════════

📊 ROUND CALCULATION SUMMARY
════════════════════════════════════════════════════════════
Round Configuration:
  • Duration: 20 epochs = 24.0h
  • Total blocks: 7,200
  • Total time: 86,400s

Task Configuration:
  • Tasks per batch: 11
  • Avg duration per batch: 600s (10.0min)
  • Safety margin: -15 tasks

Calculations:
  • Theoretical batches: 144
  • Theoretical tasks: 1584
  • ✅ Max batches to execute: 142
  • ✅ Max tasks to execute: 1562

Timing Estimates:
  • Estimated execution time: 23.67h
  • Safety buffer: 0.33h (1,200s)
════════════════════════════════════════════════════════════
```

### 4. Durante la ejecución

Verás logs como:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📍 BATCH 50/142 (35.2% complete) | Epoch 238/252
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
...
✅ Batch 50 completed in 612.3s
   Current top 3: [(17, '0.823'), (42, '0.789'), (8, '0.723')]
```

**⚠️ IMPORTANTE: Anota estos tiempos!**

### 5. Al terminar las tasks

```
════════════════════════════════════════════════════════════
✅ ALL 1562 TASKS COMPLETED!
════════════════════════════════════════════════════════════

⏳ Waiting for target epoch...
   Current: 251, Target: 252, Remaining: 1 epochs (~72 min)
```

Si esperas >1 hora: tu `AVG_TASK_DURATION_SECONDS` está muy bajo.

Si llegas justo al límite o te pasas: está muy alto.

### 6. Al setear weights

```
════════════════════════════════════════════════════════════
🏁 FINALIZING ROUND - CALCULATING WINNER & SETTING WEIGHTS
════════════════════════════════════════════════════════════

📊 TOP 10 MINERS (by average score):
────────────────────────────────────────────────────────────
    1. UID  17: 0.8234 (1562 tasks evaluated)
    2. UID  42: 0.7891 (1562 tasks evaluated)
    3. UID   8: 0.7234 (1561 tasks evaluated)
    ...

🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆
   WINNER: UID 17 (avg score: 0.8234, tasks: 1562)
🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆🏆

✅ WEIGHTS SET ON-CHAIN! Round duration: 23.92h
```

---

## 📈 Calibración Después del Primer Round

### Calcular tiempo promedio real:

```bash
# Extraer tiempos de los logs
grep "Batch .* completed in" validator.log | awk '{print $(NF-1)}' > batch_times.txt

# Calcular promedio
awk '{sum+=$1; count++} END {print "Average:", sum/count, "seconds"}' batch_times.txt
```

Ejemplo de salida:

```
Average: 547.8 seconds
```

### Ajustar config.py:

```python
# Si promedio real = 547.8s
AVG_TASK_DURATION_SECONDS = 570  # Promedio + pequeño margen

# O si quieres ser más conservador:
AVG_TASK_DURATION_SECONDS = 600  # Promedio + 50s de margen
```

---

## 🚨 Troubleshooting Rápido

| Problema                   | Solución                                                                  |
| -------------------------- | ------------------------------------------------------------------------- |
| Espero >2h al target epoch | Reducir `AVG_TASK_DURATION_SECONDS` en 50-100s                            |
| Me paso del target epoch   | Aumentar `AVG_TASK_DURATION_SECONDS` en 50-100s o `SAFETY_MARGIN_TASKS`   |
| Tasks timeout mucho        | Aumentar `TIMEOUT` en config y ajustar `AVG_TASK_DURATION_SECONDS` acorde |
| Batches tardan <5 min      | Reducir `AVG_TASK_DURATION_SECONDS`                                       |
| Batches tardan >15 min     | Aumentar `AVG_TASK_DURATION_SECONDS`                                      |

---

## 📚 Documentación Completa

- **`docs/ROUND_CALIBRATION_GUIDE.md`**: Guía detallada de calibración
- **`docs/CHANGELOG_ROUND_SYSTEM.md`**: Cambios técnicos completos
- **`validator/round_calculator.py`**: Código con docstrings

---

## ✅ Checklist de Primera Ejecución

- [ ] Revisar `config.py` (valores por defecto ok)
- [ ] Iniciar validator
- [ ] Verificar logs de cálculo inicial
- [ ] Monitorear primer round completo (24h)
- [ ] Anotar tiempos reales de batches
- [ ] Calcular promedio real
- [ ] Ajustar `AVG_TASK_DURATION_SECONDS`
- [ ] Ejecutar segundo round para validar

---

## 🎉 ¡Listo!

El sistema está **100% funcional** con la configuración por defecto.

Solo necesitas:

1. Ejecutar el validator
2. Esperar al primer round completo
3. Medir tiempos reales
4. Ajustar `AVG_TASK_DURATION_SECONDS` en `config.py`

**Todo lo demás se calcula automáticamente.** 🚀


