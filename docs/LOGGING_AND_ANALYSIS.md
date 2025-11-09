# 📊 Sistema de Logging y Análisis de Rounds

## 🎯 Resumen

El validator ahora captura **errores y warnings** de dos formas:

1. ✅ **En memoria (durante ejecución)** - método principal
2. ✅ **Desde logs por round** - método secundario para análisis históricos

## 🔄 Cómo Funciona

### Durante la Ejecución del Round

El validator captura errores/warnings EN TIEMPO REAL usando `_report_error()` y `_report_warning()`:

```python
# Ejemplo: cuando set_weights falla
if result is True:
    bt.logging.info("set_weights on chain successfully!")
    self._report_weights_set(success=True)
else:
    bt.logging.error("set_weights failed", msg)
    self._report_weights_set(success=False)
    self._report_error(f"set_weights failed: {msg}")  # ← Capturado en memoria
```

Estos se almacenan en `RoundReport.errors` y `RoundReport.warnings` y se incluyen en el email automáticamente.

### Análisis de Rounds Antiguos (Round 67, 68, etc.)

Para analizar rounds que YA terminaron, el sistema intenta leer logs específicos por round:

```python
# En _extract_errors_warnings_from_logs()
round_log = repo_root / "data" / "logs" / "rounds" / f"round_{report.round_number}.log"
if round_log.exists():
    # Extrae errores/warnings SOLO de ese round
    ...
else:
    # Si no existe, solo usa lo que se capturó en memoria
    return
```

**⚠️ IMPORTANTE**: Si el log splitter NO está activo, los logs por round NO se generan y el análisis de rounds antiguos será limitado.

## 🚀 Configurar Log Splitter (NECESARIO para análisis históricos)

### Estado Actual

```bash
ssh contabo-iwap-dev
pm2 list | grep log
```

Si ves `report-log-splitter` en estado `errored` o `stopped`, necesitas activarlo.

### Solución 1: Configuración Automática (Recomendado)

```bash
ssh contabo-iwap-dev
cd /home/admin/autoppia_web_agents_subnet
bash scripts/validator/reporting/setup_round_logs.sh
```

### Solución 2: Manual

El problema es que el log splitter necesita recibir los logs del validator. Actualmente PM2 maneja los logs del validator y el splitter no tiene acceso.

**Opción A: Redirigir PM2 logs al splitter**

```bash
# Parar el splitter viejo
pm2 delete report-log-splitter

# Iniciar con tail de PM2 logs
pm2 start bash --name "report-log-splitter" -- -c \
  "tail -F ~/.pm2/logs/validator-wta-out.log | python3 /home/admin/autoppia_web_agents_subnet/scripts/validator/utils/simple_log_splitter.py"

pm2 save
```

**Opción B: Cambiar cómo se inicia el validator**

Modificar el comando PM2 del validator para que pase por el splitter:

```bash
# ecosystem.config.js o comando PM2
python3 neurons/validator.py --netuid 36 2>&1 | \
  tee >(python3 scripts/validator/utils/simple_log_splitter.py)
```

## 📁 Estructura de Logs

```
data/logs/rounds/
├── round_167.log    # Todos los logs del round 167
├── round_168.log    # Todos los logs del round 168
└── round_169.log    # Todos los logs del round 169 (actual)
```

Cada archivo contiene SOLO los logs de ese round específico.

## 🤖 Análisis Inteligente (Codex)

El sistema ya NO depende de un comando externo `codex`. Ahora tiene análisis inteligente incorporado que detecta:

### ✅ Detecciones Automáticas

1. **Errores de set_weights**

   ```
   ⚠️ CRITICAL: Weights could not be set on-chain.
   This is likely due to insufficient stake or blockchain connection issues.
   ```

2. **Transacciones inválidas**

   ```
   ⚠️ Blockchain transaction failed - check validator stake and connection status.
   ```

3. **Checkpoints no completados**

   ```
   • Weights were NOT set on-chain - Validator likely lacks minimum stake
     (10,000 τ required in production).
   ```

4. **Ganador del round**

   ```
   • Winner: Miner UID 2 with 100.0% success rate.
   ```

5. **Proyectos con problemas**

   ```
   • Web projects with 0% success: photoshare, quickbite -
     these projects may be down or misconfigured.
   ```

6. **Proyectos con bajo rendimiento**

   ```
   • Low success rate on: autorepair (15.0%), chatapp (22.5%)
   ```

