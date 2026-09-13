"""
RADAR DE CREATIVOS — SaaS simple para los alumnos.

Una sola página: el alumno pega su token de Meta, ve qué creativos están
ganando y qué tiene que producir ahora. Nada más.

Decisión de diseño (importante): NO hay base de datos ni cuentas de usuario.
El token vive en el navegador del alumno (localStorage) y se manda en cada
consulta. El servidor no guarda nada de nadie: así no hay datos sensibles que
custodiar, ni altas, ni contraseñas, ni mantenimiento por alumno.
"""
import os

from flask import Flask, render_template, request

import meta_api
import radar

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


if __name__ == "__main__":
    app.run(debug=True, port=int(os.getenv("PORT", 5001)))
