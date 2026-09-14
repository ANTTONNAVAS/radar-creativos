"""
RADAR DE CREATIVOS — SaaS simple para los alumnos.

Una sola página: el alumno pega su token de Meta, ve qué creativos están
ganando y qué tiene que producir ahora. Nada más.

Decisión de diseño (importante): NO hay cuentas de usuario ni contraseñas.
El token vive en el navegador del alumno (localStorage) y se manda en cada
consulta; por defecto el servidor no guarda nada de nadie.

La única excepción es quien ACTIVA el agente 24/7: para poder revisar su
cuenta de madrugada hay que guardar su token, y se guarda cifrado (store.py).
Es opcional y reversible — al desactivarlo, el token se borra.
"""
import os

from flask import Flask, render_template, request

import meta_api
import radar
import store

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.post("/api/radar")
def api_radar():
    """Consulta los anuncios del alumno y devuelve el veredicto del loop.
    El token viaja en la petición y se usa solo para esta llamada."""
    d = request.get_json(silent=True) or {}
    token = (d.get("token") or "").strip()
    cuenta = (d.get("cuenta") or "").strip().replace("act_", "")
    rango = d.get("rango") or "last_7d"
    if not token or not cuenta:
        return {"ok": False, "error": "Falta el token o el ID de la cuenta."}, 200
    try:
        filas = meta_api.get_insights(token, cuenta, "ad", rango)
    except meta_api.MetaError as e:
        return {"ok": False, "error": str(e)}, 200
    except Exception:
        return {"ok": False, "error": "No se pudo conectar con Meta. "
                                      "Revisa el token y vuelve a intentarlo."}, 200
    if not filas:
        return {"ok": False, "error": "Meta no ha devuelto anuncios en ese periodo. "
                                      "Prueba a ampliar el rango de fechas."}, 200

    out = radar.analiza(filas)

    # Campañas: la vista de negocio (dónde va el dinero y qué devuelve).
    try:
        camps = meta_api.get_insights(token, cuenta, "campaign", rango)
    except Exception:
        camps = []
    out["campanas"] = sorted([{
        "nombre": c.get("name", ""), "estado": c.get("status", ""),
        "spend": round(c.get("spend", 0.0), 2),
        "impressions": int(c.get("impressions", 0)),
        "cpm": round(c.get("cpm", 0.0), 2), "ctr": round(c.get("ctr_unique", 0.0), 2),
        "lpv": int(c.get("lpv", 0)), "atc": int(c.get("add_to_cart", 0)),
        "purchases": int(c.get("purchases", 0)),
        "cpa": round(c.get("cpa", 0.0), 2), "revenue": round(c.get("revenue", 0.0), 2),
        "roas": round(c.get("roas", 0.0), 2),
    } for c in camps], key=lambda x: -x["spend"])

    # Formatos: qué CONCEPTO funciona mejor, no qué anuncio suelto.
    out["formatos"] = [{
        "formato": f["formato"], "n_creativos": f["n_creativos"],
        "spend": round(f["spend"], 2), "purchases": f["purchases"],
        "roas": round(f["roas"], 2), "cpa": round(f["cpa"], 2),
        "hook_rate": round(f["hook_rate"], 1), "score": f["score"],
        "veredicto": f["veredicto"], "veredicto_class": f["veredicto_class"],
        "angulos": f["angulos"], "tipos": f["tipos"],
    } for f in radar.build_formats(filas)]

    out["ok"] = True
    out["rango"] = rango
    return out, 200


@app.post("/api/biblioteca")
def api_biblioteca():
    """🎞️ La biblioteca de creativos: todos, ordenados por temperatura y
    ángulo, cada uno con su tendencia, su salud (fatiga) y su evolución día
    a día — que Meta sirve ya desglosada, sin esperar a acumular histórico."""
    d = request.get_json(silent=True) or {}
    token = (d.get("token") or "").strip()
    cuenta = (d.get("cuenta") or "").strip().replace("act_", "")
    rango = d.get("rango") or "last_7d"
    if not token or not cuenta:
        return {"ok": False, "error": "Falta el token o el ID de la cuenta."}, 200
    try:
        filas = meta_api.get_insights(token, cuenta, "ad", rango)
    except Exception as e:
        return {"ok": False, "error": str(e)}, 200
    if not filas:
        return {"ok": False, "error": "Meta no ha devuelto anuncios en ese periodo."}, 200
    try:
        series = meta_api.serie_diaria_ads(token, cuenta, rango)
    except Exception:
        series = {}          # sin la serie la biblioteca sigue siendo útil
    out = radar.biblioteca(filas, series)
    out["ok"] = True
    return out, 200


