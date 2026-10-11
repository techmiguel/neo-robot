#!/usr/bin/env python3
"""
calc_power_v2.py — Cálculos de la fase 2 de NEO v2 (bloques de alimentación nuevos).

Cada constante lleva la referencia de la hoja de datos de la que sale. Ejecutar:
    python3 calc_power_v2.py
La salida es el anexo de cálculos de docs/fase2-propuesta-bloques-nuevos.md.
"""
import math

E96 = [1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24, 1.27, 1.30, 1.33, 1.37,
       1.40, 1.43, 1.47, 1.50, 1.54, 1.58, 1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91,
       1.96, 2.00, 2.05, 2.10, 2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55, 2.61, 2.67,
       2.74, 2.80, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24, 3.32, 3.40, 3.48, 3.57, 3.65, 3.74,
       3.83, 3.92, 4.02, 4.12, 4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23,
       5.36, 5.49, 5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49, 6.65, 6.81, 6.98, 7.15, 7.32,
       7.50, 7.68, 7.87, 8.06, 8.25, 8.45, 8.66, 8.87, 9.09, 9.31, 9.53, 9.76]


def e96(x):
    dec = 10 ** math.floor(math.log10(x))
    return min((v * dec for v in E96 + [10.0]), key=lambda v: abs(v - x))


def h(t):
    print(f"\n## {t}\n")


# ---------------------------------------------------------------- 1. Cargas en +5V
h("1. Pico de corriente en +5V (altavoz 8 Ω)")
VDD = 5.0
# TPA6211A1 (SLOS367E, 7.6): PO = 1.36 W a 1 % THD+N, RL = 8 Ω, VDD = 5 V
PO_8 = 1.36
RL = 8.0
vpk = math.sqrt(2 * PO_8 * RL)
ipk_amp = vpk / RL
iavg_amp = 2 * ipk_amp / math.pi + 0.004          # + IQ 4 mA (7.5)
print(f"Amplificador: Vpico = {vpk:.2f} V, Ipico = {ipk_amp:.3f} A, "
      f"I media (seno a 1 % THD) = {iavg_amp:.3f} A")
# Disipación máxima BTL (eq. 4 SLOS367E): PDmax = 2·VDD²/(π²·RL)
print(f"Disipación máxima del TPA6211A1: {2*VDD**2/(math.pi**2*RL):.2f} W")
print(f"Ganancia: 40 kΩ / 15 kΩ = {40/15:.2f} V/V ({20*math.log10(40/15):.1f} dB) por entrada")

eta_buck = 0.88   # supuesto conservador para TPS62827 / TPS62065
eta_core = 0.82
loads = {
    # nombre: (corriente pico en su carril, tensión del carril, η hasta 5 V, fuente)
    "ESP32-S3 TX 802.11b 21 dBm": (0.340, 3.3, eta_buck, "ESP32-S3 datasheet, tabla RF: 340 mA pico"),
    "XU316 núcleo (típ.)": (0.300, 0.9, eta_core, "XU316 datasheet §14.6: I(VDD) 300 mA típ."),
    "XU316 E/S, flash, USB, 1V8": (0.040, 3.3, eta_buck, "estimación"),
    "AIC3204 + OLED + resto 3V3": (0.040, 3.3, eta_buck, "estimación"),
    "Micrófonos (LDO desde 5 V)": (0.002, 5.0, 1.0, "estimación"),
    "12 × WS2812B-2020 blanco 100 %": (12 * 0.036, 5.0, 1.0, "WS2812B-2020: 36 mA blanco"),
    "Amplificador (pico)": (ipk_amp, 5.0, 1.0, "cálculo anterior"),
}
total = 0
for k, (i, v, eta, src) in loads.items():
    i5 = i * v / (VDD * eta)
    total += i5
    print(f"- {k}: {i*1000:.0f} mA @ {v} V → {i5*1000:.0f} mA en +5V  [{src}]")
