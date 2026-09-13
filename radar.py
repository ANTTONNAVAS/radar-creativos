"""
radar.py — El cerebro del loop de creativos.

Lee los anuncios de Meta (ya parseados por formats.py) y decide QUÉ HAY QUE
PRODUCIR. No usa IA: es cálculo puro, así que corre gratis y en el servidor.

Lo que aporta sobre /formatos (que solo mira el presente):
  · LINAJE   — V1 madre → V2/V3 hijas: ¿la variante superó a su madre?
  · HUECOS   — cruces ángulo × formato sin probar, PRIORIZANDO lo que ya gana
               (explorar sobre lo que funciona, no a ciegas)
  · SIGUIENTE VARIANTE — qué V# toca, para que nadie repita número
  · MAL NOMBRADOS — chivato: un anuncio mal nombrado deja ciego al agente

El resultado lo consume el agente diario, que lo vuelca en la memoria de Claude.
"""
from formats import parse_ad_name, build_formats

# Umbrales del veredicto. Son los mismos criterios que ya usa /formatos, pero
# aplicados al creativo individual (no al formato agregado).
GASTO_FIABLE = 15.0     # por debajo de esto no hay dato suficiente para juzgar
GANADOR_SCORE = 70      # 🟢 escalar y clonar
PROMESA_HOOK = 30.0     # engancha, aunque aún no venda
MATAR_GASTO = 25.0      # gastó esto y no vendió nada -> fuera


def familia_de(p):
    """Clave del LINAJE: el creativo sin su número de variante.
    L3_M_HIN_TIMELINE_V2_PROGRESO  ->  L3|M|HIN|TIMELINE|PROGRESO
    Todas las variantes de la misma idea comparten esta clave."""
    return "|".join([p.get("nivel") or "", p.get("embudo") or "",
                     p.get("angulo") or "", p.get("formato") or "",
                     p.get("nombre") or ""])


def _num_version(p):
    """V3 -> 3. Sin versión -> 0 (y eso es un aviso: falta el nº de variante)."""
    v = (p.get("version") or "").upper().lstrip("V")
    return int(v) if v.isdigit() else 0


def _nombre_siguiente(ad_name, n):
    """Nombre de la próxima variante: el del ganador con el V# cambiado.
    L4_T_CAMISA_UGC_VIAJERO_V2 + 3  ->  L4_T_CAMISA_UGC_VIAJERO_V3
    Si el anuncio no llevaba V#, se lo añade al final (y así entra en el loop)."""
    import re as _re
    nuevo, cambios = _re.subn(r"(?i)(?<![A-Z0-9])V\d+(?![A-Z0-9])", f"V{n}", ad_name or "", count=1)
    return nuevo if cambios else f"{ad_name}_V{n}"


def _etiqueta(c):
    """Nombre corto y legible de un creativo, para los informes."""
    partes = [c["formato"]]
    if c["angulo"]:
        partes.append(c["angulo"])
    if c["nivel"]:
        partes.append(c["nivel"])
    if c["version"]:
        partes.append(f"V{c['version']}")
    return " · ".join(partes)


def _clasifica(c):
    """🟢 ganador / 🟡 promesa / 🔴 matar / ⚪ pocos datos."""
    if c["spend"] < GASTO_FIABLE:
        return "pocos"
    if c["score"] >= GANADOR_SCORE:
        return "ganador"
    if c["purchases"] == 0 and c["spend"] >= MATAR_GASTO:
        return "matar"
    if c["hook_rate"] >= PROMESA_HOOK or c["purchases"] > 0:
        return "promesa"
    return "matar"


