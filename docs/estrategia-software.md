# Estrategia de software: red bajo demanda, voz única y avisos pregrabados

Con las medidas de la Entrega 1 (reposo de 119 mA a 5 V, inferencia de 2,6 s), NEO pasa a:

1. **Red bajo demanda.** El WiFi y el WebSocket solo están encendidos mientras hay actividad. Tras 10 min en reposo se apagan, la CPU baja a 80 MHz y el wake word sigue escuchando. Al decir «Hola NEO», la red se conecta mientras NEO saluda y graba la pregunta.
2. **Una sola voz.** Manuel (edge-tts, `es-CU-ManuelNeural`) dice el saludo, los avisos y las respuestas. Si edge-tts falla (sin internet, 403, tiempo agotado), el servidor responde con Piper.
3. **Avisos pregrabados con variantes:** sin wifi, sin servidor, sin internet, tardando, no te entendí, error genérico y conectado.
   - **Avisos del estado de la red, sin que nadie pregunte:** en reposo, NEO avisa una sola vez al perder la red («No encuentro la red wifi», «Mi servidor no responde…»), aunque siga reintentando.
   - Al recuperarla dice «Ya estoy conectado y listo», y lo mismo al conectar tras el arranque.
   - La reconexión normal después del reposo profundo no se anuncia.
   - Probado el 24/10: al parar el servidor dijo «Mi servidor no responde…»; al relanzarlo, 30,8 s después, «Ya estoy conectado y listo».
4. **Inferencia con ESP-NN** y un **VAD más robusto**: piso de ruido y 300 ms de pre-roll.

## Conceptos

### Frecuencia de la CPU y consumo

El consumo dinámico de un chip CMOS crece con la frecuencia de reloj: cada flanco carga y descarga millones de transistores. Bajar la CPU de 240 a 80 MHz reduce ese consumo a una fracción, a cambio de que el código tarde unas 3 veces más. Es como bajar las revoluciones de un motor que está al ralentí: mientras NEO solo espera el wake word, la CPU está casi siempre esperando al micrófono.

```cpp
setCpuFrequencyMhz(80);    // reposo: 80 es el mínimo con el que el WiFi puede volver a encenderse
// ... al captar voz para el wake word:
setCpuFrequencyMhz(240);   // inferencia y conversación a toda velocidad
```

Por qué no basta con dormir el chip:
- **Light sleep** detiene los relojes de los periféricos, y el I2S dejaría de recoger muestras del micrófono.
- **Deep sleep** apaga casi todo y al despertar el chip arranca desde cero.

El wake word necesita el micrófono continuamente, así que la única palanca es bajar la frecuencia. Funciona sin perder audio por dos razones:
- El I2S toma su reloj del APLL, un PLL de audio independiente de la CPU.
- El DMA llena los búferes sin intervención de la CPU.

**Error típico:** bajar de 80 MHz. Con el WiFi encendido el chip lo rechaza, y el UART y otros periféricos cambian de reloj.

### Apagar el WiFi de verdad

`WiFi.disconnect()` solo suelta el punto de acceso: la radio sigue encendida buscando redes. `WiFi.mode(WIFI_OFF)` detiene el módem, que es la mayor parte del consumo en reposo. Para volver a encenderlo: `WiFi.mode(WIFI_STA)` + `WiFi.begin(ssid, pass)`, y la conexión tarda 1–3 s.

```cpp
ws->desconectar();       // cerrar el socket antes de tirar la red
WiFi.disconnect(true);   // soltar el AP
WiFi.mode(WIFI_OFF);     // apagar el módem
```

En `main.cpp` lo hace `tareaWs`, la única tarea que toca la red, en `_redApagar()`.

### Tabla de particiones

La flash de 8 MB está dividida como un disco en particiones. El bootloader lee la tabla en 0x8000:

| Partición | Offset | Tamaño | Uso |
|---|---|---|---|
| nvs | 0x9000 | 20 KB | credenciales WiFi (clave/valor) |
| otadata | 0xe000 | 8 KB | qué app arrancar |
| app0 / app1 | 0x10000 / 0x340000 | 3,25 MB cada una | firmware (dos para OTA) |
| spiffs | 0x670000 | 1,5 MB | archivos |

Las frases ocupan ~1,1 MB, y con ellas la app pasa de 1,1 a 2,2 MB: ya no cabe en `min_spiffs.csv` (app de 1,9 MB). En `default_8MB.csv` (arriba), **nvs sigue en 0x9000 con el mismo tamaño**, así que NEO conserva el WiFi configurado.

**Error típico:** flashear solo `firmware.bin` tras cambiar la tabla. Hay que escribir también `partitions.bin` en 0x8000 (el comando de esptool de abajo lo hace).

### Búfer circular para el pre-roll

