#!/usr/bin/env python3
"""
apply_inherited_edits.py — Aplica a las hojas heredadas de Nabu Casa los únicos cambios que
exige NEO v2 (fase 2, §4.1 y §6). Se ejecuta una sola vez sobre la copia recién importada;
el diff de git de las hojas heredadas debe contener solo esto:

  Power.kicad_sch            elimina U13 (SGM2594B) y su red EN/FAULT: R64, C79, R65, TP5.
                             El TPS2121 de la hoja nueva une VBUS con +5V.
  LED & Connector.kicad_sch  elimina el puerto Grove (J4, U20, Q5, Q7, pasivos, C32 y TP34);
                             J3.2/J3.3 pasan a ESP_IO2 / CHG_PG con R83/R84 sin montar;
                             R91/R135 (GPIO48/42 a J6) sin montar.
  ESP32S3.kicad_sch          GPIO1: GROVE_SDA -> CHG_PG; GPIO2: GROVE_SCL -> ESP_IO2;
                             GPIO46: GROVE_PWR -> ESP_IO46 (solo a un punto de prueba).
Después, clean_dangling.py retira los hilos y símbolos de alimentación que quedan sueltos.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from kisch_edit import Sheet  # noqa: E402

GROVE = ["J4", "U20", "Q5", "Q7", "R40", "R67", "R117", "R118", "R137", "R140", "R141", "R144",
         "R145", "FB11", "C84", "C85", "C98", "C99", "C100", "C118", "D15", "D17", "D21",
         "C32", "TP34", "#PWR0295", "#PWR0297", "#PWR0306"]


def main(kdir):
    p = Sheet(os.path.join(kdir, "Power.kicad_sch"))
    print("Power, eliminados:", sorted(p.delete_symbols(["U13", "R64", "C79", "R65", "TP5"])))
    p.save()

    led = Sheet(os.path.join(kdir, "LED & Connector.kicad_sch"))
    print("LED & Connector, eliminados:", sorted(led.delete_symbols(GROVE)))
    # etiquetas del bloque Grove (x < 200 mm); las de J3 (x ≈ 287 mm) se renombran
    grove_labels = [u for k, name, x, y, u in led.labels(("global_label",))
                    if name in ("GROVE_SDA", "GROVE_SCL", "GROVE_PWR") and x < 200]
    print("LED & Connector, etiquetas Grove eliminadas:", led.delete_uuids(grove_labels))
    print("LED & Connector, etiquetas J3 renombradas:",
          led.rename_global_labels({"GROVE_SCL": "ESP_IO2", "GROVE_SDA": "CHG_PG"}, where=lambda x, y: x > 200))
    print("LED & Connector, DNP:", sorted(led.set_dnp(["R83", "R84", "R91", "R135"])))
    led.save()

    esp = Sheet(os.path.join(kdir, "ESP32S3.kicad_sch"))
    print("ESP32S3, etiquetas renombradas:",
          esp.rename_global_labels({"GROVE_SDA": "CHG_PG", "GROVE_SCL": "ESP_IO2", "GROVE_PWR": "ESP_IO46"}))
    esp.save()


if __name__ == "__main__":
    main(sys.argv[1])
