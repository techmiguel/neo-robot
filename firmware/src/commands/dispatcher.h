#pragma once
/*
 * dispatcher.h — Router de comandos reconocidos (Fase 4)
 * Recibe un ID de comando y ejecuta la acción correspondiente:
 * comandos directos al servidor via JSON, locales, o inicio de grabación para híbridos.
 */

#include <Arduino.h>
#include <functional>
#include "../display/oled.h"

enum class Comando {
    DESCONOCIDO,
    HOLA_NEO,
    CLIMA,
    NOTICIAS,
    ELTOQUE,
    CRIPTO,
    TEMPORIZADOR,
    BUSCAR,
    TRADUCIR,
    RECORDATORIO,
    CALCULAR,
    TRIVIA,
    DADO,
};

class Dispatcher {
public:
    // oled          — para mostrar estado durante el comando
    // cbEnviarTexto — encola un JSON en la cola FreeRTOS hacia tareaWs
    // cbGrabar      — inicia grabarYEnviar() para comandos híbridos
    Dispatcher(Oled* oled,
               std::function<void(const char*)> cbEnviarTexto,
               std::function<void()> cbGrabar);

    // Ejecuta la acción correspondiente al comando reconocido.
    void despachar(Comando cmd);

private:
    Oled*                            _oled;
    std::function<void(const char*)> _cbEnviarTexto;
    std::function<void()>            _cbGrabar;

    // Helper para comandos híbridos: muestra label en OLED y arranca grabación.
    void _grabar(const char* label);
};