El VAD declara «hay voz» tras 3 bloques seguidos sobre el umbral (48 ms). Para entonces la primera sílaba ya pasó. La solución es guardar siempre los últimos N bloques en un búfer circular, como el historial de una terminal, que sobrescribe lo más viejo. Al detectar la voz, se ordena el búfer (lo más viejo primero) y la grabación sigue detrás.

```cpp
memcpy(buf + (k % N) * BLOQUE, bloque, sizeof(bloque));   // k = bloques leídos
// al detectar voz, si k > N: el más antiguo está en la posición k % N
std::rotate(buf, buf + (k % N) * BLOQUE, buf + N * BLOQUE);
```

NEO usa N = 19 bloques de 16 ms (~300 ms), dentro del mismo `audio_buf` en PSRAM: no gasta SRAM.

### ESP-NN

TFLite Micro trae kernels «de referencia»: C portable, una multiplicación por vez. El ESP32-S3 tiene instrucciones SIMD que multiplican 16 valores int8 en un ciclo. ESP-NN (de Espressif) reescribe en ensamblador del S3 los kernels más caros (convolución, fully connected, pooling, softmax…), con la misma aritmética int8. El resultado debe ser idéntico o diferir en ±1 por redondeo.

En PlatformIO se activa así:
- Se añade la librería `esp-nn` y el flag `-DESP_NN`.
- Se excluyen los kernels de referencia que `kernels/esp_nn/*.cc` reemplaza. Esto lo hace `scripts/parche_tflite.py`, igual que su CMakeLists.txt.

## Cómo queda el flujo

```
Arranque: WiFi (portal si no hay credenciales o la clave falla) → micro, altavoz, modelo → Listo
          (el WS lo conecta tareaWs en segundo plano; ya no hay bucle bloqueante ni reinicio)

Reposo (red viva hasta 10 min desde la última actividad)
   └─ 10 min sin actividad → [RED] apagada → [CPU] 80 MHz → reposo profundo
«Hola NEO» → [CPU] 240 MHz → saludo (variante al azar) → s_red_reintentar
   ├─ tareaWs: [RED] conectando → WiFi (≤10 s) → WS LAN/nube → [RED] lista <ms>
   └─ loop: graba la pregunta (pre-roll 300 ms) → la encola → espera el envío (≤35 s)
        ├─ enviado → espera la respuesta (≤30 s, si no: «tardando»)
        ├─ sin WiFi → «No puedo conectarme a la wifi»
        └─ sin servidor → «No encuentro mi servidor»
Servidor: {"cmd":"error","codigo":"sin_internet"|"no_entendi"|"interno"} → frase pregrabada
```

## Verificación en la placa

Flasheo (cambia la tabla de particiones), con NEO en modo de descarga:

```bash
cd firmware
pio run -e esp32dev
~/.platformio/penv/Scripts/python.exe ~/.platformio/packages/tool-esptoolpy/esptool.py --chip esp32s3 -p COMx -b 460800 --before default_reset write_flash --flash_size 8MB --flash_mode dio --flash_freq 80m 0x0 .pio/build/esp32dev/bootloader.bin 0x8000 .pio/build/esp32dev/partitions.bin 0xe000 ~/.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin 0x10000 .pio/build/esp32dev/firmware.bin
```

| Prueba | Esperado en el log |
|---|---|
| Arranque normal | `[NEO] Listo` sin esperar al WS; luego `[RED] lista <ms>` |
| «Hola NEO» + pregunta, servidor normal | respuesta con la voz de Manuel |
| Servidor de la PC parado (y nube caída) | `[RED] pedido descartado: sin servidor` + «No encuentro mi servidor» |
| Router apagado | `[RED] pedido descartado: sin WiFi` + «No puedo conectarme a la wifi» |
| Perfil nube sin internet en la PC | «No puedo acceder a internet ahora» |
| Pregunta muda (solo ruido) | «No te entendí, ¿me lo repites?» y vuelve a escuchar |
| Arranque con red | «Ya estoy conectado y listo» (o una variante) tras `[RED] lista` |
| Servidor caído con NEO en reposo | un solo aviso «No encuentro mi servidor» y, al volver, «Ya estoy conectado y listo» |
| 10 min sin hablar | `[RED] apagada`, `[CPU] 80 MHz`; la siguiente interacción mide `[RED] lista <ms>` |
| edge-tts bloqueado en el servidor | aviso `edge-tts falló … respondo con Piper` y respuesta con Piper |
| ESP-NN | `[INF] tareaInf: listo en X ms` (antes, 2600 ms) y las mismas puntuaciones con los mismos clips |

Medidas que se repiten con este firmware:
- `consumo.py`: sesión `reposo_profundo` de 10 min (el estado nuevo `reposo_profundo` sale de `[CPU] 80 MHz`), para compararla con los 119 mA.
- `latencia_wake.py`: 20 intentos, para compararlos con los 3,33 s.
- La prueba de falsos positivos por hora, que sigue pendiente.
