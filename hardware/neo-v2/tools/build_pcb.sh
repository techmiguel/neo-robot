#!/usr/bin/env bash
# build_pcb.sh — Reconstruye kicad/NEO_v2.kicad_pcb desde el PCB original de Nabu Casa (fases 4 a 6).
#
#   1. update_pcb.py       PCB original + netlist -> contorno, huellas, colocación, zonas
#   2. route_power.py      caminos de potencia y lazos críticos trazados a mano
#   3. route_signals.py    router A* propio para las conexiones pendientes (semilla 0)
#   4. stitch_gnd.py       cosido de GND en la franja y unión de bolsas de GND aisladas
#   5. silk_cleanup.py     serigrafía de los bloques nuevos y aviso de licencia (fase 6)
#   6. drc_exclusions.py   exclusiones comentadas de los errores heredados del original
#   7. DRC con paridad de esquemático: debe terminar sin violaciones ni conexiones pendientes
# Después, tools/fab_outputs.py genera el paquete de fabricación en production/.
#
# Todo es determinista. SaveBoard reescribe el .kicad_pro que hay junto al PCB, así que se guarda
# una copia y se restaura antes de escribir las exclusiones.
# Uso: tools/build_pcb.sh   (desde hardware/neo-v2; requiere KiCad 9 con su python3.12 y numpy)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-/usr/bin/python3.12}
W=$(mktemp -d)
git show 0f9b1ce:hardware/neo-v2/kicad/NEO_v2.kicad_pcb > "$W/orig.kicad_pcb"
git show HEAD:hardware/neo-v2/kicad/NEO_v2.kicad_pro > "$W/pro.bak"
python3 - "$W/pro.bak" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
d["board"]["design_settings"]["drc_exclusions"] = []
json.dump(d, open(sys.argv[1], "w"), indent=2)
EOF
cp "$W/pro.bak" "$W/orig.kicad_pro"
cp "$W/pro.bak" kicad/NEO_v2.kicad_pro
kicad-cli sch export netlist --format kicadsexpr -o "$W/neo.net" kicad/NEO_v2.kicad_sch
$PY tools/update_pcb.py "$W/orig.kicad_pcb" "$W/neo.net" kicad/NEO_v2.kicad_pcb
$PY tools/route_power.py kicad/NEO_v2.kicad_pcb kicad/NEO_v2.kicad_pcb
cp "$W/pro.bak" kicad/NEO_v2.kicad_pro
kicad-cli pcb drc --format json -o "$W/drc1.json" kicad/NEO_v2.kicad_pcb || true
$PY tools/route_signals.py kicad/NEO_v2.kicad_pcb "$W/drc1.json" kicad/NEO_v2.kicad_pcb 0
cp "$W/pro.bak" kicad/NEO_v2.kicad_pro
$PY tools/stitch_gnd.py kicad/NEO_v2.kicad_pcb
cp "$W/pro.bak" kicad/NEO_v2.kicad_pro
$PY tools/silk_cleanup.py kicad/NEO_v2.kicad_pcb
kicad-cli pcb drc --format json -o "$W/drc2.json" kicad/NEO_v2.kicad_pcb || true
$PY tools/drc_exclusions.py kicad/NEO_v2.kicad_pcb "$W/drc2.json"
kicad-cli pcb drc --schematic-parity --exit-code-violations -o "$W/drc_final.rpt" kicad/NEO_v2.kicad_pcb
