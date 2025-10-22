#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# Script para probar el sistema de recovery del validador
# ═══════════════════════════════════════════════════════════════════════════════
# Uso: bash scripts/test_recovery.sh
# ═══════════════════════════════════════════════════════════════════════════════

set -e

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}╔════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║         VALIDATOR RECOVERY TEST SCRIPT                        ║${NC}"
echo -e "${CYAN}╚════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Variables
VALIDATOR_PROCESS="validator_6am"
CHECKPOINT_DIR="/data/validator_state/round_state"
LOG_FILE="/tmp/recovery_test_$(date +%Y%m%d_%H%M%S).log"

# ═══════════════════════════════════════════════════════════════════════════════
# Funciones auxiliares
# ═══════════════════════════════════════════════════════════════════════════════

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1" | tee -a "$LOG_FILE"
}

log_warning() {
    echo -e "${YELLOW}[⚠]${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1" | tee -a "$LOG_FILE"
}

wait_for_checkpoint() {
    local timeout=$1
    local start_time=$(date +%s)
    
    log_info "Esperando checkpoint... (timeout: ${timeout}s)"
    
    while [ $(($(date +%s) - start_time)) -lt $timeout ]; do
        if ls "$CHECKPOINT_DIR"/*.pkl >/dev/null 2>&1; then
            local checkpoint_file=$(ls -t "$CHECKPOINT_DIR"/*.pkl 2>/dev/null | head -1)
            local checkpoint_size=$(stat -f%z "$checkpoint_file" 2>/dev/null || stat -c%s "$checkpoint_file" 2>/dev/null)
            log_success "Checkpoint encontrado: $(basename "$checkpoint_file") (${checkpoint_size} bytes)"
            return 0
        fi
        sleep 2
    done
    
    log_error "Timeout esperando checkpoint"
    return 1
}

get_checkpoint_info() {
    local checkpoint_file=$(ls -t "$CHECKPOINT_DIR"/*.pkl 2>/dev/null | head -1)
    
    if [ -z "$checkpoint_file" ]; then
        log_warning "No se encontró checkpoint"
        return 1
    fi
    
    echo ""
    log_info "═══ CHECKPOINT INFO ═══"
    log_info "Archivo: $(basename "$checkpoint_file")"
    log_info "Tamaño: $(du -h "$checkpoint_file" | cut -f1)"
    log_info "Fecha: $(stat -f%Sm "$checkpoint_file" 2>/dev/null || stat -c%y "$checkpoint_file" 2>/dev/null)"
    echo ""
}

get_validator_stats() {
    log_info "═══ VALIDATOR STATS ═══"
    
    # Buscar en logs las últimas líneas relevantes
    pm2 logs "$VALIDATOR_PROCESS" --nostream --lines 50 | grep -E "Task [0-9]+/|completed|Checkpoint|Resume" | tail -10
    
    echo ""
}

# ═══════════════════════════════════════════════════════════════════════════════
# PASO 1: Verificar estado inicial
# ═══════════════════════════════════════════════════════════════════════════════

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}PASO 1: Verificación del estado inicial${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

# Verificar que el validador esté corriendo
if ! pm2 describe "$VALIDATOR_PROCESS" >/dev/null 2>&1; then
    log_error "El validador '$VALIDATOR_PROCESS' no está corriendo"
    log_info "Iniciando validador..."
    pm2 start "$VALIDATOR_PROCESS" || {
        log_error "No se pudo iniciar el validador"
        exit 1
    }
    sleep 5
fi

log_success "Validador '$VALIDATOR_PROCESS' está corriendo"

# Verificar directorio de checkpoints
if [ ! -d "$CHECKPOINT_DIR" ]; then
    log_warning "Directorio de checkpoints no existe: $CHECKPOINT_DIR"
    log_info "Se creará automáticamente cuando el validador guarde el primer checkpoint"
else
    log_success "Directorio de checkpoints existe: $CHECKPOINT_DIR"
fi

# Mostrar checkpoints existentes
if ls "$CHECKPOINT_DIR"/*.pkl >/dev/null 2>&1; then
    log_info "Checkpoints existentes:"
    ls -lh "$CHECKPOINT_DIR"/*.pkl
else
    log_warning "No hay checkpoints previos"
fi

echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# PASO 2: Esperar a que se genere un checkpoint
# ═══════════════════════════════════════════════════════════════════════════════

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}PASO 2: Esperando generación de checkpoint${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

log_info "El validador debe completar al menos 1 tarea para generar un checkpoint"
log_info "Esto puede tomar 5-10 minutos..."
echo ""

# Esperar hasta 600 segundos (10 minutos)
if ! wait_for_checkpoint 600; then
    log_error "No se generó checkpoint en 10 minutos"
    log_info "Verifica los logs del validador:"
    log_info "  pm2 logs $VALIDATOR_PROCESS"
    exit 1
fi

get_checkpoint_info
get_validator_stats

# ═══════════════════════════════════════════════════════════════════════════════
# PASO 3: Simular crash (matar el proceso)
# ═══════════════════════════════════════════════════════════════════════════════

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}PASO 3: Simulando crash del validador${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

log_warning "Matando el proceso del validador..."

# Obtener PID
VALIDATOR_PID=$(pm2 describe "$VALIDATOR_PROCESS" | grep "pid" | awk '{print $4}')

if [ -n "$VALIDATOR_PID" ] && [ "$VALIDATOR_PID" != "0" ]; then
    log_info "PID del validador: $VALIDATOR_PID"
    kill -9 "$VALIDATOR_PID" 2>/dev/null || true
    sleep 2
    log_success "Proceso matado (simulando crash)"
else
    log_warning "No se pudo obtener PID, usando pm2 stop"
    pm2 stop "$VALIDATOR_PROCESS"
fi

# Verificar que el checkpoint sigue existiendo
if ls "$CHECKPOINT_DIR"/*.pkl >/dev/null 2>&1; then
    log_success "Checkpoint preservado después del crash ✓"
    get_checkpoint_info
else
    log_error "¡Checkpoint perdido! Esto es un BUG"
    exit 1
fi

echo ""

# ═══════════════════════════════════════════════════════════════════════════════
# PASO 4: Reiniciar y verificar recovery
# ═══════════════════════════════════════════════════════════════════════════════

echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}PASO 4: Reiniciando validador y verificando recovery${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

log_info "Reiniciando validador..."
pm2 restart "$VALIDATOR_PROCESS"
sleep 5

log_success "Validador reiniciado"
echo ""

# Esperar y verificar logs de recovery
log_info "Verificando logs de recovery..."
sleep 10

echo ""
log_info "═══ LOGS DE RECOVERY ═══"
pm2 logs "$VALIDATOR_PROCESS" --nostream --lines 100 | grep -E "Checkpoint loaded|Resume|Skipping task|resumed=True" | head -20

echo ""

# Verificar que el checkpoint se está usando
if pm2 logs "$VALIDATOR_PROCESS" --nostream --lines 100 | grep -q "Checkpoint loaded"; then
    log_success "✓ Recovery exitoso: Checkpoint cargado"
else
    log_error "✗ Recovery falló: No se cargó el checkpoint"
    exit 1
fi

if pm2 logs "$VALIDATOR_PROCESS" --nostream --lines 100 | grep -q "resumed=True"; then
    log_success "✓ Recovery exitoso: Round resumido"
else
    log_warning "⚠ No se detectó 'resumed=True' en los logs"
fi

if pm2 logs "$VALIDATOR_PROCESS" --nostream --lines 100 | grep -q "Skipping task"; then
    log_success "✓ Recovery exitoso: Saltando tareas completadas"
else
    log_warning "⚠ No se detectó 'Skipping task' (puede que no haya tareas completadas aún)"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# RESUMEN FINAL
# ═══════════════════════════════════════════════════════════════════════════════

echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}RESUMEN DEL TEST${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════════${NC}"
echo ""

get_checkpoint_info
get_validator_stats

echo ""
log_success "═══════════════════════════════════════════════════════════════"
log_success "TEST DE RECOVERY COMPLETADO"
log_success "═══════════════════════════════════════════════════════════════"
echo ""
log_info "Log guardado en: $LOG_FILE"
echo ""
log_info "Para monitorear el validador:"
log_info "  pm2 logs $VALIDATOR_PROCESS"
echo ""
log_info "Para ver checkpoints:"
log_info "  ls -lh $CHECKPOINT_DIR/"
echo ""