print(f"**Pico simultáneo en +5V: {total:.2f} A** (Grove eliminado)")
I5_PEAK = total
I5_DESIGN = 2.0   # margen de diseño del elevador
print(f"Corriente de diseño del elevador: {I5_DESIGN:.1f} A ({I5_DESIGN/I5_PEAK*100-100:.0f} % de margen)")

# ---------------------------------------------------------------- 2. Elevador TPS61022
h("2. Elevador TPS61022 (SLVSDX7D)")
VREF = 0.600          # 7.5, PWM mode
R2 = 100e3            # < 300 kΩ (8.2.2.1)
# Fase 4: la salida baja a 4,59 V para que el diodo ideal U206 bloquee con USB presente
# (+5V desde USB > BOOST_5V + umbral de bloqueo); ver sección 5.
R1s = 665e3
vout = VREF * (1 + R1s / R2)
print(f"R1 = 665 kΩ (E96), R2 = 100 kΩ → VOUT = {vout:.3f} V "
      f"({0.585*(1+R1s/R2):.2f}–{0.615*(1+R1s/R2):.2f} V con VREF ±2,5 %)")
fsw = 1e6
L = 1.0e-6
Lmin = L * 0.8        # FAUL0630-1R0MT: ±20 %
for vin in (2.7, 3.0, 3.6, 4.2):
    eta = 0.85 if vin < 3.3 else 0.90
    D = 1 - vin * eta / vout                                   # eq. 2
    ildc = vout * I5_DESIGN / (vin * eta)                      # eq. 5
    dil = vin * D / (Lmin * fsw)                               # eq. 6
    ilp = ildc + dil / 2                                       # eq. 7
    ival = ildc - dil / 2
    iout_cl = (1 - D) * (6.5 + dil / 2)                        # eq. 1 con ILIM mín. 6,5 A
    print(f"VIN {vin:.1f} V: D = {D:.3f}, IL(DC) = {ildc:.2f} A, ΔIL = {dil:.2f} A pp, "
          f"IL(pico) = {ilp:.2f} A, valle = {ival:.2f} A (< 6,5 A mín.), "
          f"IOUT máx. por límite = {iout_cl:.2f} A")
cout_min = I5_DESIGN * (1 - 2.7 * 0.85 / vout) / (fsw * 0.05)   # eq. 8, ±50 mV → 50 mV pp
print(f"COUT mínima (eq. 8, 50 mV pp): {cout_min*1e6:.1f} µF efectivos; rango estable 20–1000 µF (7.3)")
print("Elegido: 3 × 22 µF 0805 10 V X5R (~10 µF efectivos c/u a 5 V) + 10 µF entrada")

# ---------------------------------------------------------------- 3. Corriente de batería y protección
h("3. Corriente de batería y protección DW01A + FS8205A")
for vin in (2.7, 3.0, 3.6):
    eta = 0.85 if vin < 3.3 else 0.90
    print(f"VBAT {vin:.1f} V: I batería a {I5_PEAK:.2f} A en +5V = {vout*I5_PEAK/(vin*eta):.2f} A")
IBAT_WORST = vout * I5_PEAK / (2.7 * 0.85)
# DW01A: VEDI 130/150/170 mV; FS8205A (C908265): RDS 18/25 mΩ @4,5 V, 23/32 mΩ @2,5 V
for n_par, rmax, rtyp in ((1, 0.032, 0.021), (2, 0.016, 0.0105)):
    rs_max, rs_typ = 2 * rmax, 2 * rtyp           # dos FET en serie (carga + descarga)
    print(f"{n_par} × FS8205A: disparo sobrecorriente mín. = {0.130/rs_max:.2f} A, "
          f"típ. = {0.150/rs_typ:.2f} A  (I batería peor caso {IBAT_WORST:.2f} A)")
# P-MOSFET de inversión de polaridad CSD25402Q3A: 13,3 mΩ @ −2,5 V, 7,7 mΩ @ −4,5 V
print(f"CSD25402Q3A a {IBAT_WORST:.2f} A, 13,3 mΩ: {IBAT_WORST**2*0.0133*1000:.0f} mW")
print(f"2×FS8205A en serie-paralelo (2 × 10,5 mΩ): {IBAT_WORST**2*0.021*1000:.0f} mW")

