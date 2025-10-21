#!/bin/bash

# Script para arreglar el estado de Git en el servidor cuando queda bloqueado
# Ejecutar en el servidor cuando veas "unmerged paths" o merges a medias

echo "🧹 Limpiando estado de Git en el servidor..."
echo ""

# Verificar que estamos en el directorio correcto
if [ ! -d .git ]; then
    echo "❌ ERROR: No estás en un repositorio git"
    echo "   cd ~/autoppia_web_agents_subnet"
    exit 1
fi

BRANCH=$(git branch --show-current)
echo "📌 Rama actual: $BRANCH"
echo ""

# Advertencia
echo "⚠️  ADVERTENCIA: Esto eliminará TODOS los cambios locales"
echo "   y reseteará el repo al estado de origin/$BRANCH"
echo ""
read -p "¿Continuar? (s/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Ss]$ ]]; then
    echo "❌ Cancelado"
    exit 1
fi

echo ""
echo "🗑️  Paso 1/7: Eliminando archivos de estado de merge..."
rm -f .git/AUTO_MERGE
rm -f .git/MERGE_HEAD
rm -f .git/MERGE_MODE
rm -f .git/MERGE_MSG
rm -f .git/CHERRY_PICK_HEAD
rm -f .git/REBASE_HEAD
rm -f .git/REVERT_HEAD
echo "✅ Archivos de estado eliminados"

echo ""
echo "🔄 Paso 2/7: Reseteando al último commit..."
git reset --hard HEAD
echo "✅ Reset completado"

echo ""
echo "🧹 Paso 3/7: Limpiando archivos no rastreados..."
git clean -fd
echo "✅ Limpieza completada"

echo ""
echo "📥 Paso 4/7: Descargando últimos cambios de origin..."
git fetch origin $BRANCH
echo "✅ Fetch completado"

echo ""
echo "🔄 Paso 5/7: Reseteando a origin/$BRANCH..."
git reset --hard origin/$BRANCH
echo "✅ Reset a remoto completado"

echo ""
echo "📦 Paso 6/7: Limpiando submódulos..."
git submodule foreach --recursive git reset --hard 2>/dev/null || true
echo "✅ Submódulos limpiados"

echo ""
echo "📦 Paso 7/7: Actualizando submódulos..."
git submodule update --init --recursive
echo "✅ Submódulos actualizados"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ ¡ARREGLADO! Estado final del servidor:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
git status
echo ""
echo "📦 Estado de submódulos:"
git submodule status --recursive
echo ""
echo "🎉 El servidor está limpio y sincronizado con origin/$BRANCH"