def analiza(rows):
    """rows = meta_api.get_insights(level='ad'). Devuelve el estado del loop."""
    formatos = build_formats(rows)

    # --- 1) Cada anuncio, descifrado y clasificado ---
    creativos, mal_nombrados, sin_variante = [], [], []
    for r in rows:
        nombre_ad = (r.get("name") or "").strip()
        p = parse_ad_name(nombre_ad)
        if p["formato"] == "(SIN FORMATO)":
            # Sin nomenclatura no se puede analizar: se avisa en vez de callar.
            if r.get("spend", 0) > 0:
                mal_nombrados.append(nombre_ad)
            continue
        c = {
            "ad_name": nombre_ad, "familia": familia_de(p),
            "formato": p["formato"], "angulo": p["angulo"] or "",
            "nivel": p["nivel"] or "", "embudo": p["embudo"] or "",
            "concepto": p["nombre"] or "", "tipo": p["tipo"] or "",
            "version": _num_version(p),
            "spend": round(r.get("spend", 0.0), 2),
            "purchases": int(r.get("purchases", 0)),
            "revenue": round(r.get("revenue", 0.0), 2),
            "roas": round(r.get("roas", 0.0), 2),
            "cpa": round(r.get("cpa", 0.0), 2),
            "hook_rate": round(r.get("hook_rate", 0.0), 1),
            "score": int(r.get("score", 0)) if r.get("score") else 0,
        }
        if not c["score"]:        # /formatos puntúa el formato; aquí, el creativo
            from formats import _score
            c["score"] = _score(c["cpa"], c["roas"], c["hook_rate"], c["purchases"])
        c["estado"] = _clasifica(c)
        c["etiqueta"] = _etiqueta(c)
        # El PORQUÉ: en qué fase del embudo gana y en cuál se rompe.
        c["diag"] = diagnostico(r)
        if c["version"] == 0 and c["spend"] > 0:
            sin_variante.append(nombre_ad)
        creativos.append(c)

    # --- 2) LINAJE: ¿la hija superó a la madre? ---
    fams = {}
    for c in creativos:
        fams.setdefault(c["familia"], []).append(c)
    linaje = []
    for fam, hijos in fams.items():
        hijos.sort(key=lambda x: x["version"])
        medidos = [h for h in hijos if h["spend"] >= GASTO_FIABLE]
        if not medidos:
            continue
        mejor = max(medidos, key=lambda x: x["score"])
        madre = min(medidos, key=lambda x: x["version"])
        mejora = (((mejor["score"] - madre["score"]) / madre["score"] * 100)
                  if madre["score"] else 0.0)
        sig = max(h["version"] for h in hijos) + 1
        linaje.append({
            "familia": fam, "etiqueta": _etiqueta(mejor),
            "generaciones": [{"v": h["version"], "score": h["score"],
                              "roas": h["roas"], "spend": h["spend"]} for h in hijos],
            "mejor_v": mejor["version"], "mejor_score": mejor["score"],
            "madre_v": madre["version"], "madre_score": madre["score"],
            "mejora_pct": round(mejora),
            # El siguiente número libre: así nadie repite variante.
            "siguiente_variante": sig,
            # Y el nombre EXACTO que hay que ponerle, ya montado: se copia y se
            # pega en Meta. Es lo que mantiene vivo el linaje sin pensar.
            "siguiente_nombre": _nombre_siguiente(mejor["ad_name"], sig),
            "ad_name_mejor": mejor["ad_name"],
            "aprendizaje": ("aún sin variantes: esta es la primera generación"
                            if len(medidos) < 2 else
                            "la variante MEJORA a la madre" if mejora > 10 else
                            "la variante NO mejora: seguir clonando la madre"
                            if mejora < -10 else
                            "madre e hija empatan"),
        })
    linaje.sort(key=lambda x: -x["mejor_score"])

    # --- 3) HUECOS: cruzar lo que YA FUNCIONA con lo no probado ---
    # Nunca se explora a ciegas: se parte de lo que gana. Y si todavía no hay
    # ningún ganador (cuenta recién arrancada), se parte de lo que más
    # engancha — que es la mejor pista disponible.
    ganadores = [c for c in creativos if c["estado"] == "ganador"]
    semilla = ganadores or sorted(
        [c for c in creativos if c["estado"] == "promesa"],
        key=lambda x: -x["hook_rate"])[:3]
    probados = {(c["angulo"], c["formato"]) for c in creativos}
    ang_ganadores = sorted({c["angulo"] for c in semilla if c["angulo"]})
    fmt_ganadores = sorted({c["formato"] for c in semilla})
    todos_ang = sorted({c["angulo"] for c in creativos if c["angulo"]})
    todos_fmt = sorted({c["formato"] for c in creativos})
    tira = "está ganando" if ganadores else "es lo que más engancha"
    huecos = []
    for a in ang_ganadores:                     # ángulo que tira × formato nuevo
        for f in todos_fmt:
            if (a, f) not in probados:
                huecos.append({"angulo": a, "formato": f,
                               "razon": f"el ángulo '{a}' {tira}; este formato aún no se ha probado con él"})
    for f in fmt_ganadores:                     # formato que tira × ángulo nuevo
        for a in todos_ang:
            if (a, f) not in probados and not any(h["angulo"] == a and h["formato"] == f for h in huecos):
                huecos.append({"angulo": a, "formato": f,
                               "razon": f"el formato '{f}' {tira}; este ángulo aún no se ha probado en él"})

    gasto_total = round(sum(c["spend"] for c in creativos), 2)
    ventas = sum(c["purchases"] for c in creativos)
    return {
        "gasto_total": gasto_total,
        "ventas": ventas,
        "n_creativos": len(creativos),
        "ganadores": sorted([c for c in creativos if c["estado"] == "ganador"],
                            key=lambda x: -x["score"]),
        "promesas": sorted([c for c in creativos if c["estado"] == "promesa"],
                           key=lambda x: -x["hook_rate"]),
        "matar": sorted([c for c in creativos if c["estado"] == "matar"],
                        key=lambda x: -x["spend"]),
        "linaje": linaje,
        "huecos": huecos[:8],
        "mal_nombrados": mal_nombrados,
        "sin_variante": sin_variante,
        "formatos": [{"formato": f["formato"], "score": f["score"],
                      "veredicto": f["veredicto"], "spend": round(f["spend"], 2),
                      "roas": round(f["roas"], 2), "hook_rate": round(f["hook_rate"], 1),
                      "n_creativos": f["n_creativos"]} for f in formatos],
    }


