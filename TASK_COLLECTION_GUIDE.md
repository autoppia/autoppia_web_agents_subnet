# TaskCollection: Guía de Uso

## 📋 Resumen

`TaskCollection` es una estructura simplificada para manejar tareas en el validador.
Reemplaza el uso de tuplas `(project, task)` con el modelo `TaskWithProject` más claro.

## 🆕 Nuevos Modelos

### TaskWithProject

```python
@dataclass
class TaskWithProject:
    """Single task paired with its project."""
    project: WebProject
    task: Task
```

**Uso:**

```python
task_item = TaskWithProject(project=my_project, task=my_task)
print(task_item.project.name)
print(task_item.task.instruction)
```

### TaskCollection

```python
@dataclass
class TaskCollection:
    """Collection of tasks ready for execution."""
    items: List[TaskWithProject]

    def __len__(self) -> int
    def __getitem__(self, key)
    def __iter__(self)
```

**Uso:**

```python
# Crear
collection = TaskCollection(items=[task_item1, task_item2])

# Longitud
total = len(collection)

# Slicing
first_10 = collection[:10]
last_5 = collection[-5:]

# Iteración
for task_item in collection:
    print(task_item.project.name)
```

## 🔄 Función Principal

### get_task_collection_interleaved()

```python
async def get_task_collection_interleaved(
    *,
    prompts_per_use_case: int,
) -> TaskCollection:
    """
    Build a TaskCollection with tasks already interleaved across projects.
    """
```

**Características:**

- ✅ Devuelve lista simple de `TaskWithProject`
- ✅ Tareas **ya intercaladas** (round-robin entre proyectos)
- ✅ Listo para usar con slicing: `[:100]`
- ✅ Sin necesidad de loops anidados

**Ejemplo:**

```python
# Generar tareas
task_collection = await get_task_collection_interleaved(
    prompts_per_use_case=1
)

# Tomar solo las que necesitas
tasks_needed = 100
my_tasks = task_collection.items[:tasks_needed]

# Usar
for task_item in my_tasks:
    project = task_item.project
    task = task_item.task
    # ... hacer algo con project y task
```

## 📝 Migración de Código Existente

### ANTES (con tuplas):

```python
# Generar
task_collection: TaskInterleaver = await get_task_collection(...)

# Extraer (loops anidados)
all_tasks = []
for project_tasks in task_collection.projects_tasks:
    for task in project_tasks.tasks:
        all_tasks.append((project_tasks.project, task))  # Tupla!

# Usar (unpacking tupla)
project, task = all_tasks[i]
```

### DESPUÉS (con TaskWithProject):

```python
# Generar
task_collection: TaskCollection = await get_task_collection_interleaved(...)

# Extraer (directo)
all_tasks = task_collection.items[:100]  # Slicing simple!

# Usar (atributos claros)
task_item = all_tasks[i]
project = task_item.project
task = task_item.task
```

## 🎯 Ventajas

| Aspecto         | Antes                     | Después                     |
| --------------- | ------------------------- | --------------------------- |
| **Tipo**        | `Tuple[WebProject, Task]` | `TaskWithProject`           |
| **Acceso**      | `project, task = tuple`   | `item.project`, `item.task` |
| **Claridad**    | Tupla anónima             | Dataclass con nombres       |
| **Type hints**  | Difícil                   | Claro y explícito           |
| **IDE support** | Limitado                  | Autocompletado completo     |
| **Loops**       | Dobles anidados           | Uno simple                  |
| **Slicing**     | Manual con breaks         | Nativo `[:N]`               |

## 🧪 Testing

```bash
# Probar la nueva función
python scripts/test_task_collection_interleaved.py
```

## 📚 Referencia Rápida

```python
# Imports
from autoppia_web_agents_subnet.validator.models import TaskCollection, TaskWithProject
from autoppia_web_agents_subnet.validator.tasks import get_task_collection_interleaved

# Generar
collection = await get_task_collection_interleaved(prompts_per_use_case=1)

# Operaciones
len(collection)              # Número total de tareas
collection[:100]             # Primeras 100 tareas
collection[-10:]             # Últimas 10 tareas
collection[50:60]            # Tareas 50-59
list(collection)             # Convertir a lista
for item in collection: ...  # Iterar

# Acceso a TaskWithProject
item = collection[0]
item.project                 # WebProject
item.task                    # Task
item.project.name            # Nombre del proyecto
item.task.instruction        # Instrucción de la tarea
```

## 🔄 Backward Compatibility

La función original `get_task_collection()` **sigue existiendo** y devuelve `TaskInterleaver`.
Esto mantiene compatibilidad con código que pueda usarla directamente.

```python
# Todavía funciona:
task_interleaver = await get_task_collection(prompts_per_use_case=1)
```

## ✅ Conclusión

`TaskCollection` simplifica el manejo de tareas en el validador:

- **Más simple**: Lista plana en vez de estructura anidada
- **Más claro**: `TaskWithProject` en vez de tuplas
- **Más pythonic**: Slicing y iteración nativos
- **Más type-safe**: IDE puede ayudarte mejor
