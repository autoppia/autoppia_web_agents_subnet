#!/bin/bash

# Script para arreglar problemas comunes con submódulos
# Úsalo cuando git pull falle con errores de submódulos

echo "🔧 Arreglando referencias de submódulos..."
echo ""

# Actualizar submódulos a lo que está disponible actualmente
cd autoppia_iwa_module
echo "📦 Actualizando autoppia_iwa_module..."
git fetch origin
git checkout main
git pull origin main

cd modules/webs_demo
echo "📦 Actualizando modules/webs_demo..."
git fetch origin
git checkout main
git pull origin main

cd ../..

echo ""
echo "✅ Submódulos actualizados"
echo ""
echo "📝 Estado actual:"
git submodule status --recursive
echo ""
echo "⚠️   Si quieres guardar estos cambios en tu rama:"
echo "   git add autoppia_iwa_module"
echo "   git commit -m 'Update submodule references'"
echo "   git push"

