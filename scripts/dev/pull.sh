#!/bin/bash
set -e

# Actualizar el submódulo webs_demo
SUBMODULE_PATH="autoppia_iwa_module/modules/webs_demo"
cd "$SUBMODULE_PATH" || { echo "El directorio $SUBMODULE_PATH no existe"; exit 1; }
git pull

# Volver al directorio del submódulo principal y actualizarlo
cd ../..
git pull origin main

# Volver al directorio raíz del proyecto
cd ..

git pull origin main

echo "Actualización completada para webs_demo, autoppia_iwa_module y el repositorio raíz."
