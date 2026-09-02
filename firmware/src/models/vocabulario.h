// GENERADO por gen_vocabulario.py desde tools/vocabulario.json
// NO editar manualmente — regenerar tras cambiar el vocabulario
#pragma once
#include <stdint.h>

#define VOCAB_N_CLASES 8

static const char* const VOCAB_CLASES[VOCAB_N_CLASES]    = {"hola_neo", "clima", "noticias", "el_toque", "cripto", "dado", "desconocido", "silencio"};
static const char* const VOCAB_FRASES[VOCAB_N_CLASES]    = {"Hola NEO", "Clima", "Noticias", "El Toque", "Cripto", "Dado", "otras palabras o voces", "solo ruido ambiente"};
static const uint16_t    VOCAB_OBJETIVOS[VOCAB_N_CLASES] = {170, 80, 80, 80, 80, 80, 120, 60};
static const bool        VOCAB_ES_COMANDO[VOCAB_N_CLASES] = {true, true, true, true, true, true, false, false};
static const float       VOCAB_UMBRALES[VOCAB_N_CLASES]  = {0.8500f, 0.8500f, 0.8500f, 0.8500f, 0.8500f, 0.8500f, 0.8500f, 0.8500f};
static const int         VOCAB_COMANDO[VOCAB_N_CLASES]   = {1, 2, 3, 4, 5, 12, 0, 0};
