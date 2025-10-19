# 🔧 Instrucciones para Re-clonar el Repositorio

### ⚠️ Si rompiste el repositorio con un push, sigue estos pasos:

### 1. Respaldar tu trabajo (por si acaso)

```bash
# Ir a tu directorio de trabajo actual
cd ~/autoppia_web_agents_subnet  # o donde esté tu repo

# Crear una carpeta de respaldo con tus cambios
mkdir -p ~/backup_trabajo_$(date +%Y%m%d)

# Copiar SOLO los archivos que modificaste (ejemplos)
# Ajusta según los archivos que hayas cambiado
cp autoppia_web_agents_subnet/validator/config.py ~/backup_trabajo_$(date +%Y%m%d)/
cp neurons/validator.py ~/backup_trabajo_$(date +%Y%m%d)/
# etc...

# O si quieres, respalda todo (pero tarda más)
cp -r ~/autoppia_web_agents_subnet ~/backup_autoppia_$(date +%Y%m%d)
```

### 2. Eliminar el repositorio corrupto

```bash
# Salir del directorio
cd ~

# Eliminar el repo corrupto
rm -rf autoppia_web_agents_subnet
```

### 3. Clonar de nuevo LIMPIO

```bash
# Clonar el repositorio
git clone https://github.com/autoppia/autoppia_web_agents_subnet.git

# Entrar al directorio
cd autoppia_web_agents_subnet

# Cambiar a la rama leaderboard
git checkout leaderboard

# Inicializar y actualizar TODOS los submódulos recursivamente
git submodule update --init --recursive

# Verificar que todo está bien
git status
git submodule status --recursive
```

### 4. Recuperar tus cambios (si los necesitas)

```bash
# Copiar de vuelta los archivos que habías modificado
cp ~/backup_trabajo_YYYYMMDD/config.py autoppia_web_agents_subnet/validator/
cp ~/backup_trabajo_YYYYMMDD/validator.py neurons/

# Ver qué cambió
git diff
```

### 5. Antes de hacer commit, VERIFICAR submódulos

```bash
# SIEMPRE ejecutar esto ANTES de commit
cd autoppia_iwa_module
git checkout main
git pull origin main
cd ..

# Verificar estado
git submodule status --recursive
```

### 6. Hacer commit y push CORRECTAMENTE

```bash
# Agregar cambios
git add .

# ANTES de commit, verificar que no hay referencias rotas
git submodule status --recursive
# Debes ver algo como:
#  f30a9d49... autoppia_iwa_module (heads/main)
#  1ab1358e... modules/webs_demo (heads/main)

# Si ves todo bien, hacer commit
git commit -m "tu mensaje descriptivo"

# ANTES de push, hacer pull
git pull origin leaderboard

# Si todo está bien, AHORA SÍ push
git push origin leaderboard
```

## 🛠️ Script automático (RECOMENDADO)

Usa este script que hace todo automáticamente:

```bash
#!/bin/bash

echo "🔧 Re-clonando repositorio limpio..."

# Respaldar ubicación actual
BACKUP_DIR=~/backup_autoppia_$(date +%Y%m%d_%H%M%S)
REPO_DIR=~/autoppia_web_agents_subnet

# Respaldar si existe
if [ -d "$REPO_DIR" ]; then
    echo "📦 Creando backup en $BACKUP_DIR..."
    cp -r $REPO_DIR $BACKUP_DIR
    echo "✅ Backup creado"
    
    # Eliminar repo corrupto
    echo "🗑️  Eliminando repo corrupto..."
    rm -rf $REPO_DIR
fi

# Clonar limpio
echo "📥 Clonando repositorio..."
cd ~
git clone https://github.com/autoppia/autoppia_web_agents_subnet.git

# Entrar y configurar
cd autoppia_web_agents_subnet

echo "🔀 Cambiando a rama leaderboard..."
git checkout leaderboard

echo "📦 Inicializando submódulos..."
git submodule update --init --recursive

echo ""
echo "✅ ¡Listo! Repositorio clonado correctamente"
echo ""
echo "📋 Estado:"
git status
echo ""
echo "📦 Submódulos:"
git submodule status --recursive

echo ""
echo "💡 Si tenías cambios, están respaldados en: $BACKUP_DIR"
```

Guarda esto como `reclone.sh` y ejecútalo:
```bash
chmod +x reclone.sh
./reclone.sh
```

## ❗ IMPORTANTE - Para NO volver a romper el repo

Antes de CADA push, ejecuta:

```bash
./scripts/dev/check_before_push.sh
```

(Este script verificará que todo está bien antes de permitirte hacer push)