def snapshot_rows(rows, dia):
    """Filas listas para guardar la foto del día en la base de datos."""
    out = []
    for r in rows:
        p = parse_ad_name(r.get("name") or "")
        if p["formato"] == "(SIN FORMATO)":
            continue
        from formats import _score
        cpa, roas = r.get("cpa", 0.0), r.get("roas", 0.0)
        hook, purch = r.get("hook_rate", 0.0), int(r.get("purchases", 0))
        out.append({
            "dia": dia, "ad_name": (r.get("name") or "").strip(),
            "familia": familia_de(p), "formato": p["formato"],
            "angulo": p["angulo"] or "", "nivel": p["nivel"] or "",
            "embudo": p["embudo"] or "", "version": _num_version(p),
            "spend": r.get("spend", 0.0), "purchases": purch,
            "revenue": r.get("revenue", 0.0),
            "impressions": int(r.get("impressions", 0)),
            "roas": roas, "cpa": cpa, "hook_rate": hook,
            "score": _score(cpa, roas, hook, purch),
        })
    return out


# ---------------------------------------------------------------------------
# EL DIAGNÓSTICO: por qué funciona (o por qué no) un creativo.
#
# No se inventa nada ni hace falta IA: se lee el EMBUDO del anuncio paso a paso
# —gancho, retención, clic, landing, carrito, compra— y se señala dónde gana y
# dónde se rompe. Es lo que mira un buen media buyer, automatizado.
# ---------------------------------------------------------------------------

# Referencias de un creativo sano en COD/ecommerce.
REF = {"hook": 30.0, "reten": 35.0, "ctr": 1.5, "atc": 8.0, "cr": 2.0}


def _pct(a, b):
    return (a / b * 100) if b else 0.0


