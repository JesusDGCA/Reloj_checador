# Reloj Checador

Aplicación web local para administrar la asistencia de empleados con el reloj checador
**Steren CLK-960** y otros relojes compatibles con el protocolo **ZKTeco**.

El reloj sigue funcionando igual (los empleados checan con su huella); este programa lee las
checadas por red y se encarga del resto: expedientes, horarios, retardos, faltas, justificaciones
y reportes en PDF y Excel.

## Funciones

- **Empleados**: alta, baja y expediente con foto, contrato y otros documentos.
- **Asistencia**: cálculo de retardos y faltas, checadas manuales y justificaciones
  (vacaciones, incapacidades y permisos).
- **Horarios**: fijos (entrada y salida) o flexibles (horas por día).
- **Reportes**: por empleado, historial con foto, general, faltas y retardos, y directorio, en PDF o Excel.
- **Días festivos**: los oficiales de la Ley Federal del Trabajo se cargan automáticamente cada año.
- **Reloj checador**: sincronización periódica de checadas, respaldo de huellas y configuración de conexión.
  Incluye un modo de práctica (`simulado`) que no requiere reloj físico.
- **Importación** de empleados, departamentos, checadas y huellas desde el respaldo `.db`
  del software de Steren / ZKTime.Net.
- **Usuarios y bitácora**: acceso con contraseña y registro de quién hizo qué y cuándo.
- **Respaldos**: descarga y restauración de la base de datos completa desde **Ajustes**.

## Tecnologías

Python 3.12, Flask, Waitress, SQLite, pyzk, openpyxl, fpdf2 y Pillow.

## Estructura

```
checador/
  app.py               Servidor web (rutas y vistas)
  db.py                Base de datos SQLite y configuración
  asistencia.py        Cálculo de retardos, faltas y horas
  reloj.py             Comunicación con el reloj (protocolo ZKTeco) y simulador
  reportes.py          Generación de reportes PDF y Excel
  importar_zktime.py   Importación desde el respaldo de Steren / ZKTime.Net
  Checador.pyw         Lanzador de escritorio para Windows
  iniciar.bat          Arranque en modo desarrollo
  iniciar_en_red.bat   Arranque accesible desde otras computadoras de la red
  templates/           Plantillas HTML
  static/              Estilos, íconos y fuentes
  LEEME.md             Guía de uso para el usuario final
build/
  construir.ps1        Genera el instalador de Windows
  instalador.nsi       Script de NSIS para el instalador
  crear_demo.py        Crea una base de datos de demostración
```

## Ejecutar en desarrollo

Requisitos: Windows con Python 3.12 o superior.

```bat
cd checador
iniciar.bat
```

La primera vez crea el entorno virtual `.venv` e instala las dependencias de `requirements.txt`.
Después abre el navegador en `http://localhost:8080`.

Manualmente:

```bash
cd checador
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Opciones de `app.py`:

| Opción | Descripción |
|---|---|
| `--red` | Escucha en `0.0.0.0` para permitir el acceso desde otras computadoras de la red |
| `--sin-navegador` | No abre el navegador al arrancar |
| `--nuevo-usuario` | Crea un usuario desde la consola |

Variables de entorno:

| Variable | Descripción |
|---|---|
| `CHECADOR_DATOS` | Carpeta de datos (por defecto `checador/data`) |
| `CHECADOR_PUERTO` | Puerto del servidor (por defecto `8080`) |
| `CHECADOR_RED` | `1` equivale a `--red` |
| `CHECADOR_SIN_SYNC` | `1` desactiva la sincronización automática con el reloj |

## Generar el instalador

Requisitos: Python 3.12 y [NSIS](https://nsis.sourceforge.io/) (`winget install NSIS.NSIS`).

```powershell
powershell -ExecutionPolicy Bypass -File "build\construir.ps1"
```

El script descarga un Python portátil, instala las dependencias, empaqueta la aplicación y genera
`build\salida\Instalar Checador.exe`. También prepara `build\salida\USB` con una versión portátil
que trae datos de demostración (usuario `demo`, contraseña `demo123`).

La versión instalada guarda sus datos en `%LOCALAPPDATA%\Checador\datos`, por lo que actualizar o
reinstalar no los borra.

## Conexión con el reloj

1. El reloj y la computadora deben estar en la misma red.
2. Consulta la IP del reloj en **Menú > Sistema > Ethernet** y configúrala en
   **Reloj checador > Conexión** (puerto por defecto `4370`).
3. Cierra el software original de Steren: el reloj funciona mejor con un solo programa conectado.

Para probar sin reloj, escribe `simulado` como IP.

## Datos

La carpeta `checador/data/` contiene la base de datos, fotos y documentos de los empleados.
Está excluida del repositorio en `.gitignore` porque contiene información personal.