# ---------------------------------------------------------------- 4. Cargador BQ25170
h("4. Cargador BQ25170 (SLUSDJ8A)")
KISET = 300.0          # A·Ω típ. (270–330)
ICHG = 0.5
riset = e96(KISET / ICHG)
print(f"RISET = {KISET/ICHG:.0f} Ω → E96 {riset:.0f} Ω; ICHG = {KISET/riset*1000:.0f} mA "
      f"({270/riset*1000:.0f}–{330/riset*1000:.0f} mA); precarga 20 % = {0.2*KISET/riset*1000:.0f} mA; "
      f"terminación 10 % = {0.1*KISET/riset*1000:.0f} mA")
print("RVSET = 27 kΩ → 4,20 V (tabla 8-x)")
for vb in (3.0, 3.6, 4.0):
    print(f"Disipación a VBUS 5,0 V y VBAT {vb} V: {(5.0-vb)*ICHG:.2f} W")
print("RθJA = 75,2 °C/W (JEDEC) → a 1,0 W, ΔT = 75 °C: entra en regulación térmica (125 °C)")
# NTC 10 k B3380 (NCP18XH103F03RB) con ITS = 38 µA
for t, vth, name in ((0, 1.04, "VCOLD"), (45, 0.188, "VHOT")):
    r = 10e3 * math.exp(3380 * (1 / (273.15 + t) - 1 / 298.15))
    print(f"NTC a {t} °C: {r/1e3:.2f} kΩ → VTS = {38e-6*r:.3f} V (umbral {name} = {vth} V)")
cap = 3.0
print(f"Tiempo de carga aprox. de una celda de {cap:.1f} Ah a {ICHG} A: {cap/ICHG*1.15:.1f} h")

# ---------------------------------------------------------------- 5. Unión de fuentes (fase 4)
h("5. Unión de fuentes: TPS2121 de entrada única (SLVSEA3F) + diodo ideal LM66200 (SLVSG04)")
# U201 TPS2121 (abajo): IN1 = VBUS; IN2, PR1, CP2 y OV2 a GND. Tabla 9-3: IN2 <= UV la hace
# inválida, así que la salida la alimenta IN1 ("Invalid Input"); con OV1 >= VREF ninguna es
# válida y la salida queda en alta impedancia (función OFF del interruptor).
ILM = 2.5
rilm = (65.2 / ILM) ** (1 / 0.861) * 1e3                       # eq. 2
print(f"RILM = {rilm/1e3:.1f} kΩ → 44,2 kΩ (tabla: 2,0–3,0 A); IOCP = 2,4 × ILM = {2.4*ILM:.1f} A")
ot, ob = 43.2e3, 10e3
print(f"OV1: {ot/1e3:.1f} k / {ob/1e3:.0f} k → corte por sobretensión en "
      f"{1.06*(ot+ob)/ob:.2f} V (tolerancia {1.01*(ot+ob)/ob:.2f}–{1.10*(ot+ob)/ob:.2f} V)")
for vb in (4.0, 5.0, 5.5):
    vov = vb * (1 / ot + 1 / 10e3) / (1 / ot + 1 / ob + 1 / 10e3)
    print(f"Interruptor en OFF (R215 10 k a VBUS) con VBUS {vb} V: OV1 = {vov:.2f} V (≥ 1,10 V y ≤ 5,5 V)")
