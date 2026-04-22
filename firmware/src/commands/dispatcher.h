#pragma once
/*
 * dispatcher.h — Router de comandos reconocidos (Fase 4)
 * Recibe un ID de comando y decide si ejecutarlo localmente o enviarlo al servidor.
 */

#include <Arduino.h>

enum class Comando {
    DESCONOCIDO,
    CLIMA,
    CRIPTO,
    NOTICIAS,
    TEMPORIZADOR,
    TASA_CAMBIO,
};

class Dispatcher {
public:
    // Ejecuta la acción correspondiente al comando reconocido.
    void despachar(Comando cmd);
};
