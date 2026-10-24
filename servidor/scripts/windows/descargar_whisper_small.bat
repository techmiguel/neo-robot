@echo off
setlocal enabledelayedexpansion
rem Descarga faster-whisper "small" (486 MB) en %USERPROFILE%\.cache\neo\whisper-small
rem Si se corta internet, reintenta solo y continua desde el ultimo byte (curl -C -).
rem Doble clic para ejecutar. Se puede cerrar y volver a abrir: sigue donde iba.

set "DESTINO=%USERPROFILE%\.cache\neo\whisper-small"
set "BASE=https://huggingface.co/Systran/faster-whisper-small/resolve/main"
set "TAM_MODELO=483546902"

where curl.exe >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No encuentro curl.exe ^(viene con Windows 10/11^).
  pause
  exit /b 1
)
if not exist "%DESTINO%" mkdir "%DESTINO%"
echo Destino: %DESTINO%
echo.

for %%F in (config.json tokenizer.json vocabulary.txt model.bin) do call :bajar %%F

rem Comprobar el tamano de model.bin
for %%A in ("%DESTINO%\model.bin") do set "TAM=%%~zA"
if not "!TAM!"=="%TAM_MODELO%" (
  echo [ERROR] model.bin mide !TAM! bytes y deberia medir %TAM_MODELO%.
  echo Vuelve a ejecutar este archivo para completarlo.
  pause
  exit /b 1
)

echo.
echo === Listo: model.bin completo ^(%TAM_MODELO% bytes^) ===
echo Para usarlo en el banco de pruebas:
echo   python -m src.benchmark.e2e --perfiles local --whisper-model "%DESTINO%"
echo Para dejarlo fijo, en servidor\.env:
echo   WHISPER_MODEL_SIZE=%DESTINO%
echo.
pause
exit /b 0

:bajar
echo Descargando %1 ...
:reintentar
curl.exe -fL -C - --retry 5 --retry-delay 5 --connect-timeout 20 -o "%DESTINO%\%1" "%BASE%/%1"
if errorlevel 1 (
  echo %1 cortado. Reintento en 10 segundos... ^(Ctrl+C para cancelar^)
  timeout /t 10 /nobreak >nul
  goto reintentar
)
exit /b 0