def diagnostico(r):
    """r = fila cruda de meta_api.get_insights(level='ad').
    Devuelve el porqué: qué parte del creativo gana, cuál se rompe y qué
    replicar en las variantes."""
    imp = r.get("impressions", 0) or 0
    hook = r.get("hook_rate", 0.0)
    v25, v50, v95 = r.get("v25", 0), r.get("v50", 0), r.get("v95", 0)
    ctr = r.get("ctr_unique", 0.0)
    lpv, atc = r.get("lpv", 0), r.get("add_to_cart", 0)
    compras = r.get("purchases", 0)
    atc_pct = r.get("atc_pct", 0.0) or _pct(atc, lpv)
    cr = r.get("cr", 0.0) or _pct(compras, lpv)
    reten = _pct(v50, v25)          # cuántos de los que entraron llegan a la mitad
    remata = _pct(v95, v25)         # cuántos se lo ven entero

    pasos, gana, rompe = [], [], []

    def paso(fase, ok, texto, dato):
        pasos.append({"fase": fase, "ok": ok, "texto": texto, "dato": dato})
        (gana if ok else rompe).append(fase)

    # 1) EL GANCHO — los 3 primeros segundos
    if imp:
        paso("Gancho", hook >= REF["hook"],
             ("El gancho PARA el scroll: la primera frase y el primer plano "
              "están haciendo su trabajo." if hook >= REF["hook"] else
              "El gancho no retiene: la gente pasa de largo en los 3 primeros "
              "segundos. El problema está en la primera frase o en el plano inicial."),
             f"{hook:.0f}% hook (referencia {REF['hook']:.0f}%)")

    # 2) EL CUERPO — ¿mantiene al que enganchó?
    if v25:
        paso("Guion", reten >= REF["reten"],
             ("El guion mantiene: quien entra se queda hasta la mitad, así que "
              "la historia y el ritmo funcionan." if reten >= REF["reten"] else
              "Engancha pero se cae: entran y abandonan antes de la mitad. "
              "Sobra paja o el desarrollo no cumple lo que promete el gancho."),
             f"{reten:.0f}% llega a la mitad · {remata:.0f}% lo ve entero")

    # 3) EL CLIC — ¿la promesa mueve a la acción?
    if imp:
        paso("Promesa", ctr >= REF["ctr"],
             ("La promesa convence: ven el vídeo y hacen clic." if ctr >= REF["ctr"]
              else "Ven el vídeo pero no hacen clic: falta deseo o un cierre "
                   "claro que diga qué tienen que hacer."),
             f"{ctr:.2f}% CTR")

    # 4) LA LANDING — ¿lo que prometió el anuncio se cumple al llegar?
    if lpv:
        paso("Landing", atc_pct >= REF["atc"],
             ("La landing recoge bien lo que promete el anuncio: llegan y "
              "añaden al carrito." if atc_pct >= REF["atc"] else
              "Llegan pero no añaden al carrito: lo que promete el anuncio y lo "
              "que encuentran en la web no cuadran (oferta, precio o producto)."),
             f"{atc_pct:.0f}% añaden al carrito")

    # 5) EL CIERRE — ¿se cierra la venta?
    if atc:
        paso("Cierre", cr >= REF["cr"],
             ("Cierra la venta: el precio y la oferta se sostienen."
              if cr >= REF["cr"] else
              "Añaden al carrito pero no compran: se cae en el cierre — precio, "
              "gastos de envío o falta de confianza."),
             f"{cr:.2f}% compran · {compras} ventas")

    # --- El resumen en una frase, que es lo que se lee de verdad ---
    if not pasos:
        resumen = "Todavía no hay datos suficientes para diagnosticar este creativo."
    elif not rompe:
        resumen = "Funciona de principio a fin: gancho, guion, clic y cierre."
    elif not gana:
        resumen = "No levanta en ninguna fase: mejor cambiarlo entero que retocarlo."
    else:
        resumen = f"Gana en {', '.join(gana).lower()} y se rompe en {', '.join(rompe).lower()}."

    # --- Qué conservar al hacer variantes (lo valioso del creativo) ---
    replicar = []
    if "Gancho" in gana:
        replicar.append("el TIPO de gancho (mismo dolor, mismas primeras palabras)")
    if "Guion" in gana:
        replicar.append("la estructura del guion y su ritmo")
    if "Promesa" in gana:
        replicar.append("la promesa y el cierre del vídeo")
    arreglar = []
    if "Gancho" in rompe:
        arreglar.append("prueba otros 3 primeros segundos: otro dolor u otro plano")
    if "Guion" in rompe:
        arreglar.append("acorta y ve antes al grano")
    if "Promesa" in rompe:
        arreglar.append("cierra con una llamada a la acción clara")
    if "Landing" in rompe:
        arreglar.append("alinea el anuncio con la landing (misma oferta y mismo precio)")
    if "Cierre" in rompe:
        arreglar.append("revisa precio, envío y pruebas sociales")

    return {"resumen": resumen, "pasos": pasos,
            "replicar": replicar, "arreglar": arreglar}


def plan_semanal(d):
    """Cuántos creativos tocan esta semana, repartidos. El objetivo del método
    son 25-30 a la semana: si con lo que hay no se llega, se completa con
    ángulos nuevos."""
    g, p = len(d["ganadores"]), len(d["promesas"])
    hu = min(len(d.get("huecos") or []), 6)
    vg, vp, vt = g * 3, p * 2, hu
    total = vg + vp + vt
    extra = max(0, 25 - total)
    return {"ganadores": g, "promesas": p, "var_ganadores": vg, "var_promesas": vp,
            "tests": vt, "extra": extra, "total": total + extra}


