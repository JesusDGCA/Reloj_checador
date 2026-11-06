# Arma "Instalar Checador.exe" en Windows: Python portátil + librerías + la app + accesos directos.
# Uso (PowerShell, desde cualquier carpeta):
#   powershell -ExecutionPolicy Bypass -File "build\construir.ps1"
# Necesita: Python 3.12 instalado (solo para descargar librerías) y NSIS (winget install NSIS.NSIS).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$PYVER = "3.12.10"
$app = Resolve-Path "..\checador"

# 1. Python portátil (se descarga una sola vez y se queda en build\pyembed)
if (-not (Test-Path "pyembed\python.exe")) {
    Write-Host "Descargando Python $PYVER portátil..."
    $zip = "python-embed.zip"
    Invoke-WebRequest "https://www.python.org/ftp/python/$PYVER/python-$PYVER-embed-amd64.zip" -OutFile $zip
    Expand-Archive $zip -DestinationPath "pyembed" -Force
    Remove-Item $zip
    # que el Python portátil vea las librerías de Lib\site-packages
    $pth = Get-ChildItem "pyembed\python*._pth" | Select-Object -First 1
    $lineas = (Get-Content $pth.FullName) -replace '^#\s*import site', 'import site'
    Set-Content $pth.FullName (@("Lib\site-packages") + $lineas) -Encoding ascii
}

# 2. Librerías (flask, waitress, pyzk, openpyxl, pillow, fpdf2)
Write-Host "Instalando librerías..."
py -3.12 -m pip install --disable-pip-version-check -q --upgrade --target "pyembed\Lib\site-packages" -r "$app\requirements.txt"
if ($LASTEXITCODE) { throw "No se pudieron instalar las librerías." }

# 3. Carpeta con todo lo que va dentro del instalador
Write-Host "Preparando archivos..."
if (Test-Path staging) { Remove-Item staging -Recurse -Force }
if (Test-Path salida) { Remove-Item salida -Recurse -Force }
New-Item -ItemType Directory staging, salida | Out-Null
Copy-Item pyembed staging\python -Recurse
Copy-Item staging\python\pythonw.exe staging\python\Checador.exe   # proceso con nombre propio (sin ventana negra)
Copy-Item "$app\static\checador.ico" staging\
robocopy $app staging\app /E /XD __pycache__ data .venv /XF *.bat requirements.txt /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "No se pudo copiar la app." }
# precompila para que abra más rápido la primera vez
& staging\python\python.exe -m compileall -q staging\app staging\python\Lib | Out-Null

# 4. Instalador
$nsis = @((Get-Command makensis -ErrorAction SilentlyContinue).Source,
          "${env:ProgramFiles(x86)}\NSIS\makensis.exe", "$env:ProgramFiles\NSIS\makensis.exe") |
        Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $nsis) { throw "No se encontró NSIS. Instálalo con: winget install NSIS.NSIS" }
& $nsis /V2 instalador.nsi
if ($LASTEXITCODE) { throw "NSIS no pudo crear el instalador." }
Get-Item "salida\Instalar Checador.exe" | Format-Table Name, Length, LastWriteTime

# 5. Carpeta para la USB: el instalador (para quien compre) + Checador portátil con datos de demostración
Write-Host "Preparando carpeta para USB..."
$usb = "salida\USB"
$port = "$usb\Checador Portatil"
New-Item -ItemType Directory $port -Force | Out-Null
Copy-Item "salida\Instalar Checador.exe" $usb
Copy-Item staging\python "$port\python" -Recurse
Copy-Item staging\app "$port\app" -Recurse
Copy-Item staging\checador.ico $port
Set-Content "$port\portatil.txt" "Este archivo indica que Checador corre desde la USB: los datos se guardan en la carpeta 'datos'." -Encoding utf8
Set-Content "$port\Abrir Checador.bat" "@echo off`r`nstart `"`" `"%~dp0python\Checador.exe`" `"%~dp0app\Checador.pyw`"" -Encoding ascii
& staging\python\python.exe crear_demo.py "$port\datos"
if ($LASTEXITCODE) { throw "No se pudo crear la base de demostración." }
@"
CHECADOR EN USB
===============

Instalar Checador.exe
    Para el cliente que compra: lo instala en su computadora (no pide permisos de administrador).

Checador Portatil\Abrir Checador.bat
    Para hacer demostraciones SIN instalar nada: corre desde la USB y guarda los datos en la USB.
    Entrar con  usuario: demo   contraseña: demo123
    Trae una empresa y empleados ficticios. El reloj está en modo de práctica ("simulado"),
    así que las checadas nuevas llegan solas cada minuto.
    Para usar un reloj real: Reloj checador > Conexión > escribe la IP del reloj.

    Para sacar la USB: cierra la ventana de Checador (o usa "Cerrar programa (USB)" en el menú)
    y espera 2 segundos.
"@ | Set-Content "$usb\LEEME.txt" -Encoding utf8
Write-Host "Listo. Copia el contenido de build\salida\USB a tu memoria USB."
