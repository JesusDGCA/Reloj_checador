"""Lanzador de escritorio de Checador (Windows).

- Doble clic en el ícono: arranca el programa (si no estaba corriendo) y abre su ventana.
- Con --fondo (se usa al iniciar Windows): arranca sin abrir ventana, solo para ir leyendo el reloj.
Los datos se guardan en %LOCALAPPDATA%\\Checador\\datos para que sobrevivan a actualizaciones.

Modo portátil (USB): si junto a la carpeta app hay un archivo "portatil.txt", los datos se guardan en la
carpeta "datos" de la misma USB, usa otro puerto (para no chocar con un Checador instalado), no deja nada
en la computadora y se apaga solo al cerrar su ventana.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

RAIZ = os.path.dirname(AQUI)
PORTATIL = os.path.exists(os.path.join(RAIZ, "portatil.txt"))
if PORTATIL:
    DATOS = os.path.join(RAIZ, "datos")
    os.environ["CHECADOR_DATOS"] = DATOS
    os.environ["CHECADOR_PORTATIL"] = "1"
else:
    DATOS = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Checador", "datos")
os.environ.setdefault("CHECADOR_DATOS", DATOS)
os.makedirs(os.environ["CHECADOR_DATOS"], exist_ok=True)

# pythonw no tiene consola: mandamos los mensajes a un archivo para poder revisar errores
_log = open(os.path.join(os.environ["CHECADOR_DATOS"], "registro.log"), "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = _log

PUERTO = int(os.environ.get("CHECADOR_PUERTO", "8766" if PORTATIL else "8765"))
URL = f"http://127.0.0.1:{PUERTO}/"


def ya_esta_corriendo():
    try:
        with urllib.request.urlopen(URL + "api/ping", timeout=2) as r:
            return json.load(r).get("app") == "checador"
    except Exception:
        return False


def puerto_libre():
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", PUERTO))
            return True
        except OSError:
            return False


def _buscar_navegador():
    """Edge viene en todo Windows 10/11; si no, Chrome. Se abren en modo 'aplicación' (sin barra de direcciones)."""
    rutas = []
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES"), os.environ.get("LOCALAPPDATA")):
        if base:
            rutas.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
            rutas.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    try:
        import winreg
        for exe in ("msedge.exe", "chrome.exe"):
            for raiz in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(raiz, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                        rutas.append(winreg.QueryValue(k, None))
                except OSError:
                    pass
    except ImportError:
        pass
    return next((r for r in rutas if r and os.path.exists(r)), None)


PERFIL_NAV = os.path.join(os.environ.get("TEMP") or RAIZ, "checador_portatil_navegador")


def abrir_ventana():
    """Abre la ventana. En modo portátil regresa el proceso del navegador para saber cuándo se cierra."""
    nav = _buscar_navegador()
    if nav:
        args = [nav, f"--app={URL}", "--window-size=1366,860", "--no-first-run", "--no-default-browser-check"]
        if PORTATIL:  # perfil aparte: no se mezcla con el navegador de la computadora y se borra al final
            args.append(f"--user-data-dir={PERFIL_NAV}")
        try:
            return subprocess.Popen(args, close_fds=True)
        except Exception as e:
            print("No se pudo abrir el navegador en modo app:", e)
    webbrowser.open(URL)
    return None


def _apagar_al_cerrar(proc):
    """Modo portátil: cuando se cierra la ventana, se apaga el programa (así se puede sacar la USB)."""
    proc.wait()
    time.sleep(1)
    import shutil
    shutil.rmtree(PERFIL_NAV, ignore_errors=True)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "Ventana cerrada: Checador portátil se apaga")
    os._exit(0)


def esperar_servidor(segundos=20):
    fin = time.time() + segundos
    while time.time() < fin:
        if ya_esta_corriendo():
            return True
        time.sleep(0.25)
    return False


def main():
    fondo = "--fondo" in sys.argv
    if ya_esta_corriendo():
        if not fondo:
            abrir_ventana()
        return
    if not puerto_libre():
        _aviso(f"El puerto {PUERTO} está ocupado por otro programa. Reinicia la computadora e intenta de nuevo.")
        return

    import app as aplicacion
    import db
    import reloj
    db.iniciar()
    reloj.iniciar_ciclo()
    print(time.strftime("%Y-%m-%d %H:%M:%S"), "Checador iniciado en", URL)

    def servir():
        from waitress import serve
        serve(aplicacion.app, host="127.0.0.1", port=PUERTO, threads=8, _quiet=True)

    hilo = threading.Thread(target=servir, name="servidor")
    hilo.start()
    if not fondo and esperar_servidor():
        proc = abrir_ventana()
        if PORTATIL and proc:
            threading.Thread(target=_apagar_al_cerrar, args=(proc,), daemon=True).start()
    hilo.join()  # el programa sigue vivo leyendo el reloj aunque se cierre la ventana


def _aviso(texto):
    print(texto)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, texto, "Checador", 0x30)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        _aviso(f"Checador no pudo iniciar:\n{e}\n\nDetalles en {os.path.join(os.environ['CHECADOR_DATOS'], 'registro.log')}")
