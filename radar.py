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
        # Todos, incluidos los que aún tienen pocos datos: la biblioteca los
        # enseña igual (existen y hay que poder buscarlos), aunque el agente
        # todavía no se moje con ellos.
        "creativos": creativos,
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


# ---------------------------------------------------------------------------
# BIBLIOTECA DE CREATIVOS — organizada por temperatura y ángulo,
# con la evolución de cada uno y aviso de fatiga.
# ---------------------------------------------------------------------------
TEMPERATURA = {"TOFFU": ("frio", "Frío"), "MOFFU": ("templado", "Templado"),
               "BOFFU": ("caliente", "Caliente")}

FREC_FATIGA = 3.5      # a partir de aquí el público empieza a estar quemado
FREC_AVISO = 2.5


def tendencia(serie, metrica="roas"):
    """¿Viene subiendo o bajando? Compara la primera mitad del periodo con la
    segunda. Devuelve el % de cambio y una palabra: sube / baja / estable."""
    datos = [d for d in (serie or []) if d.get("spend", 0) > 0]
    if len(datos) < 4:
        return {"pct": 0, "dir": "nuevo", "texto": "pocos días para ver tendencia"}
    mitad = len(datos) // 2
    def _media(xs):
        vals = [x.get(metrica, 0) for x in xs]
        return sum(vals) / len(vals) if vals else 0.0
    antes, ahora = _media(datos[:mitad]), _media(datos[mitad:])
    if not antes:
        return {"pct": 0, "dir": "nuevo", "texto": "sin referencia anterior"}
    pct = round((ahora - antes) / antes * 100)
    if pct >= 8:
        return {"pct": pct, "dir": "sube", "texto": f"viene subiendo ({pct:+d}%)"}
    if pct <= -8:
        return {"pct": pct, "dir": "baja", "texto": f"viene bajando ({pct:+d}%)"}
    return {"pct": pct, "dir": "estable", "texto": "estable"}


def salud(serie, tend):
    """Fatiga del creativo: la frecuencia sube y el rendimiento baja = quemado."""
    ultimos = [d for d in (serie or []) if d.get("spend", 0) > 0][-3:]
    frec = max((d.get("frecuencia", 0) for d in ultimos), default=0)
    if frec >= FREC_FATIGA and tend["dir"] == "baja":
        return {"estado": "quemado", "titulo": "Creativo quemado",
                "texto": f"Frecuencia en {frec:.1f} y cayendo: el público ya lo ha "
                         "visto demasiadas veces. Toca renovarlo o ampliar público.",
                "frecuencia": round(frec, 1)}
    if frec >= FREC_AVISO:
        return {"estado": "vigilar", "titulo": "Ojo a la frecuencia",
                "texto": f"Frecuencia en {frec:.1f}. Aún aguanta, pero prepara ya "
                         "la siguiente variante.",
                "frecuencia": round(frec, 1)}
    return {"estado": "sano", "titulo": "Creativo sano",
            "texto": f"Frecuencia en {frec:.1f} y tendencia {tend['dir']}. "
                     "Sin señales de fatiga por ahora.",
            "frecuencia": round(frec, 1)}


def _etiqueta_rendimiento(c):
    """La pegatina que se ve en la esquina de la tarjeta."""
    return {"ganador": ("GANADOR", "g"), "promesa": ("EN TEST", "a"),
            "matar": ("APAGAR", "r")}.get(c["estado"], ("POCOS DATOS", "m"))


