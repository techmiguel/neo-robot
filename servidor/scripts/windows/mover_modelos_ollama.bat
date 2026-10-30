@echo off
setlocal enabledelayedexpansion
rem Mueve los modelos de Ollama a D:\ollama\models y deja OLLAMA_MODELS apuntando ahi.
rem Copia primero, comprueba que Ollama los ve desde D: y solo entonces pregunta si
rem borrar la copia antigua. Si algo falla, no se toca la configuracion.
rem
rem Uso: doble clic, o desde cmd:
rem   mover_modelos_ollama.bat                 (origen detectado, destino D:\ollama\models)
rem   mover_modelos_ollama.bat "C:\otra\ruta"  (origen explicito)

set "DESTINO=D:\ollama\models"

where ollama >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No encuentro ollama. Instala Ollama o abre una terminal nueva.
  pause
  exit /b 1
)
if not exist D:\ (
  echo [ERROR] No existe la unidad D:.
  pause
  exit /b 1
)

rem 1. Origen: argumento, o OLLAMA_MODELS del usuario, o la carpeta por defecto
set "ORIGEN=%~1"
if not defined ORIGEN (
  for /f "tokens=2,*" %%A in ('reg query HKCU\Environment /v OLLAMA_MODELS 2^>nul ^| find "OLLAMA_MODELS"') do set "ORIGEN=%%B"
)
if not defined ORIGEN set "ORIGEN=%USERPROFILE%\.ollama\models"

if /i "%ORIGEN%"=="%DESTINO%" (
  echo OLLAMA_MODELS ya apunta a %DESTINO%. Nada que mover.
  pause
  exit /b 0
)
if not exist "%ORIGEN%\manifests" (
  echo [ERROR] "%ORIGEN%" no parece una carpeta de modelos de Ollama ^(falta manifests^).
  echo Pasa la ruta correcta como argumento: mover_modelos_ollama.bat "C:\ruta\models"
  pause
  exit /b 1
)

rem 2. Comprobar espacio libre en D: (en MB)
for /f %%S in ('powershell -NoProfile -Command "[math]::Ceiling((Get-ChildItem -LiteralPath '%ORIGEN%' -Recurse -File | Measure-Object Length -Sum).Sum/1MB)"') do set "NECESARIO=%%S"
for /f %%F in ('powershell -NoProfile -Command "[math]::Floor((Get-PSDrive D).Free/1MB)"') do set "LIBRE=%%F"
echo Origen:  %ORIGEN%  ^(!NECESARIO! MB^)
echo Destino: %DESTINO%  ^(libres en D: !LIBRE! MB^)
if !LIBRE! LSS !NECESARIO! (
  echo [ERROR] No hay espacio suficiente en D:.
  pause
  exit /b 1
)
echo.

rem 3. Parar Ollama (bandeja y servidor) para que no haya ficheros abiertos
echo Parando Ollama ...
taskkill /f /im "ollama app.exe" >nul 2>&1
taskkill /f /im ollama.exe >nul 2>&1
timeout /t 3 /nobreak >nul

rem 4. Copiar. robocopy: codigo >= 8 es error
if not exist "%DESTINO%" mkdir "%DESTINO%"
echo Copiando ^(puede tardar varios minutos^) ...
robocopy "%ORIGEN%" "%DESTINO%" /E /COPY:DAT /R:2 /W:5 /NFL /NDL /NJH /NP
if errorlevel 8 (
  echo [ERROR] robocopy fallo. OLLAMA_MODELS no se ha cambiado; los modelos siguen en %ORIGEN%.
  call :arrancar
  pause
  exit /b 1
)

rem 5. Apuntar Ollama a D: (variable de usuario, persistente) y reiniciarlo
setx OLLAMA_MODELS "%DESTINO%" >nul
set "OLLAMA_MODELS=%DESTINO%"
call :arrancar

echo Esperando a Ollama ...
set /a INTENTOS=0
:esperar
ollama list >nul 2>&1
if errorlevel 1 (
  set /a INTENTOS+=1
  if !INTENTOS! GEQ 30 (
    echo [ERROR] Ollama no responde. Revisa la bandeja del sistema y vuelve a abrirlo.
    pause
    exit /b 1
  )
  timeout /t 2 /nobreak >nul
  goto esperar
)

echo.
echo === Modelos que Ollama ve ahora desde %DESTINO%: ===
ollama list
echo.
echo Si la lista coincide con la de antes, la copia de %ORIGEN% ya sobra.
choice /c SN /m "Borrar la copia antigua en %ORIGEN%"
if errorlevel 2 (
  echo Copia antigua conservada. Puedes borrarla a mano cuando quieras.
) else (
  rmdir /s /q "%ORIGEN%"
  echo Borrada.
)
echo.
echo Hecho. Las terminales abiertas antes de este script no ven OLLAMA_MODELS:
echo abre una nueva antes de lanzar el servidor de NEO.
pause
exit /b 0

:arrancar
echo Arrancando Ollama ...
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" (
  start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
) else (
  start "Ollama" /min ollama serve
)
exit /b 0