RON_MUX = 0.062            # TPS2121 RON máx. a 5 V (tabla 8.5, 85 °C) — conservador
# U206 LM66200 (arriba): VIN1 = BOOST_5V, VOUT = +5V. Bloquea cuando VOUT > VIN1 + VRCB
# (umbral de bloqueo inverso 42–70 mV, tabla 6.5), y conduce sin umbral cuando VIN1 > VOUT.
VRCB_MIN = 0.042
for vbus in (5.25, 5.0, 4.75, 4.5):
    v5 = vbus - I5_PEAK * RON_MUX
    for vb, tag in ((0.585 * (1 + R1s / R2), "mín."), (vout, "típ."), (0.615 * (1 + R1s / R2), "máx.")):
        margin = v5 - (vb + VRCB_MIN)
        if vb == vout:
            print(f"VBUS {vbus:.2f} V, {I5_PEAK:.2f} A: +5V = {v5:.2f} V; elevador {tag} {vb:.2f} V "
                  f"→ margen de bloqueo {margin*1000:+.0f} mV")
    worst = v5 - (0.615 * (1 + R1s / R2) + VRCB_MIN)
    print(f"    peor caso (elevador máx.): {worst*1000:+.0f} mV"
          f"{'  ← reparto de carga USB/batería' if worst < 0 else ''}")
print("Con margen negativo ambos caminos alimentan +5V a la vez: no es peligroso (el cargador sigue"
      " limitado a 0,5 A), pero la batería se descarga en paralelo. Se mide en el prototipo; si ocurre,"
      " subir R210 a 102 k (4,51 V).")
RON_LM = 0.040             # LM66200 RON típ. 40 mΩ a 5 V
print(f"Caída en U206 a {I5_PEAK:.2f} A (batería): {I5_PEAK*RON_LM*1000:.0f} mV; "
      f"+5V con batería ≈ {vout - I5_PEAK*RON_LM:.2f} V")
c5 = 22e-6 * 0.5 * 2 + 40e-6
print(f"Desenchufar USB: U201 deja de conducir y U206 toma la carga sin conmutación activa; el hueco"
      f" es la respuesta del elevador (que ya está en marcha en PWM forzado sin carga).")

# ---------------------------------------------------------------- 6. I2C
h("6. Bus I2C interno con OLED y MAX17048")
c_bus = {"ESP32-S3": 5, "XU316": 5, "AIC3204": 10, "MAX17048 (CB,IN máx.)": 60,
         "pistas ~100 mm": 12, "conector + 10 cm de cable": 10, "módulo OLED": 10}
cb_tot = sum(c_bus.values())
print(f"Capacidad estimada del bus: {cb_tot} pF ({c_bus})")
for name, r in (("4,7 k de placa", 4.7e3), ("4,7 k ‖ 4,7 k nuevas", 2.35e3),
                ("4,7 k ‖ 4,7 k ‖ 4,7 k módulo OLED", 4.7e3 / 3)):
    tr = 0.8473 * r * cb_tot * 1e-12
    isink = (3.3 - 0.4) / r
    print(f"{name}: tr = {tr*1e9:.0f} ns (máx. 300 ns), I sumidero = {isink*1e3:.2f} mA (máx. 3 mA)")

# ---------------------------------------------------------------- 7. Autonomía
h("7. Autonomía estimada con 18650")
p3v3 = 3.3 * (0.120 + 0.030 + 0.005 + 0.012 + 0.010)
pcore = 0.9 * 0.300
p5v_idle = p3v3 / eta_buck + pcore / eta_core + 5 * 0.0015 + 12 * 5 * 0.0006 * 0
pbat_idle = p5v_idle / 0.90
print(f"Reposo escuchando (Wi-Fi conectado, XMOS activo, LED apagados): {p5v_idle:.2f} W en +5V, "
      f"{pbat_idle:.2f} W en batería")
for cap_ah in (2.5, 3.0, 3.5):
    e = cap_ah * 3.6 * 0.90
    print(f"Celda {cap_ah} Ah ({cap_ah*3.6:.1f} Wh, 90 % útil): {e/pbat_idle:.1f} h en reposo; "
          f"{e/(pbat_idle+0.4):.1f} h con 0,4 W medios de audio/LED")
off = 3 + 1 + 0.5 + 0.35 + 0.1
print(f"Consumo con el interruptor en OFF: ~{off:.1f} µA → {3000/(off*1e-3)/24/365:.0f} años (domina la autodescarga)")
