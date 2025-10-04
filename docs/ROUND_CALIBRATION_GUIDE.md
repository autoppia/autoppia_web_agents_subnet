# 📊 Guía de Calibración del Sistema de Rounds

## 🎯 Objetivo

Este sistema calcula **automáticamente** cuántas tasks puede ejecutar el validator en un round completo (típicamente 24h = 20 epochs). El único parámetro que **debes ajustar según tu experiencia real** es:

```python
AVG_TASK_DURATION_SECONDS = 600  # ⚠️ AJUSTAR ESTE VALOR
```

---

## 📐 ¿Qué es `AVG_TASK_DURATION_SECONDS`?

Es el **tiempo promedio** que tarda tu validator en:

1. **Generar** un batch de tasks (11 tasks, 1 por web)
2. **Enviar** a todos los miners activos
3. **Esperar** respuestas (con timeout)
4. **Evaluar** todas las respuestas
5. **Enviar** feedback

**Valor por defecto:** `600` segundos = 10 minutos

---

## 🔬 Cómo Medir el Tiempo Real

### Método 1: Revisar logs del validator

Cuando ejecutes el validator, en cada batch verás:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📍 BATCH 1/129 (0.8% complete) | Epoch 233/253
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
...
✅ Batch 1 completed in 547.3s
```

**Anota el tiempo de varios batches** y calcula el promedio.

### Método 2: Script de medición automática

Crea un pequeño script para trackear tiempos:

```python
# measure_batch_time.py
import numpy as np

# Copia estos valores de tus logs
batch_times = [
    547.3,  # Batch 1
    612.8,  # Batch 2
    589.4,  # Batch 3
    601.2,  # Batch 4
    # ... añade más
]

avg_time = np.mean(batch_times)
std_time = np.std(batch_times)

print(f"Average batch time: {avg_time:.1f}s ({avg_time/60:.1f}min)")
print(f"Standard deviation: {std_time:.1f}s")
print(f"\nRecommended config:")
print(f"AVG_TASK_DURATION_SECONDS = {int(avg_time + std_time)}  # avg + 1 std")
```

---

## ⚙️ Configuración en `config.py`

### Parámetros principales

```python
# autoppia_web_agents_subnet/config.py

# ╭─────────────────────────── Rounds (Epoch-based System) ─────────────────────────────╮

ROUND_SIZE_EPOCHS = 20              # Duración del round en epochs (~24h)
                                     # 20 epochs = 7200 bloques ≈ 24 horas
                                     # NO cambiar a menos que quieras rounds más cortos/largos

SAFETY_MARGIN_TASKS = 15            # Reducir N tasks del cálculo teórico
                                     # Si terminas MUY antes del target epoch: reducir a 10
                                     # Si llegas justo o pasas: aumentar a 20-25

AVG_TASK_DURATION_SECONDS = 600     # ⚠️ ESTE ES EL QUE AJUSTAS
                                     # Valor inicial: 600s (10 min)
                                     # Ajustar después de medir tiempos reales

TASKS_PER_BATCH = 11                # Número de web projects activos
                                     # Solo cambiar si añades/quitas webs
```

---

## 📊 Ejemplo de Cálculo

Con la configuración por defecto:

```
ROUND_SIZE_EPOCHS = 20
AVG_TASK_DURATION_SECONDS = 600
SAFETY_MARGIN_TASKS = 15
TASKS_PER_BATCH = 11
```

### Cálculo automático:

```
1. Tiempo total disponible:
   20 epochs × 360 bloques/epoch × 12s/bloque = 86,400s (24h)

2. Batches teóricos:
   86,400s / 600s = 144 batches

3. Tasks teóricas:
   144 batches × 11 tasks/batch = 1,584 tasks

4. Aplicar margen de seguridad:
   1,584 - 15 = 1,569 tasks

5. Batches finales:
   1,569 / 11 = 142 batches (redondeado hacia abajo)

6. Tasks totales:
   142 batches × 11 = 1,562 tasks
```

### Tiempo estimado:

```
Ejecución: 142 × 600s = 85,200s (23.67h)
Buffer: 86,400 - 85,200 = 1,200s (0.33h = 20 min)
```

**Con este cálculo, el validator terminará ~20 minutos antes del target epoch.**

---

## 🎛️ Ajustes según tu caso

### Escenario 1: Terminas MUCHO antes (2-3 horas de buffer)

```python
# Tu tiempo real es menor al configurado
# Ejemplo: batches tardan ~450s pero configuraste 600s

# ✅ SOLUCIÓN: Reducir AVG_TASK_DURATION_SECONDS
AVG_TASK_DURATION_SECONDS = 480  # Más realista

# O reducir margen de seguridad
SAFETY_MARGIN_TASKS = 10
```

### Escenario 2: Llegas justo o te pasas del target epoch

```python
# Tu tiempo real es mayor al configurado
# Ejemplo: batches tardan ~720s pero configuraste 600s

# ✅ SOLUCIÓN: Aumentar AVG_TASK_DURATION_SECONDS
AVG_TASK_DURATION_SECONDS = 750  # Con margen extra

# O aumentar margen de seguridad
SAFETY_MARGIN_TASKS = 25
```

### Escenario 3: Quieres rounds más cortos (12h en vez de 24h)

```python
# Cambiar duración del round
ROUND_SIZE_EPOCHS = 10  # 10 epochs ≈ 12 horas