def biblioteca(rows, series):
    """La biblioteca completa: cada creativo con su temperatura, su ángulo,
    su tendencia, su salud y su evolución día a día."""
    an = analiza(rows)
    por_id = {}
    for r in rows:
        por_id[(r.get("name") or "").strip()] = r.get("id") or ""

    fichas = []
    for c in an["creativos"]:
        ad_id = por_id.get(c["ad_name"], "")
        serie = series.get(ad_id, [])
        tend = tendencia(serie)
        temp_k, temp_n = TEMPERATURA.get(c["embudo"], ("", "Sin clasificar"))
        etq, etq_cls = _etiqueta_rendimiento(c)
        fichas.append({**c, "ad_id": ad_id, "temp": temp_k, "temp_nombre": temp_n,
                       "tendencia": tend, "salud": salud(serie, tend),
                       "serie": serie, "etiqueta_rend": etq, "etiqueta_cls": etq_cls})

    fichas.sort(key=lambda f: -f["spend"])
    return {
        "fichas": fichas,
        "total": len(fichas),
        "ganadores": sum(1 for f in fichas if f["estado"] == "ganador"),
        "en_test": sum(1 for f in fichas if f["estado"] == "promesa"),
        "inversion": round(sum(f["spend"] for f in fichas), 2),
        "mejor_roas": max((f["roas"] for f in fichas), default=0),
        "temperaturas": sorted({f["temp_nombre"] for f in fichas if f["temp"]}),
        "angulos": sorted({f["angulo"] for f in fichas if f["angulo"]}),
        "formatos": sorted({f["formato"] for f in fichas}),
    }


# ---------------------------------------------------------------------------
# DECISIONES POR CONJUNTO — escalar, cortar o dejar en paz.
#
# El creativo dice QUÉ producir; el conjunto dice DÓNDE va el dinero. Son dos
# decisiones distintas y hay que tomarlas por separado.
# ---------------------------------------------------------------------------
ROAS_OBJETIVO = 2.5      # a partir de aquí merece la pena subir presupuesto
ROAS_BREAKEVEN = 1.0     # por debajo se pierde dinero
GASTO_APRENDIZAJE = 20.0  # con menos que esto no hay dato: no se toca


def conjuntos(rows, series_por_id=None):
    """Veredicto por conjunto de anuncios. Cada uno con su tendencia y la
    acción concreta, para no tener que pensarlo dos veces."""
    series_por_id = series_por_id or {}
    out = []
    for r in rows:
        gasto = round(r.get("spend", 0.0), 2)
        roas = round(r.get("roas", 0.0), 2)
        ventas = int(r.get("purchases", 0))
        tend = tendencia(series_por_id.get(r.get("id", ""), []))

        if gasto < GASTO_APRENDIZAJE:
            veredicto, clase = "APRENDIZAJE", "m"
            accion = "Poco gasto, dale tiempo"
        elif roas < ROAS_BREAKEVEN:
            veredicto, clase = "CORTAR", "r"
            accion = "Bajo breakeven"
        elif roas >= ROAS_OBJETIVO and tend["dir"] != "baja":
            veredicto, clase = "ESCALAR", "g"
            accion = "Sube presupuesto 20%"
        elif tend["dir"] == "baja":
            veredicto, clase = "VIGILAR", "a"
            accion = "Cae pero sigue rentable"
        else:
            veredicto, clase = "MANTENER", "b"
            accion = "Rentable y estable"

        out.append({
            "id": r.get("id", ""), "nombre": r.get("name", ""),
            "gasto": gasto, "roas": roas, "ventas": ventas,
            "cpa": round(r.get("cpa", 0.0), 2),
            "tendencia": tend, "veredicto": veredicto, "clase": clase,
            "accion": accion,
            "serie": [d.get("roas", 0) for d in series_por_id.get(r.get("id", ""), [])],
        })
    out.sort(key=lambda x: -x["gasto"])
    libera = round(sum(c["gasto"] for c in out if c["veredicto"] == "CORTAR"), 2)
    return {
        "lista": out,
        "cortar": sum(1 for c in out if c["veredicto"] == "CORTAR"),
        "escalar": sum(1 for c in out if c["veredicto"] == "ESCALAR"),
        "vigilar": sum(1 for c in out if c["veredicto"] == "VIGILAR"),
        "sin_tocar": sum(1 for c in out if c["veredicto"] in ("MANTENER", "APRENDIZAJE")),
        "libera": libera,
    }


