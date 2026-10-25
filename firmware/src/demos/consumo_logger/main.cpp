/*
 * consumo_logger — registrador de consumo de NEO (corre en un D1 Mini / ESP8266 aparte)
 *
 * Lee un INA219 (shunt de 0,1 Ω) por I2C a ~1 kHz y, a la vez, la salida serie de
 * NEO. Las dos cosas se marcan con el mismo reloj (micros64, µs) y se envían por el
 * USB del D1 Mini a la PC (tools/consumo.py):
 *
 *   I,<us>,<n>,<i_media_0.1mA>,<i_max_0.1mA>,<v_mV>   cada 10 ms (n = muestras)
 *   N,<us>,<línea de NEO>                              cada línea que imprime NEO
 *
 * Conexiones: INA219 SDA→D2 (GPIO4), SCL→D1 (GPIO5), VCC→3V3, GND→GND común.
 *             TX de NEO (GPIO43) → D5 del D1 Mini (GPIO14). GND común.
 *
 * Por qué SoftwareSerial en D5: el ESP8266 solo tiene un UART que recibe (UART0, el
 * del USB; UART1 solo transmite), y en el D1 Mini el CH340 mantiene en alto su pin
 * RX: la señal de NEO no llegaba (probado el 24/10). SoftwareSerial recibe por
 * interrupciones en cualquier pin; aquí solo recibe, a 115200 baudios.
 *
 * Por qué se lee el registro de shunt y no el de corriente: con R = 0,1 Ω y un LSB
 * de 10 µV, el valor crudo ya es la corriente en unidades de 0,1 mA, sin calibrar.
 */

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <SoftwareSerial.h>
#include <Wire.h>

static const uint8_t  INA_ADDR   = 0x40;
static const int      PIN_SDA    = 4;        // D2
static const int      PIN_SCL    = 5;        // D1
static const int      PIN_NEO_RX = 14;       // D5 ← TX de NEO
static const uint32_t BAUD_NEO   = 115200;   // monitor_speed de NEO
static const uint32_t BAUD_PC    = 921600;   // el USB del D1 Mini ya no comparte UART con NEO

static SoftwareSerial neo;

// Configuración (registro 0x00): bus 16 V, PGA ÷4 (±160 mV = ±1,6 A con 0,1 Ω),
// ADC de bus y shunt a 12 bit sin promediar (532 µs cada uno), modo continuo shunt+bus.
static const uint16_t INA_CONFIG = 0x119F;
static const uint64_t PERIODO_US = 1000;    // una lectura por ms
static const uint64_t VENTANA_US = 10000;   // una línea I cada 10 ms

static bool leerReg(uint8_t reg, uint16_t& valor) {
    Wire.beginTransmission(INA_ADDR);
    Wire.write(reg);
    if (Wire.endTransmission(false) != 0) return false;
    if (Wire.requestFrom(INA_ADDR, (uint8_t)2) != 2) return false;
    valor = ((uint16_t)Wire.read() << 8) | Wire.read();
    return true;
}

static bool escribirReg(uint8_t reg, uint16_t valor) {
    Wire.beginTransmission(INA_ADDR);
    Wire.write(reg);
    Wire.write(valor >> 8);
    Wire.write(valor & 0xFF);
    return Wire.endTransmission() == 0;
}

// Acumuladores de la ventana actual
static uint64_t v_ini_us = 0;
static int32_t  v_n = 0, v_errores = 0;
static int64_t  v_suma_i = 0, v_suma_v = 0;
static int16_t  v_max_i = INT16_MIN;

// Línea de NEO en construcción. Se fecha con el instante de su '\n', no del primer
// carácter: mientras suena el altavoz, el ruido del amplificador mete basura en el cable
// y se acumula al principio de la línea siguiente (visto el 24/10: la marca de fin de
// reproducción quedaba fechada 3 s antes). El '\n' siempre es de NEO; retraso fijo ~3 ms.
static char     neo_buf[256];
static size_t   neo_len = 0;

void setup() {
    WiFi.mode(WIFI_OFF);          // sin radio: menos ruido y menos interrupciones
    WiFi.forceSleepBegin();
    Serial.begin(BAUD_PC);
    // Búfer de bytes de 4 KB (el arranque de NEO suelta ~4 KB seguidos; con 2 KB se
    // desbordaba) y de 2048 flancos (4 B cada uno, ~30 ms en el peor caso): el loop los
    // vacía cada pocos cientos de µs. Con 4096 × 10 flancos (160 KB) no cabía en la RAM.
    neo.begin(BAUD_NEO, SWSERIAL_8N1, PIN_NEO_RX, -1, false, 4096, 2048);
    Wire.begin(PIN_SDA, PIN_SCL);
    Wire.setClock(400000);
    delay(300);
    // Error explícito y reintento: sin INA219 no hay nada que medir
    while (!escribirReg(0x00, INA_CONFIG)) {
        Serial.println("ERROR,INA219 no responde en 0x40 (revisa SDA/SCL/VCC/GND)");
        delay(1000);
    }
    Serial.printf("INFO,consumo_logger listo, config=0x%04X, %u us/muestra\n",
                  INA_CONFIG, (unsigned)PERIODO_US);
    v_ini_us = micros64();
}

void loop() {
    static uint64_t proxima_us = 0;
    uint64_t ahora = micros64();

    // ── Muestra del INA219 cada PERIODO_US ──────────────────────────────────────
    if (ahora >= proxima_us) {
        proxima_us = ahora + PERIODO_US;
        uint16_t shunt, bus;
        if (leerReg(0x01, shunt) && leerReg(0x02, bus)) {
            int16_t i = (int16_t)shunt;               // 0,1 mA por unidad
            v_suma_i += i;
            v_suma_v += (int32_t)(bus >> 3) * 4;      // mV (bits 15..3, 4 mV/LSB)
            if (i > v_max_i) v_max_i = i;
            v_n++;
        } else {
            v_errores++;
        }
    }

    // ── Cierre de ventana ───────────────────────────────────────────────────────
    if (ahora - v_ini_us >= VENTANA_US) {
        if (v_n > 0) {
            Serial.printf("I,%llu,%ld,%ld,%d,%ld\n", (unsigned long long)v_ini_us, (long)v_n,
                          (long)(v_suma_i / v_n), v_max_i, (long)(v_suma_v / v_n));
        }
        if (v_errores) {
            Serial.printf("ERROR,%ld lecturas I2C fallidas en la ventana\n", (long)v_errores);
        }
        v_ini_us = ahora;
        v_n = v_errores = 0;
        v_suma_i = v_suma_v = 0;
        v_max_i = INT16_MIN;
    }

    // ── Reenvío de la salida serie de NEO ───────────────────────────────────────
    if (neo.overflow()) {
        Serial.println("ERROR,desbordado el buffer de la línea de NEO: se perdieron bytes");
    }
    while (neo.available()) {
        char c = (char)neo.read();
        if (c == '\n' || neo_len == sizeof(neo_buf) - 1) {
            neo_buf[neo_len] = '\0';
            if (neo_len) Serial.printf("N,%llu,%s\n", (unsigned long long)micros64(), neo_buf);
            neo_len = 0;
        } else if ((uint8_t)c >= 0x20 || c == '\t') {
            neo_buf[neo_len++] = c;   // los caracteres de control son ruido; ≥0x80 = tildes UTF-8
        }
    }
    yield();   // ESP8266: dejar correr las tareas del sistema (watchdog)
}
