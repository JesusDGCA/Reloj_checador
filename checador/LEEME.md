# Checador

Programa para el reloj checador **Steren CLK-960** (y relojes compatibles con ZKTeco).
El reloj sigue funcionando igual: la gente checa con su huella. Este programa se encarga de lo demás:
expediente con foto y contrato, asistencia, retardos y reporte en Excel.

## Instalar (una sola vez)

1. Doble clic en **Instalar Checador.exe** › Siguiente › Terminar.
   - Si Windows muestra "Windows protegió su equipo": clic en **Más información** › **Ejecutar de todas formas**.
     Pasa con cualquier programa nuevo que no es de una empresa grande.
2. Se abre Checador. En la pantalla de bienvenida carga el respaldo `.db` del programa de Steren.
3. Cierra el programa de Steren y no lo vuelvas a abrir (el reloj funciona mejor con un solo programa conectado).

## Usar

Doble clic en el ícono **Checador** del escritorio. Eso es todo.

El programa también arranca solo, sin abrir ventana, cuando se enciende la computadora,
para ir leyendo las checadas del reloj. Cerrar la ventana no lo apaga.

## Dónde está cada cosa

| Quiero… | Dónde |
|---|---|
| Ver quién ya llegó | **Hoy** |
| Dar de alta a alguien | **Empleados › + Nuevo empleado** y luego registrar su huella en el reloj |
| Subir foto o contrato | Ficha del empleado › foto / **Contrato y documentos** |
| Ver retardos y faltas | **Asistencia** |
| Reportes en PDF o Excel (por empleado, historial con foto, general, faltas y retardos, directorio) | **Reportes** |
| Horarios fijos (entrada/salida) o flexibles (horas por día) | **Horarios** |
| Corregir una checada olvidada | Ficha del empleado › **Asistencia › Agregar checada a mano** |
| Registrar vacaciones, incapacidad o permiso (justificar faltas) | Ficha del empleado › **Asistencia › Vacaciones, incapacidades y permisos**, o el botón **Justificar** junto a cada falta |
| Días festivos | **Ajustes › Días festivos** (los oficiales de la Ley Federal del Trabajo se cargan solos cada año) |
| Ver quién hizo qué y cuándo | **Bitácora** (filtrar por fecha, usuario o texto y descargar en Excel) |
| Dar de baja | Ficha del empleado › **Dar de baja** (el expediente se conserva) |
| Hacer respaldo | **Ajustes › Descargar respaldo completo** (guárdalo en una USB cada semana) |
| Restaurar un respaldo | **Ajustes › Restaurar un respaldo** (pide tu contraseña y antes guarda una copia de lo actual para poder deshacer) |

**Registrar una huella en el reloj:** Menú › Usuarios › Usuarios › elige el número › Editar (OK) ›
Agregar Huella › pon el dedo 3 veces. Después, en Checador: **Reloj checador › Respaldar huellas**.

## Si no conecta con el reloj

- Que el reloj y la computadora estén en la misma red (mismo módem o switch).
- Que la IP sea la del reloj: en el reloj, Menú › Sistema › Ethernet. Se corrige en **Reloj checador › Conexión**.
- Que el programa de Steren esté cerrado.

## Datos

Todo se guarda en `%LOCALAPPDATA%\Checador\datos` (empleados, checadas, fotos y contratos).
Desinstalar o actualizar Checador no borra los datos, a menos que lo confirmes al desinstalar.