# ---------------------------------------------------------------------------
# EL EMBUDO, PASO A PASO — dónde se cae la gente entre el anuncio y la venta.
# ---------------------------------------------------------------------------
def embudo_visual(rows):
    """Del anuncio a la venta: cuántos llegan a cada paso y a qué precio."""
    t = lambda k: sum(r.get(k, 0) or 0 for r in rows)
    gasto = sum(r.get("spend", 0.0) for r in rows)
    imp, lpv = t("impressions"), t("lpv")
    clics, atc = t("outbound_unique"), t("add_to_cart")
    compras = t("purchases")
    ing = sum(r.get("revenue", 0.0) for r in rows)
    paso = lambda n, v, cn, cv: {"nombre": n, "valor": int(v), "coste_nombre": cn,
                                 "coste": round(cv, 2)}
    return {
        "gasto": round(gasto, 2), "ingresos": round(ing, 2),
        "roas": round(ing / gasto, 2) if gasto else 0,
        "pasos": [
            paso("Impresiones", imp, "CPM", (gasto / imp * 1000) if imp else 0),
            paso("Clics", clics, "CPC", (gasto / clics) if clics else 0),
            paso("Llegan a la web", lpv, "Coste/visita", (gasto / lpv) if lpv else 0),
            paso("Añaden al carrito", atc, "Coste/carrito", (gasto / atc) if atc else 0),
            paso("Compras", compras, "CPA", (gasto / compras) if compras else 0),
        ],
        # Dónde se pierde MÁS gente entre un paso y el siguiente
        "fuga": _mayor_fuga(imp, clics, lpv, atc, compras),
    }


def _mayor_fuga(imp, clics, lpv, atc, compras):
    """El salto del embudo donde se cae más gente, en proporción."""
    saltos = [("del anuncio al clic", clics, imp, "el creativo no mueve a hacer clic"),
              ("del clic a la web", lpv, clics, "se pierden antes de que cargue la página"),
              ("de la web al carrito", atc, lpv, "la landing no convence"),
              ("del carrito a la compra", compras, atc, "se cae en el checkout")]
    peor, peor_pct = None, 101
    for nombre, tienen, de, motivo in saltos:
        if de <= 0:
            continue
        pct = tienen / de * 100
        if pct < peor_pct:
            peor, peor_pct = {"salto": nombre, "pasan_pct": round(pct, 1),
                              "motivo": motivo}, pct
    return peor


# ---------------------------------------------------------------------------
# BRIEF DE PRODUCCIÓN — lo que hay que respetar al hacer cada variante.
# ---------------------------------------------------------------------------
ESTRUCTURA = [
    ("0-3 s", "GANCHO", "Nombra el dolor en la primera frase. Plano que corte el scroll."),
    ("3-10 s", "PROBLEMA", "Que se reconozca: la situación concreta del día a día."),
    ("10-20 s", "SOLUCIÓN", "El producto en uso, resolviendo eso mismo."),
    ("20-27 s", "PRUEBA", "Por qué creerte: resultado, testimonio o demostración."),
    ("27-32 s", "CIERRE", "Qué tiene que hacer ahora y por qué merece la pena hoy."),
]


def brief(c, linaje_de_familia=None):
    """El brief de la siguiente variante de un creativo que funciona.

    No escribe el guion —eso lo hace el chat de creativos— pero sí fija lo
    que NO se puede tocar, lo que hay que cambiar y por qué. Sale del
    diagnóstico, así que cada brief es distinto."""
    d = c.get("diag") or {}
    l = linaje_de_familia or {}
    gana = [p["fase"] for p in d.get("pasos", []) if p["ok"]]
    rompe = [p["fase"] for p in d.get("pasos", []) if not p["ok"]]

    conservar = list(d.get("replicar") or [])
    if not conservar:
        conservar = ["el guion tal cual está: es lo único medido"]

    cambiar = ["el GANCHO: mismo dolor, otras primeras palabras",
               "el AVATAR: otra persona, otra edad o acento",
               "el ESCENARIO: otro sitio, otra luz, otro plano de apertura"]
    if "Gancho" in rompe:
        cambiar[0] = ("el GANCHO ENTERO: es lo que está fallando. Prueba otro dolor "
                      "y otro plano inicial")

    return {
        "titulo": f"Brief · {c['etiqueta']}",
        "nombre_variante": l.get("siguiente_nombre") or (c["ad_name"] + "_V2"),
        "base": (f"Partes de {c['etiqueta']}: {d.get('resumen','')}"),
        "gana_en": gana, "rompe_en": rompe,
        "conservar": conservar,
        "cambiar": cambiar,
        "corregir": list(d.get("arreglar") or []),
        "estructura": [{"t": t, "b": b, "q": q} for t, b, q in ESTRUCTURA],
        "angulo": c.get("angulo", ""), "formato": c.get("formato", ""),
        "temperatura": TEMPERATURA.get(c.get("embudo", ""), ("", "sin clasificar"))[1],
        "cuantas": 3 if c["estado"] == "ganador" else 2,
    }


