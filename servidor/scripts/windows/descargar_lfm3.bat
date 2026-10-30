@echo off
setlocal enabledelayedexpansion
rem Descarga LFM3-1.7B (Liquid AI) con Ollama, en la carpeta de OLLAMA_MODELS.
rem Ejecuta antes mover_modelos_ollama.bat para que se guarde en D:.
rem
rem Por defecto, la variante QAD Q4_0 (1,0 GB): entrenada para recuperar la precision
rem que pierde Q4_0, y Q4_0 es la cuantizacion con kernels mas rapidos en CPU x86.
rem Otra variante: descargar_lfm3.bat lfm3:1.7b-q8_0   (1,8 GB, para comparar calidad)

set "MODELO=%~1"
if not defined MODELO set "MODELO=lfm3:1.7b-qad-q4_0"

where ollama >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No encuentro ollama. Instala Ollama o abre una terminal nueva.
  pause
  exit /b 1
)

rem 1. Avisar si los modelos se van a guardar en C:
set "CARPETA=%OLLAMA_MODELS%"
if not defined CARPETA set "CARPETA=%USERPROFILE%\.ollama\models"
echo Los modelos se guardan en: %CARPETA%
if /i "%CARPETA:~0,2%"=="C:" (
  echo [AVISO] Esa carpeta esta en C:. Ejecuta antes mover_modelos_ollama.bat
  choice /c SN /m "Descargar igualmente en C:"
  if errorlevel 2 exit /b 1
)

rem 2. Esperar a que Ollama responda
echo Esperando a Ollama ...
:esperar
ollama list >nul 2>&1
if errorlevel 1 (
  timeout /t 2 /nobreak >nul
  goto esperar
)
ollama --version

rem 3. Descargar con reintentos (ollama pull reanuda donde quedo)
echo.
echo Descargando %MODELO%. Si se corta, reintenta solo.
set /a INTENTOS=0
:descargar
ollama pull %MODELO%
if errorlevel 1 (
  set /a INTENTOS+=1
  if !INTENTOS! GEQ 5 (
    echo.
    echo [ERROR] La descarga fallo 5 veces. Si el error dice que hace falta una version
    echo mas nueva de Ollama ^("requires a newer version"^), actualizalo desde
    echo https://ollama.com/download y vuelve a ejecutar este archivo.
    pause
    exit /b 1
  )
  echo.
  echo Descarga cortada. Reintento !INTENTOS!/5 en 15 segundos... ^(Ctrl+C para cancelar^)
  timeout /t 15 /nobreak >nul
  goto descargar
)

echo.
echo === Listo. Modelos instalados: ===
ollama list
echo.
echo Prueba rapida ^(sin razonamiento, como lo usa NEO^):
ollama run %MODELO% --think=false "Responde en una frase: cual es el planeta mas grande del sistema solar?"
echo.
echo Para usarlo en NEO, en servidor\.env:
echo   LLM_PROVIDER=ollama
echo   OLLAMA_MODEL=%MODELO%
echo   OLLAMA_THINK=false
echo O para compararlo con gemma4 en el banco de pruebas:
echo   python -m src.benchmark.e2e --variante "lfm3=local,OLLAMA_MODEL=%MODELO%"
echo.
pause