def texto_para_ia(d):
    """El informe en texto plano, escrito PARA que una IA sepa qué producir.

    Es la pieza que cierra el loop: lleva los números, el PORQUÉ de cada
    creativo, qué conservar, qué corregir y con qué nombre exacto va cada
    variante. Lo usan igual el botón de la web y la skill del chat, para que
    los dos digan exactamente lo mismo."""
    P = plan_semanal(d)
    L = {l["familia"]: l for l in (d.get("linaje") or [])}
    out = [f"ESTADO DE MIS CREATIVOS ({d.get('rango','')}) — "
           f"{d['gasto_total']:.2f}€ invertidos · {d['ventas']} ventas · "
           f"{d['n_creativos']} creativos analizados",
           f"\nOBJETIVO DE ESTA SEMANA: {P['total']} creativos "
           f"({P['var_ganadores']} variantes de ganadores + {P['var_promesas']} de promesas + "
           f"{P['tests']} tests nuevos"
           + (f" + {P['extra']} de ángulos nuevos)" if P["extra"] else ")")]

    def bloque(c, n):
        g = c.get("diag") or {}
        l = L.get(c["familia"])
        t = [f"  · {c['etiqueta']} — nota {c['score']}, ROAS {c['roas']}, "
             f"hook {c['hook_rate']}%, {c['spend']:.2f}€, {c['purchases']} ventas",
             f"    POR QUÉ: {g.get('resumen','')}"]
        if g.get("replicar"):
            t.append(f"    CONSERVAR: {'; '.join(g['replicar'])}")
        if g.get("arreglar"):
            t.append(f"    CORREGIR: {'; '.join(g['arreglar'])}")
        t.append(f"    HACER: {n} variantes · nombre de la siguiente: "
                 f"{l['siguiente_nombre'] if l else c['ad_name'] + '_V2'}")
        return "\n".join(t)

    out.append("\n🟢 GANADORES — clonar en variantes")
    out.append("\n".join(bloque(c, 3) for c in d["ganadores"]) if d["ganadores"]
               else "  (ninguno todavía: aún no hay creativos con datos suficientes para escalar)")
    if d["promesas"]:
        out.append("\n🟡 PROMESAS — enganchan pero aún no cierran")
        out.append("\n".join(bloque(c, 2) for c in d["promesas"]))
    if d["matar"]:
        out.append("\n🔴 MATAR — no repetir esta idea")
        out.append("\n".join(f"  · {c['etiqueta']} — {c['spend']:.2f}€ sin ventas. "
                             f"{(c.get('diag') or {}).get('resumen','')}" for c in d["matar"]))
    if d.get("huecos"):
        out.append("\n🧪 SIN PROBAR — explorar SOBRE lo que ya funciona")
        out.append("\n".join(f"  · {h['angulo']} × {h['formato']} — {h['razon']}"
                             for h in d["huecos"][:6]))
    lin = [l for l in (d.get("linaje") or []) if len(l["generaciones"]) > 1]
    if lin:
        out.append("\n📈 LO QUE YA HEMOS APRENDIDO")
        out.append("\n".join(
            f"  · {l['etiqueta']}: "
            + " → ".join(f"V{g['v']}({g['score']})" for g in l["generaciones"])
            + f" — {l['aprendizaje']}" for l in lin))
    avisos = (d.get("mal_nombrados") or []) + (d.get("sin_variante") or [])
    if avisos:
        out.append(f"\n⚠️ AVISO: {len(avisos)} anuncios mal nombrados o sin número de "
                   "variante. No entran en el análisis hasta que se corrijan.")
    out.append(
        "\nINSTRUCCIÓN: prepara los creativos de arriba respetando el POR QUÉ de cada uno "
        "(conserva lo que funciona, corrige lo que se rompe). En las variantes cambia gancho, "
        "avatar y escenario, NUNCA el guion que ya gana. Nombra cada creativo con su número de "
        "variante exacto. Dime primero qué vas a hacer para que lo revise antes de escribirlo.")
    return "\n".join(out)
