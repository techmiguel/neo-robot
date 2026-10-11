#!/usr/bin/env bash
# build_pcb.sh — Reconstruye kicad/NEO_v2.kicad_pcb desde el PCB original de Nabu Casa (fases 4 y 5).
#
#   1. update_pcb.py       PCB original + netlist -> contorno, huellas, colocación, zonas
#   2. route_power.py      caminos de potencia y lazos críticos trazados a mano
#   3. autoroute.py        exporta las netas pendientes a Freerouting y fusiona el resultado
#   4. stitch_gnd.py       cosido de GND en la franja
#   5. drc_exclusions.py   exclusiones comentadas de los errores heredados del original
#
# Freerouting 2.1.0 (GPL-3, https://github.com/freerouting/freerouting) no se distribuye aquí;
# FREEROUTING debe apuntar al .jar. El autorruteo no es determinista entre versiones de Java o de
# Freerouting: el PCB del repositorio es el resultado validado; este script documenta cómo se hizo.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-/usr/bin/python3.12}
FREEROUTING=${FREEROUTING:?indique la ruta de freerouting-2.1.0.jar}
W=$(mktemp -d)
git show 0f9b1ce:hardware/neo-v2/kicad/NEO_v2.kicad_pcb > "$W/orig.kicad_pcb"
cp kicad/NEO_v2.kicad_pro "$W/orig.kicad_pro"
cp kicad/NEO_v2.kicad_pro "$W/pro.bak"
kicad-cli sch export netlist --format kicadsexpr -o "$W/neo.net" kicad/NEO_v2.kicad_sch
$PY tools/update_pcb.py "$W/orig.kicad_pcb" "$W/neo.net" kicad/NEO_v2.kicad_pcb
$PY tools/route_power.py kicad/NEO_v2.kicad_pcb kicad/NEO_v2.kicad_pcb
kicad-cli pcb drc --format json -o "$W/drc1.json" kicad/NEO_v2.kicad_pcb || true
$PY tools/autoroute.py export kicad/NEO_v2.kicad_pcb "$W/fr" "$W/drc1.json"
java -jar "$FREEROUTING" -de "$W/fr/neo.dsn" -do "$W/fr/neo.ses" -mp 15 -inc completa --gui.enabled=false
$PY tools/autoroute.py merge kicad/NEO_v2.kicad_pcb "$W/fr"
$PY tools/stitch_gnd.py kicad/NEO_v2.kicad_pcb
# SaveBoard reescribe el .kicad_pro: se restaura antes de escribir las exclusiones
cp "$W/pro.bak" kicad/NEO_v2.kicad_pro
kicad-cli pcb drc --format json -o "$W/drc2.json" kicad/NEO_v2.kicad_pcb || true
$PY tools/drc_exclusions.py kicad/NEO_v2.kicad_pcb "$W/drc2.json"
kicad-cli pcb drc --schematic-parity --exit-code-violations kicad/NEO_v2.kicad_pcb
