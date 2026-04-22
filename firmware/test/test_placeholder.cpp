/*
 * test_placeholder.cpp
 * Prueba vacía para verificar que el framework de testing de PlatformIO funciona.
 * Reemplazar con tests reales a partir del Módulo 1.1.
 *
 * Para correr: pio test -e esp32dev
 */

#include <unity.h>

void test_siempre_pasa() {
    TEST_ASSERT_EQUAL(1, 1);
}

void setup() {
    UNITY_BEGIN();
    RUN_TEST(test_siempre_pasa);
    UNITY_END();
}

void loop() {}
