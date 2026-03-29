# ScheNotify

Programe notificaciones con lenguaje natural

## Características

ScheNotify es un plugin de LangBot que permite a los usuarios establecer recordatorios programados a través de la interacción de lenguaje natural con el LLM.

### Características principales

- **Interacción de lenguaje natural**: Comprende las intenciones de programación del usuario a través del LLM
- **Análisis de tiempo inteligente**: Obtiene automáticamente la hora actual y calcula la hora del recordatorio
- **Soporte multiidioma**: Soporta mensajes de recordatorio en chino e inglés
- **Comandos de gestión de programación**: Ver y eliminar recordatorios programados
- **Notificaciones automáticas**: Envía automáticamente mensajes de recordatorio a la hora programada

## Configuración

### Ajuste de idioma

Puede seleccionar el idioma de los mensajes de recordatorio en la configuración del plugin:

- `zh_Hans` (Chino simplificado) - Predeterminado
- `en_US` (Inglés)

## Uso

### 1. Programar a través del LLM

Simplemente dígale al LLM su programación en lenguaje natural:

**Ejemplos:**
```
Recuérdame tener una reunión a las 3 PM mañana
Recuérdame enviar el informe a las 9 AM pasado mañana
Recuérdame almorzar a las 12 PM el próximo lunes
Recuérdame la cena de Navidad el 2024-12-25 18:00
```

El LLM automáticamente:
1. Llamará a `get_current_time_str` para obtener la hora actual
2. Analizará su expresión de tiempo y la convertirá a un formato estándar
3. Llamará a `schedule_notify` para crear el recordatorio

### 2. Ver recordatorios programados

Use el comando para ver todos los recordatorios programados:

```
!sche
```

Ejemplo de salida:
```
[Notify] Recordatorios programados:
#1 2024-12-25 18:00:00: Cena de Navidad
#2 2024-12-26 09:00:00: Enviar informe
```

### 3. Eliminar recordatorio

Use el comando para eliminar un recordatorio específico (usando el número de `!sche`):

```
!dsche i <número>
```

Ejemplo:
```
!dsche i 1   # Eliminar el 1er recordatorio
```

## Componentes

### Herramientas

1. **get_current_time_str** - Obtener hora actual
   - Formato de retorno: `YYYY-MM-DD HH:MM:SS`
   - El LLM debe llamar a esta herramienta antes de configurar recordatorios

2. **schedule_notify** - Programar notificación
   - Parámetros: cadena de tiempo, mensaje de recordatorio
   - Obtiene automáticamente la información de la sesión del parámetro session de la herramienta

### Comandos

1. **sche** (alias: s) - Listar todos los recordatorios programados
2. **dsche** (alias: d) - Eliminar recordatorio especificado

## Detalles técnicos

- Intervalo de comprobación: Cada 60 segundos
- Precisión de tiempo: Nivel de minuto (comprueba cada minuto)
- Información de sesión: Obtenida automáticamente a través del parámetro session de la herramienta
- Persistencia: Actualmente utiliza almacenamiento en memoria (se pierde al reiniciar)

## Ejemplo de conversación

**Usuario:** Recuérdame asistir a una reunión a las 2 PM mañana

**LLM:** Claro, configuraré un recordatorio para ti.

*[El LLM llama a get_current_time_str]*
*[El LLM llama a schedule_notify(time_str="2024-12-26 14:00:00", mensaje="Asistir a la reunión")]*

**LLM:** ¡Hecho! Te recordaré a las 2024-12-26 14:00:00: Asistir a la reunión

*[Al día siguiente a las 2 PM]*

**Bot:** [Notify] Asistir a la reunión

## Notas

- La hora del recordatorio debe ser en el futuro, las horas pasadas serán rechazadas
- Los mensajes de recordatorio se enviarán a la misma sesión donde se configuró el recordatorio
- Los recordatorios no enviados se perderán después de reiniciar el plugin (la persistencia será soportada en versiones futuras)

## Información del desarrollador

- Autor: RockChinQ
- Versión: 0.2.0
- Tipo de plugin: LangBot Plugin v1

## Licencia

Parte del ecosistema de plugins de LangBot.
