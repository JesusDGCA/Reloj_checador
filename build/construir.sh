#!/bin/bash
# Arma "Instalar Checador.exe": Python portátil de Windows + la app + accesos directos.
set -e
cd "$(dirname "$0")"
rm -rf staging salida && mkdir -p staging/app salida
cp -r pyembed staging/python
cp staging/python/pythonw.exe staging/python/Checador.exe   # proceso con nombre propio (sin ventana negra)
cp ../checador/static/checador.ico staging/
(cd ../checador && tar --exclude=__pycache__ --exclude=data --exclude=.venv \
   --exclude='*.bat' --exclude=requirements.txt -cf - .) | (cd staging/app && tar -xf -)
# precompila para que abra más rápido la primera vez
WINEDEBUG=-all wine staging/python/python.exe -m compileall -q staging/app staging/python/Lib >/dev/null 2>&1 || true
makensis -V2 instalador.nsi
ls -la salida