# Todo lo demás se ajusta automáticamente
```

---

## 🔍 Monitoreo en Producción

### Logs importantes a revisar:

1. **Al inicio del round:**

```
📊 ROUND CALCULATION SUMMARY
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
```

2. **Durante la ejecución:**

```
✅ Batch 50 completed in 612.3s
   Current top 3: [(17, '0.823'), (42, '0.789'), (8, '0.723')]
```

3. **En la fase de espera:**

```
⏳ Waiting for target epoch... Current: 252, Target: 253, Remaining: 1 epochs (~72 min)
```

**Si ves que esperas >1 hora:** Tu `AVG_TASK_DURATION_SECONDS` está configurado muy bajo.

**Si llegas al target antes de terminar tasks:** Tu `AVG_TASK_DURATION_SECONDS` está configurado muy alto.

---

## ✅ Checklist de Primera Ejecución

1. **Iniciar con valores por defecto**

   ```python
   AVG_TASK_DURATION_SECONDS = 600
   SAFETY_MARGIN_TASKS = 15
   ```

2. **Ejecutar 1 round completo y monitorear:**

   - ¿Cuánto tardan los batches realmente?
   - ¿Cuánto tiempo esperaste al target epoch?
   - ¿Terminaste todas las tasks a tiempo?

3. **Calcular promedio real:**

   ```bash
   # Extraer tiempos de logs
   grep "Batch .* completed in" logfile.log | awk '{print $(NF-1)}' > batch_times.txt

   # Calcular promedio
   awk '{sum+=$1; count++} END {print sum/count}' batch_times.txt
   ```

4. **Ajustar config.py:**

   ```python
   # Si promedio real = 547s
   AVG_TASK_DURATION_SECONDS = 570  # Promedio + margen pequeño
   ```

5. **Ejecutar otro round y validar**

---

## 📈 Optimización Avanzada

### Factores que afectan el tiempo de batch:

- **Número de miners activos:** Más miners = más respuestas que procesar
- **Timeout configurado:** `TIMEOUT = 120` afecta el tiempo máximo de espera
- **Complejidad de las tasks:** Tasks más complejas tardan más en evaluarse
- **Hardware del validator:** CPU/RAM afectan la velocidad de evaluación

### Fórmula refinada:

```python
# Para cálculo más preciso
base_time = 180  # Tiempo de generación + envío
wait_time = TIMEOUT  # Tiempo máximo de espera
eval_time = 60  # Tiempo de evaluación por batch
feedback_time = 20  # Tiempo de feedback

AVG_TASK_DURATION_SECONDS = base_time + wait_time + eval_time + feedback_time
# Ejemplo: 180 + 120 + 60 + 20 = 380s (6.3 min)
```

---

## 🚨 Troubleshooting

### Problema: "No tasks completed before target epoch"

**Causa:** `AVG_TASK_DURATION_SECONDS` es demasiado bajo.

**Solución:**

```python
AVG_TASK_DURATION_SECONDS = 900  # Aumentar significativamente
SAFETY_MARGIN_TASKS = 30  # Más margen
```

### Problema: "Waited 4 hours for target epoch"

**Causa:** `AVG_TASK_DURATION_SECONDS` es demasiado alto.

**Solución:**

```python
AVG_TASK_DURATION_SECONDS = 400  # Reducir
SAFETY_MARGIN_TASKS = 10  # Menos margen
```

### Problema: "Tasks timing out frequently"

**Causa:** `TIMEOUT` es muy corto para tus miners.

**Solución:**

```python
TIMEOUT = 60 * 3  # 3 minutos
AVG_TASK_DURATION_SECONDS = 700  # Ajustar acorde
```

---

## 📝 Template de Configuración Comentado

```python
# config.py - Sección de Rounds

# ═══════════════════════════════════════════════════════════
# CONFIGURACIÓN DE ROUNDS
# ═══════════════════════════════════════════════════════════

# Duración del round (NO modificar a menos que cambies estrategia)
ROUND_SIZE_EPOCHS = 20  # 20 epochs ≈ 24 horas

# ⚠️ PARÁMETRO PRINCIPAL A AJUSTAR ⚠️
# Medir en producción y actualizar según tiempos reales
# Ver: docs/ROUND_CALIBRATION_GUIDE.md
AVG_TASK_DURATION_SECONDS = 600  # TODO: Ajustar después del primer round

# Margen de seguridad (tasks a restar del cálculo teórico)
# Aumentar si llegas justo al límite, reducir si sobra mucho tiempo
SAFETY_MARGIN_TASKS = 15

# Tasks por batch (= número de web projects activos)
TASKS_PER_BATCH = 11  # Solo cambiar si añades/quitas webs

# ═══════════════════════════════════════════════════════════
```

---

## 💡 Consejos Finales

1. **Empieza conservador:** Mejor terminar 1-2h antes que pasarse del límite
2. **Monitorea el primer round completo:** No optimices hasta tener datos reales
3. **Ajusta incrementalmente:** Cambios de ±50-100s son suficientes
4. **Documenta tus cambios:** Guarda un log de qué configuraciones probaste
5. **Considera variabilidad:** Añade 10-15% extra al promedio medido

---

¿Preguntas? Revisa los logs del validator o contacta al equipo de desarrollo.