# ---------------------------------------------------------------------------
# 💶 PRESUPUESTO EXACTO — no "sube un 20%", sino "de 30 € pasa a 36 €".
#
# Meta reinicia el aprendizaje si el salto es grande, así que nunca se propone
# más de +50%, y cuanto más ajustado va el ROAS, más suave el paso.
# ---------------------------------------------------------------------------
def presupuesto_sugerido(cj, objetivo=ROAS_OBJETIVO):
    """Cuánto subir o bajar, en euros, y por qué."""
    act = cj.get("budget_num", 0) or 0
    roas = cj.get("roas", 0)
    if cj["veredicto"] == "CORTAR":
        libera = act if act else cj["gasto"]
        unidad = "€/día" if act else "€"
        return {"accion": "apagar", "pct": -100, "nuevo": 0,
                "texto": f"Apágalo: libera {libera:.2f} {unidad} para lo que sí funciona."}
    if cj["veredicto"] != "ESCALAR":
        return None
    # Cuanto más despegado del objetivo, más margen para subir (tope +50%).
    holgura = (roas / objetivo) if objetivo else 1
    pct = 20 if holgura < 1.4 else (35 if holgura < 2 else 50)
    if not act:
        return {"accion": "subir", "pct": pct, "nuevo": 0,
                "texto": f"Sube un {pct}%. El presupuesto de este conjunto vive en la "
                         "campaña (CBO): tócalo ahí."}
    nuevo = round(act * (1 + pct / 100), 2)
    return {"accion": "subir", "pct": pct, "nuevo": nuevo,
            "texto": f"De {act:.2f} € a {nuevo:.2f} €/día (+{pct}%). "
                     f"ROAS {roas} sobre un objetivo de {objetivo}."}


# ---------------------------------------------------------------------------
# 🥧 REPARTO DEL PRESUPUESTO — lo que gastas de verdad frente al método.
#
# Si el CBO principal se come el presupuesto del testeo, dejas de alimentar la
# máquina de creativos nuevos y el sistema se apaga solo en unas semanas.
# ---------------------------------------------------------------------------
REPARTO_OBJETIVO = [
    ("CBO Principal", 40, "Escala lo validado", ("cbo principal", "principal", "escala")),
    ("Testeo", 25, "Prueba creativos y públicos", ("abo", "test", "testeo")),
    ("Incubadora", 25, "Valida antes de escalar", ("incubadora", "incuba")),
    ("Retargeting", 10, "Recupera calientes", ("retarget", "rtg", "remarketing")),
]


def _tipo_campana(nombre):
    n = (nombre or "").lower()
    for etiqueta, _, _, claves in REPARTO_OBJETIVO:
        if any(k in n for k in claves):
            return etiqueta
    return "CBO Principal" if "cbo" in n else "Testeo"


