; Instalador de Checador — no pide permisos de administrador
Unicode true
SetCompressor /SOLID lzma
RequestExecutionLevel user

!define NOMBRE "Checador"
!define VERSION "1.3.0"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Checador"

Name "${NOMBRE}"
OutFile "salida\Instalar Checador.exe"
InstallDir "$LOCALAPPDATA\Programs\Checador"
BrandingText "Checador ${VERSION}"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${NOMBRE}"
VIAddVersionKey "FileDescription" "Instalador de Checador"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Checador"

!include "MUI2.nsh"
!define MUI_ICON "staging\checador.ico"
!define MUI_UNICON "staging\checador.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Instalar Checador"
!define MUI_WELCOMEPAGE_TEXT "Este asistente instalará Checador en esta computadora.$\r$\n$\r$\nAl terminar tendrás el ícono de Checador en el escritorio. Solo dale doble clic para abrirlo.$\r$\n$\r$\nPresiona Siguiente para continuar."
!define MUI_FINISHPAGE_TITLE "¡Listo!"
!define MUI_FINISHPAGE_TEXT "Checador quedó instalado.$\r$\n$\r$\nPara abrirlo usa el ícono Checador del escritorio."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Abrir Checador ahora"
!define MUI_FINISHPAGE_RUN_FUNCTION AbrirChecador

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

Function AbrirChecador
  SetOutPath "$INSTDIR\app"
  Exec '"$INSTDIR\python\Checador.exe" "$INSTDIR\app\Checador.pyw"'
FunctionEnd

Section "Checador" SecPrincipal
  ; si había una versión abierta, la cerramos para poder actualizar
  nsExec::Exec 'taskkill /F /IM Checador.exe'
  Sleep 800
  RMDir /r "$INSTDIR\app"

  SetOutPath "$INSTDIR"
  File "staging\checador.ico"
  SetOutPath "$INSTDIR\python"
  File /r "staging\python\*.*"
  SetOutPath "$INSTDIR\app"
  File /r "staging\app\*.*"

  ; accesos directos (escritorio, menú inicio, y arranque con Windows para leer el reloj en segundo plano)
  SetOutPath "$INSTDIR\app"
  CreateShortcut "$DESKTOP\Checador.lnk" "$INSTDIR\python\Checador.exe" '"$INSTDIR\app\Checador.pyw"' "$INSTDIR\checador.ico" 0
  CreateDirectory "$SMPROGRAMS\Checador"
  CreateShortcut "$SMPROGRAMS\Checador\Checador.lnk" "$INSTDIR\python\Checador.exe" '"$INSTDIR\app\Checador.pyw"' "$INSTDIR\checador.ico" 0
  CreateShortcut "$SMPROGRAMS\Checador\Desinstalar Checador.lnk" "$INSTDIR\Desinstalar.exe"
  CreateShortcut "$SMSTARTUP\Checador.lnk" "$INSTDIR\python\Checador.exe" '"$INSTDIR\app\Checador.pyw" --fondo' "$INSTDIR\checador.ico" 0 SW_SHOWMINIMIZED

  WriteUninstaller "$INSTDIR\Desinstalar.exe"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${NOMBRE}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "Checador"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\checador.ico"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "Uninstall"
  nsExec::Exec 'taskkill /F /IM Checador.exe'
  Sleep 800
  Delete "$DESKTOP\Checador.lnk"
  Delete "$SMSTARTUP\Checador.lnk"
  RMDir /r "$SMPROGRAMS\Checador"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${UNINST_KEY}"
  MessageBox MB_YESNO|MB_ICONQUESTION|MB_DEFBUTTON2 "¿Borrar también los datos (empleados, checadas, fotos y contratos)?$\r$\n$\r$\nSi vas a reinstalar, elige No." /SD IDNO IDNO conservar
    RMDir /r "$LOCALAPPDATA\Checador"
  conservar:
SectionEnd