@app.post("/api/agente/activar")
def agente_activar():
    """Activa el agente 24/7: a partir de aquí el servidor revisa la cuenta
    cada madrugada. Requiere guardar el token (cifrado) — es el precio de que
    alguien trabaje mientras el alumno duerme, y se le dice claramente."""
    d = request.get_json(silent=True) or {}
    token = (d.get("token") or "").strip()
    cuenta = (d.get("cuenta") or "").strip().replace("act_", "")
    if not token or not cuenta:
        return {"ok": False, "error": "Falta el token o la cuenta."}, 200
    try:                       # comprobamos que el token sirve ANTES de guardarlo
        meta_api.get_insights(token, cuenta, "campaign", "last_7d")
    except Exception as e:
        return {"ok": False, "error": f"Meta ha rechazado el token: {e}"}, 200
    codigo = store.alta_cuenta(d.get("nombre", ""), token, cuenta,
                               d.get("rango") or "last_7d")
    return {"ok": True, "codigo": codigo}, 200


@app.post("/api/agente/desactivar")
def agente_desactivar():
    """Apaga el agente y BORRA el token. Sin preguntas ni rastro."""
    d = request.get_json(silent=True) or {}
    store.baja_cuenta((d.get("codigo") or "").strip())
    return {"ok": True}, 200


@app.get("/api/agente/novedades")
def agente_novedades():
    """Lo que el agente encontró en su última ronda."""
    codigo = (request.args.get("codigo") or "").strip()
    cta = store.get_cuenta(codigo) if codigo else None
    if not cta:
        return {"ok": False, "activo": False}, 200
    nov = store.ultimas_novedades(codigo)
    return {"ok": True, "activo": True, "nombre": cta.get("nombre", ""),
            "ultima_revision": cta.get("ultima_revision", ""),
            "dia": nov["dia"], "items": nov["items"]}, 200


@app.post("/api/briefing")
def api_briefing():
    """El mismo informe, ya escrito para que lo lea una IA.

    Lo piden dos sitios: el botón de la web y la skill del chat de creativos.
    Al vivir aquí, los dos dicen exactamente lo mismo — que es lo que hace que
    el loop se retroalimente sin contradicciones."""
    d = request.get_json(silent=True) or {}
    token = (d.get("token") or "").strip()
    cuenta = (d.get("cuenta") or "").strip().replace("act_", "")
    rango = d.get("rango") or "last_7d"
    if not token or not cuenta:
        return "Falta el token o el ID de la cuenta.", 400, {"Content-Type": "text/plain; charset=utf-8"}
    try:
        filas = meta_api.get_insights(token, cuenta, "ad", rango)
    except Exception as e:
        return f"No se pudo leer Meta: {e}", 200, {"Content-Type": "text/plain; charset=utf-8"}
    if not filas:
        return ("Meta no ha devuelto anuncios en ese periodo.", 200,
                {"Content-Type": "text/plain; charset=utf-8"})
    an = radar.analiza(filas)
    an["rango"] = rango
    texto = radar.texto_para_ia(an)
    # Si tiene el agente 24/7 activado, se cuela lo que encontró esta noche:
    # así el chat sabe también qué CAMBIÓ, no solo cómo están las cosas.
    codigo = (d.get("codigo") or "").strip()
    if codigo:
        nov = store.ultimas_novedades(codigo)
        if nov["items"]:
            lineas = "\n".join("  · " + i["texto"] for i in nov["items"])
            texto += (f"\n\n🌙 LO QUE ENCONTRÓ EL AGENTE EN SU ÚLTIMA RONDA "
                      f"({nov['dia']})\n{lineas}")
    return (texto, 200, {"Content-Type": "text/plain; charset=utf-8"})


# ---------------------------------------------------------------------------
# 🌙 EL AGENTE 24/7 vive DENTRO de este servicio, en segundo plano.
#
# Por qué aquí y no en un cron aparte: en Render los discos NO se comparten
# entre servicios, así que un cron separado no vería las cuentas guardadas.
# Un hilo dentro del propio servicio ve la misma base de datos, cuesta la
# mitad y no hay nada más que configurar.
#
# Cada media hora mira si ya pasó la hora de la ronda y si hoy aún no se ha
# hecho. Si el servicio se reinicia, al volver lo comprueba otra vez: no se
# salta ninguna noche.
# ---------------------------------------------------------------------------
HORA_RONDA = int(os.getenv("HORA_RONDA", "3"))      # madrugada, hora del servidor


def _bucle_agente():
    import time
    from datetime import datetime
    import nocturno
    while True:
        try:
            ahora = datetime.now()
            hoy = ahora.date().isoformat()
            if ahora.hour >= HORA_RONDA and store.get_kv("ultima_ronda") != hoy:
                if store.cuentas():                  # solo si alguien lo activó
                    print(f"[agente] ronda de {hoy}", flush=True)
                    nocturno.main()
                store.set_kv("ultima_ronda", hoy)
        except Exception as e:
            print(f"[agente] fallo en la ronda: {e}", flush=True)
        time.sleep(1800)                              # media hora


def _arranca_agente():
    import threading
    store.init()
    threading.Thread(target=_bucle_agente, daemon=True).start()


_arranca_agente()


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", 5001)))