def reparto(campanas):
    """Cuánto se lleva cada tipo de campaña frente a lo que debería."""
    total = sum(c.get("spend", 0.0) for c in campanas) or 1
    grupos = {}
    for c in campanas:
        t = _tipo_campana(c.get("name") or c.get("nombre") or "")
        g = grupos.setdefault(t, {"gasto": 0.0, "ventas": 0, "ingresos": 0.0, "n": 0})
        g["gasto"] += c.get("spend", 0.0)
        g["ventas"] += int(c.get("purchases", 0))
        g["ingresos"] += c.get("revenue", 0.0)
        g["n"] += 1
    out = []
    for etiqueta, obj, para_que, _ in REPARTO_OBJETIVO:
        g = grupos.get(etiqueta, {"gasto": 0.0, "ventas": 0, "ingresos": 0.0, "n": 0})
        real = round(g["gasto"] / total * 100)
        desv = real - obj
        out.append({
            "tipo": etiqueta, "para_que": para_que, "campanas": g["n"],
            "gasto": round(g["gasto"], 2), "real": real, "objetivo": obj,
            "desvio": desv,
            "roas": round(g["ingresos"] / g["gasto"], 2) if g["gasto"] else 0,
            "cpa": round(g["gasto"] / g["ventas"], 2) if g["ventas"] else 0,
            "estado": "ok" if abs(desv) <= 8 else ("alto" if desv > 0 else "bajo"),
        })
    peor = max(out, key=lambda x: abs(x["desvio"]))
    aviso = None
    if abs(peor["desvio"]) > 8:
        cola = ("Estás quitándole dinero al resto del sistema." if peor["desvio"] > 0
                else "Le estás dando de menos: eso frena la máquina.")
        aviso = (f"{peor['tipo']} se lleva el {peor['real']}% cuando debería rondar el "
                 f"{peor['objetivo']}%. {cola}")
    return {"lineas": out, "total": round(total, 2), "aviso": aviso}


# ---------------------------------------------------------------------------
# 📅 COMPARATIVA — este periodo frente al anterior.
# ---------------------------------------------------------------------------
def comparativa(ahora, antes):
    """Qué ha mejorado y qué ha empeorado respecto al periodo anterior."""
    def _tot(rows):
        g = sum(r.get("spend", 0.0) for r in rows)
        v = sum(int(r.get("purchases", 0)) for r in rows)
        i = sum(r.get("revenue", 0.0) for r in rows)
        imp = sum(r.get("impressions", 0) for r in rows)
        clics = sum(r.get("outbound_unique", 0) for r in rows)
        return {"gasto": g, "ventas": v, "ingresos": i,
                "roas": (i / g) if g else 0, "cpa": (g / v) if v else 0,
                "ctr": (clics / imp * 100) if imp else 0,
                "cpm": (g / imp * 1000) if imp else 0}

    a, b = _tot(ahora), _tot(antes)
    # En CPA y CPM, BAJAR es mejorar. La inversión ni mejora ni empeora sola.
    METRICAS = [("Facturación", "ingresos", "eur", True), ("Ventas", "ventas", "num", True),
                ("ROAS", "roas", "x", True), ("CPA", "cpa", "eur", False),
                ("Inversión", "gasto", "eur", None), ("CTR", "ctr", "pct", True),
                ("CPM", "cpm", "eur", False)]
    lineas = []
    for nombre, k, fmt, subir_es_bueno in METRICAS:
        va, vb = a[k], b[k]
        pct = round((va - vb) / vb * 100) if vb else 0
        if subir_es_bueno is None:
            signo = "neutro"
        elif not vb:
            # Antes cero y ahora algo: eso es mejorar, no "sin cambios".
            signo = "mejor" if (va and subir_es_bueno) else "neutro"
        else:
            mejora = pct > 0 if subir_es_bueno else pct < 0
            signo = "igual" if abs(pct) < 3 else ("mejor" if mejora else "peor")
        lineas.append({"nombre": nombre, "clave": k, "fmt": fmt,
                       "ahora": round(va, 2), "antes": round(vb, 2),
                       "pct": pct, "signo": signo})
    mejor = [l["nombre"] for l in lineas if l["signo"] == "mejor"]
    peor = [l["nombre"] for l in lineas if l["signo"] == "peor"]
    # Sin gasto antes no hay comparación posible: decirlo, no inventar mejoras.
    if not antes or not b["gasto"]:
        return {"lineas": lineas, "hay_anterior": False,
                "resumen": "El periodo anterior no tuvo actividad, así que todavía "
                           "no hay con qué comparar."}
    if not peor:
        resumen = "Periodo mejor que el anterior en todo lo que importa."
    elif not mejor:
        resumen = "Periodo peor que el anterior. Toca revisar creativos y públicos."
    else:
        resumen = (f"Mejora en {', '.join(mejor[:3]).lower()}; "
                   f"empeora en {', '.join(peor[:3]).lower()}.")
    return {"lineas": lineas, "resumen": resumen, "hay_anterior": bool(antes)}


