// Configuración local de NEO. Copia este archivo como src/config_local.h (no se
// versiona) y pon tus valores; main.cpp lo incluye si existe.
//
// El WiFi no va aquí: si NEO no tiene red guardada, abre el punto de acceso
// "NEO-Config"; conéctate a él y abre http://192.168.4.1 para darle la red.
#pragma once

// IP de la PC donde corre el servidor (python -m src.server.ws_server), en la misma red.
#define NEO_SERVIDOR_HOST "192.168.1.100"

// Respaldo en la nube (Hugging Face Spaces, ver servidor/README.md). Vacío = sin nube.
#define NEO_SERVIDOR_HOST_NUBE ""
