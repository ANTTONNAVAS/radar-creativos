# -*- coding: utf-8 -*-
"""
nocturno.py — EL AGENTE 24/7.

Se ejecuta solo cada madrugada (cron de Render). Entra en la cuenta de cada
alumno que lo haya activado, mira qué ha cambiado desde la última revisión y
deja escrito **lo que pasó esta noche**: quién empezó a ganar, qué variante
superó a su madre, qué se quedó sin fuelle y qué creativos son nuevos.

Así, cuando el alumno abre la web por la mañana, el trabajo ya está hecho.

Se lanza con:  python nocturno.py
"""
import sys
import traceback
from datetime import date

import meta_api
import radar
import store


def _novedades(hoy, ayer, analisis):
    """Compara la foto de hoy con la anterior y lo cuenta en cristiano."""
    items = []

    for nombre, c in hoy.items():
        viejo = ayer.get(nombre)

        if not viejo:
            items.append({"tipo": "nuevo", "etiqueta": c["etiqueta"],
                          "texto": f"Creativo nuevo en marcha: {c['etiqueta']}."})
            continue

        # Cambios de veredicto: lo que de verdad importa
        if c["estado"] == "ganador" and viejo["estado"] != "ganador":
            items.append({"tipo": "gano", "etiqueta": c["etiqueta"],
                          "texto": f"🏆 {c['etiqueta']} YA ES GANADOR "
                                   f"(nota {c['score']}, ROAS {c['roas']}). "
                                   "Toca hacerle variantes."})
        elif viejo["estado"] == "ganador" and c["estado"] != "ganador":
            items.append({"tipo": "perdio", "etiqueta": c["etiqueta"],
                          "texto": f"⚠️ {c['etiqueta']} ha dejado de ganar "
                                   f"(nota {viejo['score']} → {c['score']}). Vigílalo."})
        elif c["estado"] == "matar" and viejo["estado"] != "matar":
            items.append({"tipo": "murio", "etiqueta": c["etiqueta"],
                          "texto": f"💀 {c['etiqueta']} se ha quedado sin fuelle: "
                                   f"{c['spend']:.2f}€ sin vender. Apágalo."})

    # ¿Alguna variante ha superado a su madre? Es el aprendizaje del sistema.
    for l in analisis.get("linaje") or []:
        if len(l["generaciones"]) > 1 and l["mejora_pct"] > 10:
            items.append({"tipo": "supera", "etiqueta": l["etiqueta"],
                          "texto": f"📈 En {l['etiqueta']}, la V{l['mejor_v']} SUPERA a la "
                                   f"V{l['madre_v']} (+{l['mejora_pct']}%). "
                                   f"La V{l['mejor_v']} pasa a ser la nueva madre: "
                                   "clona esa a partir de ahora."})
    return items


def revisa(cta):
    """Una cuenta: leer Meta, comparar con ayer, dejar las novedades escritas."""
    hoy_str = date.today().isoformat()
    filas = meta_api.get_insights(cta["token"], cta["cuenta"], "ad",
                                  cta.get("rango") or "last_7d")
    if not filas:
        return 0

    an = radar.analiza(filas)
    creativos = an["ganadores"] + an["promesas"] + an["matar"]
    hoy = {c["ad_name"]: c for c in creativos}
    ayer = store.foto_anterior(cta["codigo"], hoy_str)

    items = _novedades(hoy, ayer, an) if ayer else [{
        "tipo": "nuevo", "etiqueta": "",
        "texto": f"Primera revisión: {len(creativos)} creativos bajo vigilancia. "
                 "A partir de mañana te aviso de cada cambio."}]

    store.guarda_novedades(cta["codigo"], hoy_str, items)
    store.guarda_foto(cta["codigo"], hoy_str, creativos)
    return len(items)


def main():
    store.init()
    ctas = store.cuentas()
    print(f"Agente nocturno: {len(ctas)} cuenta(s) con el agente activado.")
    fallos = 0
    for cta in ctas:
        etiqueta = cta.get("nombre") or cta["codigo"]
        try:
            n = revisa(cta)
            print(f"  ✓ {etiqueta}: {n} novedad(es)")
        except Exception as e:
            fallos += 1
            # Que una cuenta rota (token caducado, permisos) no pare a las demás.
            print(f"  ✗ {etiqueta}: {e}")
            traceback.print_exc(limit=1)
    print("Listo.")
    return 1 if fallos and fallos == len(ctas) else 0


if __name__ == "__main__":
    sys.exit(main())