# ---------------------------------------------------------------------------
# 🗓️ PROTOCOLO SEMANAL — dos revisiones fijas, sin tocar nada entre medias.
#
# Cambiar cosas a diario reinicia el aprendizaje de Meta y empeora el
# resultado. Por eso el protocolo dice también cuándo NO hacer nada.
# ---------------------------------------------------------------------------
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

RITUALES = {
    0: ("escalar", "Escalar y cortar",
        "Sube el presupuesto de lo que va por encima del objetivo y apaga lo que "
        "lleva días por debajo del breakeven sin recuperarse."),
    3: ("inyectar", "Inyectar creativos",
        "Mete los ganadores de la incubadora en el CBO principal y lanza en testeo "
        "los creativos nuevos de la semana."),
}
RITUAL_DIARIO = ("mirar", "Solo mirar",
                 "Comprueba que ninguna campaña se haya disparado o apagado sola. "
                 "No se toca nada más: hay que darle tiempo al algoritmo.")


def protocolo(hoy_idx, cjs, plan_semana, briefs):
    """Qué toca hacer HOY, con las acciones concretas sacadas de los datos."""
    clave, titulo, explica = RITUALES.get(hoy_idx, RITUAL_DIARIO)
    tareas = []
    if clave == "escalar":
        for c in (cjs or {}).get("lista", []):
            p = presupuesto_sugerido(c)
            if not p:
                continue
            verbo = "Subir" if p["accion"] == "subir" else "Apagar"
            tareas.append({"hacer": f"{verbo} «{c['nombre']}»", "detalle": p["texto"]})
        if not tareas:
            tareas.append({"hacer": "Nada que tocar hoy",
                           "detalle": "Ningún conjunto cumple para escalar ni para "
                                      "cortar. Déjalo correr."})
    elif clave == "inyectar":
        for b in (briefs or [])[:4]:
            tareas.append({"hacer": f"Producir {b['cuantas']} variantes · {b['titulo'][8:]}",
                           "detalle": f"Nómbralas {b['nombre_variante']}"})
        if plan_semana:
            tareas.append({"hacer": f"Objetivo de la semana: {plan_semana['total']} creativos",
                           "detalle": "Lanza en testeo lo nuevo y sube a principal lo validado."})
        if not tareas:
            tareas.append({"hacer": "Aún no hay ganadores que clonar",
                           "detalle": "Sigue testeando ángulos nuevos."})
    else:
        tareas.append({"hacer": "No tocar nada",
                       "detalle": "Hoy no toca revisión. Cambiar cosas a diario reinicia "
                                  "el aprendizaje y empeora los resultados."})
    return {
        "hoy": DIAS[hoy_idx], "clave": clave, "titulo": titulo, "explica": explica,
        "tareas": tareas,
        "semana": [{"dia": DIAS[i], "titulo": RITUALES.get(i, RITUAL_DIARIO)[1],
                    "clave": RITUALES.get(i, RITUAL_DIARIO)[0], "hoy": i == hoy_idx}
                   for i in range(7)],
    }


# ---------------------------------------------------------------------------
# 📋 EL ENCARGO DE LA SEMANA — un brief por CADA creativo que hay que producir.
#
# El plan no puede decir "25 creativos" y luego darte 2 briefs: cada pieza de
# la semana sale con sus instrucciones, tenga padre (variante de algo que
# funciona) o sea un test nuevo.
# ---------------------------------------------------------------------------
OBJETIVO_SEMANA = 25        # el listón del método
MAX_VARIANTES = 5           # más de 5 clones del mismo creativo ya es repetirse


