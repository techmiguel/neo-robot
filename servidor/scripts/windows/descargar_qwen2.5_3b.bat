@echo off
setlocal
rem Descarga qwen2.5:3b con Ollama en B:\ollama\models.
rem Si se corta internet, reintenta solo y continua donde quedo (ollama pull reanuda).
rem Doble clic para ejecutar. Se puede cerrar y volver a abrir: sigue donde iba.

set "MODELO=qwen2.5:3b"
set "DESTINO=B:\ollama\models"

where ollama >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No encuentro ollama. Instala Ollama o abre una terminal nueva.
  pause
  exit /b 1
)

rem 1. Guardar los modelos en B: (C: tiene poco espacio). Solo la primera vez.
if /i not "%OLLAMA_MODELS%"=="%DESTINO%" (
  echo Configurando OLLAMA_MODELS=%DESTINO% ...
  if not exist "%DESTINO%" mkdir "%DESTINO%"
  rem Copia los modelos que ya tienes en C: (no borra nada de C:)
  if exist "%USERPROFILE%\.ollama\models" robocopy "%USERPROFILE%\.ollama\models" "%DESTINO%" /E /NFL /NDL /NJH /NJS >nul
  setx OLLAMA_MODELS "%DESTINO%" >nul
  set "OLLAMA_MODELS=%DESTINO%"
  echo Reiniciando Ollama para que use %DESTINO% ...
  taskkill /f /im "ollama app.exe" >nul 2>&1
  taskkill /f /im ollama.exe >nul 2>&1
  timeout /t 3 /nobreak >nul
  if exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" (
    start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
  ) else (
    start "Ollama" /min ollama serve
  )
)

rem 2. Esperar a que Ollama responda
echo Esperando a Ollama ...
:esperar
ollama list >nul 2>&1
if errorlevel 1 (
  timeout /t 2 /nobreak >nul
  goto esperar
)

rem 3. Descargar con reintentos
echo.
echo Descargando %MODELO% (1,9 GB). Si se corta, reintenta solo.
:descargar
ollama pull %MODELO%
if errorlevel 1 (
  echo.
  echo Descarga cortada. Reintento en 15 segundos... ^(Ctrl+C para cancelar^)
  timeout /t 15 /nobreak >nul
  goto descargar
)

echo.
echo === Listo. Modelos instalados: ===
ollama list
echo.
echo Prueba rapida:
ollama run %MODELO% "Responde en una frase: cual es el planeta mas grande del sistema solar?"
echo.
pause
