#!/bin/bash

# Script para verificar que TODO está bien antes de hacer push
# Ejecuta esto SIEMPRE antes de git push para no romper el repo

echo "🔍 Verificando estado antes de push..."
echo ""

# Verificar que estamos en un repo git
if [ ! -d .git ]; then
    echo "❌ ERROR: No estás en un repositorio git"
    exit 1
fi

# Ver en qué rama estamos
BRANCH=$(git branch --show-current)
echo "📌 Rama actual: $BRANCH"
echo ""

# Verificar que no hay cambios sin commit
if ! git diff-index --quiet HEAD --; then
    echo "⚠️  ADVERTENCIA: Tienes cambios sin hacer commit"
    echo ""
    git status --short
    echo ""
    read -p "¿Quieres hacer commit ahora? (s/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Ss]$ ]]; then
        echo "📝 Ejecuta:"
        echo "   git add ."
        echo "   git commit -m 'tu mensaje'"
        echo "   Luego vuelve a ejecutar este script"
        exit 1
    fi
fi

# Verificar estado de submódulos
echo "📦 Verificando submódulos..."
SUBMODULE_STATUS=$(git submodule status --recursive)
echo "$SUBMODULE_STATUS"
echo ""

# Verificar si hay submódulos con referencias adelantadas (-)
if echo "$SUBMODULE_STATUS" | grep -q "^-"; then
    echo "❌ ERROR: Hay submódulos sin inicializar"
    echo "   Ejecuta: git submodule update --init --recursive"
    exit 1
fi

# Verificar si hay submódulos con cambios (+)
if echo "$SUBMODULE_STATUS" | grep -q "^+"; then
    echo "⚠️  ADVERTENCIA: Los submódulos tienen cambios"
    echo ""
    echo "🔧 Arreglando submódulos..."
    
    # Ir al submódulo principal
    cd autoppia_iwa_module
    
    # Verificar si está en main
    SUBMODULE_BRANCH=$(git branch --show-current)
    if [ "$SUBMODULE_BRANCH" != "main" ]; then
        echo "   Cambiando autoppia_iwa_module a main..."
        git fetch origin
        git checkout main
    fi
    
    # Actualizar a lo último de main
    echo "   Actualizando autoppia_iwa_module a latest main..."
    git pull origin main
    
    # Volver al repo principal
    cd ..
    
    # Agregar la actualización del submódulo
    echo "   Agregando cambio de submódulo..."
    git add autoppia_iwa_module
    
    echo ""
    echo "✅ Submódulo actualizado a main"
    echo ""
    echo "⚠️  DEBES hacer commit de este cambio:"
    echo "   git commit -m 'Update autoppia_iwa_module to latest main'"
    echo "   Luego vuelve a ejecutar este script"
    exit 1
fi

# Verificar que estamos sincronizados con origin
echo "🔄 Verificando sincronización con origin..."
git fetch origin $BRANCH

LOCAL=$(git rev-parse @)
REMOTE=$(git rev-parse @{u})
BASE=$(git merge-base @ @{u})

if [ $LOCAL = $REMOTE ]; then
    echo "✅ Tu rama está actualizada con origin/$BRANCH"
elif [ $LOCAL = $BASE ]; then
    echo "⚠️  Tu rama está DETRÁS de origin/$BRANCH"
    echo "   Ejecuta primero: git pull origin $BRANCH"
    exit 1
elif [ $REMOTE = $BASE ]; then
    echo "✅ Tu rama está ADELANTE de origin/$BRANCH (tienes commits para subir)"
else
    echo "⚠️  Tu rama y origin/$BRANCH han DIVERGIDO"
    echo "   Ejecuta primero: git pull origin $BRANCH"
    echo "   Resuelve conflictos si los hay, luego vuelve a ejecutar este script"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ TODO ESTÁ BIEN - Puedes hacer push seguro"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📤 Ejecuta:"
echo "   git push origin $BRANCH"
echo ""

