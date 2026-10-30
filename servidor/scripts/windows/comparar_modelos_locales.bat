@echo off
setlocal enabledelayedexpansion
rem Descarga varios LLM pequenos y los compara con las preguntas libres del corpus
rem (src.benchmark.prompt): latencia, respuestas de mas de 20 palabras, otro alfabeto.
rem Solo mide el LLM, sin Whisper ni TTS: sirve para descartar modelos antes de
rem pasar los finalistas por el banco completo (src.benchmark.e2e).
rem
rem Uso: doble clic (lista por defecto), o desde cmd con los modelos que quieras:
rem   comparar_modelos_locales.bat lfm3:1.7b-qad-q4_0 qwen3.5:2b-q4_K_M
rem Para medir en condiciones reales, cierra el servidor de NEO y otros programas pesados.

set "MODELOS=%*"
if not defined MODELOS set "MODELOS=gemma4:e2b gemma4:e2b-it-qat lfm3:1.7b-qad-q4_0 qwen3.5:2b-q4_K_M qwen3.5:4b granite4.2:3b bonsai-2:4b"
set "REPETICIONES=2"

rem Ir a servidor\ (este archivo esta en servidor\scripts\windows)
cd /d "%~dp0..\.."
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
set "SALIDA=logs\comparativa_llm"
if not exist "%SALIDA%" mkdir "%SALIDA%"

rem Igual que el perfil local de NEO: Ollama, prompt corto y sin razonamiento
set "LLM_PROVIDER=ollama"
set "NEO_PROMPT=corto"
set "OLLAMA_THINK=false"
rem Respuestas con caracteres fuera de cp1252 no rompen la consola ni el resumen
set "PYTHONUTF8=1"
chcp 65001 >nul

where ollama >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No encuentro ollama. Instala Ollama o abre una terminal nueva.
  pause
  exit /b 1
)
echo Modelos en: %OLLAMA_MODELS%
echo A comparar: %MODELOS%
echo.

set "EVALUACIONES="
for %%M in (%MODELOS%) do (
  set "M=%%M"
  set "NOMBRE=!M::=_!"
  echo ================ !M! ================
  call :descargar !M!
  if errorlevel 1 (
    echo [AVISO] No se pudo descargar !M!. Lo salto.
  ) else (
    %PY% -m src.benchmark.prompt --ollama-model !M! --repeticiones %REPETICIONES% --salida "%SALIDA%\!NOMBRE!.json"
    if errorlevel 1 (
      echo [AVISO] La evaluacion de !M! fallo. Lo salto.
    ) else (
      set "EVALUACIONES=!EVALUACIONES! %SALIDA%\!NOMBRE!.json"
    )
    rem Liberar la RAM antes del siguiente: con 16 GB, dos modelos cargados se pisan
    ollama stop !M! >nul 2>&1
  )
  echo.
)

if not defined EVALUACIONES (
  echo [ERROR] Ninguna evaluacion termino.
  pause
  exit /b 1
)
echo ================ Resumen ================
%PY% -m src.benchmark.prompt --comparar %EVALUACIONES% > "%SALIDA%\resumen.md"
type "%SALIDA%\resumen.md"
echo.
echo Tabla en %CD%\%SALIDA%\resumen.md y respuestas completas en los .json.
echo La primera pregunta de cada modelo incluye la carga desde disco: mira la mediana.
pause
exit /b 0

:descargar
set /a INTENTOS=0
:reintentar
ollama pull %1
if not errorlevel 1 exit /b 0
set /a INTENTOS+=1
if !INTENTOS! GEQ 3 exit /b 1
echo Descarga cortada. Reintento en 10 segundos...
timeout /t 10 /nobreak >nul
goto reintentar