7. **Problemas de consensus**
   ```
   • No other validators participated in consensus -
     validator may be isolated or in testing mode.
   ```

## 🔍 Verificación

### 1. Verificar que el validator captura errores en memoria

```bash
# Durante un round, revisa los logs
pm2 logs validator-wta | grep -i error
```

Si ves errores, deberían aparecer en el email del round.

### 2. Verificar que se generan logs por round

```bash
ssh contabo-iwap-dev
ls -lh /home/admin/autoppia_web_agents_subnet/data/logs/rounds/

# Deberías ver archivos como:
# round_167.log
# round_168.log
# round_169.log
```

### 3. Verificar que el log splitter está funcionando

```bash
pm2 logs report-log-splitter --lines 50

# Deberías ver mensajes como:
# [2025-11-09 12:00:00] Log splitter started
# [2025-11-09 12:00:00] Started logging round 169 → /home/.../round_169.log
```

### 4. Leer el log de un round específico

```bash
cat /home/admin/autoppia_web_agents_subnet/data/logs/rounds/round_169.log | grep -i error
```

## 🐛 Troubleshooting

### Problema: "Codex analysis not available for this round"

**Causa**: Antes intentaba ejecutar un comando `codex` que no existía.

**Solución**: Ya está arreglado. Ahora usa análisis incorporado.

### Problema: "Errors & Warnings" está vacío en el email

**Causas posibles**:

1. El round realmente no tuvo errores (poco probable)
2. Los logs por round no existen (splitter inactivo)
3. Los errores no se están capturando en memoria durante ejecución

**Solución**:

1. Verificar que `_report_error()` se llama cuando ocurren errores
2. Activar el log splitter (ver arriba)
3. Esperar al siguiente round para verificar

### Problema: El log splitter crashea constantemente

**Causa**: Probablemente no recibe input de stdin.

**Solución**: Usar la opción A de configuración manual (tail -F de PM2 logs).

## 📧 Email Report Checklist

El email ahora incluye estos checkpoints:

- ✅ Tasks Generated
- ✅ Handshake Sent
- ✅ Tasks Evaluated
- ✅ Publishing Results on IPFS
- ✅ Downloaded Results from IPFS
- ✅ Select Winner of Round
- ✅ **Set Weights** ← NUEVO

Estados posibles:

- ✓ Done (verde) - Checkpoint completado exitosamente
- ✗ Error (rojo) - Checkpoint falló pero el round terminó
- ⏸ Pending (amarillo) - Round aún en progreso

**Ya no hay "Skipped"** - solo Done, Error o Pending.

## 🎯 Ejemplo de Email Completo

```
Round Progress Checklist
┌────────────────────────────────┬─────────┐
│ Checkpoint                     │ Status  │
├────────────────────────────────┼─────────┤
│ Tasks Generated                │ ✓ Done  │
│ Handshake Sent                 │ ✓ Done  │
│ Tasks Evaluated                │ ✓ Done  │
│ Publishing Results on IPFS     │ ✓ Done  │
│ Downloaded Results from IPFS   │ ✗ Error │ ← No hay otros validators
│ Select Winner of Round         │ ✓ Done  │
│ Set Weights                    │ ✗ Error │ ← Sin stake suficiente
└────────────────────────────────┴─────────┘

Errors & Warnings
❌ Errors (5)
1. set_weights failed: Subtensor returned: Invalid Transaction
2. set_weights failed: Subtensor returned: Invalid Transaction
3. set_weights failed: Subtensor returned: Invalid Transaction
4. set_weights failed: Subtensor returned: Invalid Transaction
5. set_weights failed: Subtensor returned: Invalid Transaction

🤖 Codex AI Analysis
⚠️ CRITICAL: Weights could not be set on-chain. This is likely due to
insufficient stake or blockchain connection issues.

• Weights were NOT set on-chain - Validator likely lacks minimum stake
  (10,000 τ required in production).

• Winner: Miner UID 2 with 100.0% success rate.

• Only aurocinema has good success rate - other projects need attention.

• No other validators participated in consensus - validator may be isolated
  or in testing mode.
```

## 📝 Notas Finales

1. **Captura en memoria es la fuente principal** - los logs son backup
2. **Log splitter es OPCIONAL** pero recomendado para análisis históricos
3. **Codex AI ahora funciona sin dependencias externas**
4. **Checkpoints ahora son Done/Error/Pending** - no más "Skipped"
5. **Todos los errores importantes se capturan automáticamente**