def brief_nuevo(angulo, formato, referencia, motivo=""):
    """Brief de un creativo NUEVO (un cruce que aún no se ha probado).

    No hay diagnóstico del que tirar, así que lo que se conserva es el
    INGREDIENTE que ya funciona —el ángulo o el formato— y lo nuevo es lo otro.
    """
    nivel = (referencia or {}).get("nivel") or "L2"
    embudo_letra = {"TOFFU": "T", "MOFFU": "M", "BOFFU": "B"}.get(
        (referencia or {}).get("embudo", ""), "T")
    ang = (angulo or "GEN").upper().replace(" ", "-")
    fmt = (formato or "NUEVO").upper().replace(" ", "-")
    nombre = f"{nivel}_{embudo_letra}_{ang}_{fmt}_V1_CONCEPTO"
    return {
        "clase": "test",
        "titulo": f"Brief · {formato} × {angulo} (nuevo)",
        "nombre_variante": nombre,
        "base": motivo or f"Cruce sin probar: el ángulo «{angulo}» con el formato «{formato}».",
        "gana_en": [], "rompe_en": [],
        "conservar": [f"el ángulo «{angulo}»: mismo dolor y mismo lenguaje que en lo que ya funciona"]
                     if referencia else ["nada todavía: es un test desde cero"],
        "cambiar": [f"el FORMATO: esto va en {formato}, no como lo vienes haciendo",
                    "el GANCHO: escríbelo desde cero para este formato"],
        "corregir": [],
        "estructura": [{"t": t, "b": b, "q": q} for t, b, q in ESTRUCTURA],
        "angulo": angulo, "formato": formato,
        "temperatura": TEMPERATURA.get((referencia or {}).get("embudo", ""),
                                       ("", "Frío"))[1],
        "cuantas": 1,
        "aviso": "Sustituye CONCEPTO por el nombre de la idea antes de subirlo.",
    }


def encargo_semanal(an, objetivo=OBJETIVO_SEMANA):
    """TODO lo que hay que producir esta semana, cada pieza con su brief.

    Reparto: primero variantes de los ganadores (lo seguro), luego de las
    promesas, luego los cruces sin probar. Si con eso no se llega al objetivo,
    se suben variantes por ganador antes que inventar ideas de la nada —
    clonar lo que funciona rinde más que disparar a ciegas.
    """
    lin = {l["familia"]: l for l in (an.get("linaje") or [])}
    ganadores, promesas = an.get("ganadores", []), an.get("promesas", [])
    huecos = an.get("huecos") or []

    # Cuántas variantes por creativo, subiendo hasta llegar al objetivo.
    por_ganador, por_promesa = 3, 2
    def _total(g, p):
        return len(ganadores) * g + len(promesas) * p + min(len(huecos), 6)
    while _total(por_ganador, por_promesa) < objetivo and por_ganador < MAX_VARIANTES:
        por_ganador += 1
        if _total(por_ganador, por_promesa) < objetivo and por_promesa < MAX_VARIANTES - 1:
            por_promesa += 1

    briefs = []
    for c in ganadores:
        b = brief(c, lin.get(c["familia"]))
        b["clase"] = "variante"
        b["cuantas"] = por_ganador
        briefs.append(b)
    for c in promesas:
        b = brief(c, lin.get(c["familia"]))
        b["clase"] = "variante"
        b["cuantas"] = por_promesa
        briefs.append(b)

    # Para cada cruce sin probar, buscamos de dónde sale el ingrediente que gana.
    ref_por_angulo = {c["angulo"]: c for c in (ganadores + promesas) if c.get("angulo")}
    ref_por_formato = {c["formato"]: c for c in (ganadores + promesas)}
    for h in huecos[:6]:
        ref = ref_por_angulo.get(h["angulo"]) or ref_por_formato.get(h["formato"])
        briefs.append(brief_nuevo(h["angulo"], h["formato"], ref, h.get("razon", "")))

    piezas = sum(b["cuantas"] for b in briefs)
    faltan = max(0, objetivo - piezas)
    return {
        "briefs": briefs,
        "variantes_ganadores": len(ganadores) * por_ganador,
        "variantes_promesas": len(promesas) * por_promesa,
        "tests": min(len(huecos), 6),
        "por_ganador": por_ganador, "por_promesa": por_promesa,
        "piezas": piezas, "objetivo": objetivo, "faltan": faltan,
        # Si aún faltan, se dice claro: hay que traer ángulos del research.
        "nota_faltan": (f"Faltan {faltan} para llegar a {objetivo}. Sácalos de tu "
                        "research: ángulos que todavía no hayas puesto en marcha."
                        if faltan else None),
    }
