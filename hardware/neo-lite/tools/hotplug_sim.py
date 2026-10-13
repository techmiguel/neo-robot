#!/usr/bin/env python3
"""
hotplug_sim.py — Pico de tensión en +5V al enchufar el USB en caliente (fase 6).

  python3 hotplug_sim.py

Modelo: escalón de 5,25 V (máximo de VBUS) a través de la inductancia y la resistencia del cable,
los contactos y el PPTC (L, R) sobre los condensadores de +5V. Los cerámicos (C2, C9 y C10;
capacidad efectiva Ceff tras la reducción por tensión continua, ESR ~5 mΩ) forman con el cable
un LC poco amortiguado. Un condensador con ESR moderada en paralelo (C1, tántalo) lo amortigua
(Linear Technology AN-88; TI SLVA936). Integración explícita con paso de 2 ns durante 40 µs.

Referencia: TLV1117LV y MAX98357A admiten 6 V como máximo absoluto en la entrada.
"""
import itertools
import sys

VBUS = 5.25
LIMIT = 6.0


def peak(L, R, C, Cd=0.0, Rd=1.0, V=VBUS, dt=2e-9, T=40e-6, esr=0.005):
    i = vc = vd = vmax = 0.0
    for _ in range(int(T / dt)):
        if Cd:
            v = (i + vc / esr + vd / Rd) / (1 / esr + 1 / Rd)
            vd += (v - vd) / Rd / Cd * dt
        else:
            v = i * esr + vc
        vc += (v - vc) / esr / C * dt
        i += (V - R * i - v) / L * dt
        vmax = max(vmax, v)
    return vmax


OPTIONS = [("sin C1", 0.0, 1.0), ("47 µF / 1 Ω (TAJ, caja B)", 47e-6, 1.0),
           ("47 µF / 0,5 Ω (TAJ, caja C)", 47e-6, 0.5), ("47 µF / 0,35 Ω (TPS, caja C)", 47e-6, 0.35)]


def main():
    print("| L (µH) | R (Ω) | Ceff (µF) | " + " | ".join(o[0] for o in OPTIONS) + " |")
    print("|---" * (3 + len(OPTIONS)) + "|")
    worst = {o[0]: 0.0 for o in OPTIONS}
    for L, R, C in itertools.product((0.5e-6, 1e-6, 2e-6), (0.1, 0.15, 0.25), (15e-6, 30e-6)):
        vals = [peak(L, R, C, cd, rd) for _, cd, rd in OPTIONS]
        for (name, _, _), v in zip(OPTIONS, vals):
            worst[name] = max(worst[name], v)
        print(f"| {L * 1e6:.1f} | {R:.2f} | {C * 1e6:.0f} | " + " | ".join(
            f"**{v:.2f}**" if v > LIMIT else f"{v:.2f}" for v in vals) + " |")
    print()
    for name, v in worst.items():
        print(f"peor caso {name}: {v:.2f} V {'> 6 V' if v > LIMIT else '<= 6 V'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
