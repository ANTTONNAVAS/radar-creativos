"""
formats.py — Agrupa los anuncios de Meta por FORMATO leyendo el nombre del anuncio.

Convención NUEVA:  L3_M_HIN_TIMELINE_V1_PROGRESO ESTATICO
  L#       -> nivel de conciencia (L1..L5)
  EMBUDO   -> T / M / B   (también valen TOFFU / MOFFU / BOFFU, de antes)
  ÁNGULO   -> HIN / ANT / GEN  (también HINCHAZON / ANTOJOS, de antes)
  FORMATO  -> el concepto (TIMELINE, PODCAST, DOCTORA, COMPARATIVA...)
  V#       -> versión
  NOMBRE   -> el concepto del creativo ("PROGRESO")
  TIPO     -> EST / VIDEO, al final del nombre
  LANDING  -> LG (landing general), después del tipo

Los nombres viejos siguen leyéndose: la detección va por contenido, no por
posición, así que conviven las dos convenciones sin tocar nada.

No inventa métricas: reutiliza las que ya calcula meta_api.get_insights(level="ad").
El formato "se cualifica" solo con una nota 0-100 según los objetivos del dossier.
"""
import re

EMBUDOS = ["TOFFU", "MOFFU", "BOFFU", "TOFU", "MOFU", "BOFU"]
# Productos conocidos que NO son formato (se ignoran). Amplía si usas otros tags "P...".
PRODUCTOS = ["PNUTRIVIDA", "PNOVEXA", "PNUEVO", "P NUTRIVIDA", "P NOVEXA", "P NUEVO"]


# Embudo en una letra (convención nueva) y en palabra (la de antes)
_EMBUDO_LETRA = {"T": "TOFFU", "M": "MOFFU", "B": "BOFFU"}
_EMBUDO_PALABRA = ("TOFFU", "MOFFU", "BOFFU", "TOFU", "MOFU", "BOFU")

# Tipo de asset: va pegado al final del nombre ("PROGRESO ESTATICO")
_TIPO_ASSET = {
    "ESTATICO": "estático", "ESTATICA": "estático", "ESTÁTICO": "estático",
    "ESTÁTICA": "estático", "STATIC": "estático", "IMAGEN": "estático",
    "IMG": "estático", "FOTO": "estático",
    # forma corta que se usa de verdad en la pizarra
    "EST": "estático", "ESTAT": "estático",
    "VIDEO": "vídeo", "VÍDEO": "vídeo", "VID": "vídeo", "REEL": "vídeo",
    "MP4": "vídeo", "GIF": "vídeo",
}

# A dónde manda el anuncio. Va DESPUÉS del tipo ("..._VIDEO_LG"). Solo se
# aparta lo que conocemos: un código raro se queda en el nombre antes que
# inventarle un significado.
_LANDING = {"LG": "landing general"}

# Ángulos abreviados que ya conocemos. La lista NO es cerrada: en la posición
# del ángulo vale cualquier código, y el que no esté aquí se queda tal cual.
_ANGULO_CORTO = {"HIN": "hinchazon", "ANT": "antojos", "GEN": "generico",
                 "REG": "regularidad", "COM": "comidas", "ENE": "energia",
                 "GAS": "gases", "SIB": "sibo", "VPL": "vientre plano"}


def _norm_embudo(e):
    return e.replace("TOFU", "TOFFU").replace("MOFU", "MOFFU").replace("BOFU", "BOFFU")


def _lee_angulo(s):
    """'HIN' / 'HINCHAZON' / 'ANT' / 'ANTOJOS' / 'GEN' -> nombre del ángulo."""
    if s in _ANGULO_CORTO:
        return _ANGULO_CORTO[s]
    if s.startswith("HINCHAZ"):
        return "hinchazon"
    if s.startswith("ANTOJOS"):
        return "antojos"
    if s.startswith("GENERICO"):
        return "generico"
    return None

# --- Objetivos que definen la nota 0-100 (del dossier; ajustables) ---
CPA_BUENO, CPA_MAX = 6.0, 15.0   # CPA: 100 si <=6€, 0 si >=15€
ROAS_OBJ = 7.0                   # ROAS: 100 si >=7
HOOK_OBJ = 50.0                  # Hook: 100 si >=50%
PESO_CPA, PESO_ROAS, PESO_HOOK = 0.4, 0.4, 0.2
GASTO_MIN_FIABLE = 10.0          # por debajo de esto -> "pocos datos"


def parse_ad_name(name):
    """Lee el nombre del anuncio con la convención:
        L3_M_HIN_TIMELINE_V1_PROGRESO ESTATICO
    El FORMATO es el segmento justo DESPUÉS del ángulo (su campo propio).
    Detecta nivel/conciencia/ángulo/versión por contenido (tolerante al orden).
    Si el anuncio no lleva formato tras el ángulo -> '(SIN FORMATO)'."""
    segs = [s.strip() for s in (name or "").upper().split("_") if s.strip()]

    nivel = embudo = angulo = version = None
    ang_idx = None
    for i, s in enumerate(segs):
        if nivel is None and re.fullmatch(r"L[1-5]", s):
            nivel = s
        elif embudo is None and s in _EMBUDO_PALABRA:
            embudo = _norm_embudo(s)
        elif embudo is None and s in _EMBUDO_LETRA:
            embudo = _EMBUDO_LETRA[s]
        elif angulo is None and _lee_angulo(s):
            angulo = _lee_angulo(s)
            ang_idx = i
        elif version is None and re.fullmatch(r"V\d+", s):
            version = s

    # Si no reconocimos el ángulo por su nombre, va POR POSICIÓN: el ángulo es
    # SIEMPRE el segmento justo después del embudo, se llame como se llame y
    # mida lo que mida. Así entran códigos nuevos (REG, COM, CAMISA, SUJETA...)
    # y también los nombres que no empiezan por nivel:
    #    L3_M_HIN_TIMELINE_V1_PROGRESO      -> ángulo HIN, formato TIMELINE
    #    L4_T_CAMISA_UGC_VIAJERO_SUEÑO_V2   -> ángulo CAMISA, formato UGC
    #    MODA_AURE_B_SUJETA_UNBOXING_V1_...  -> ángulo SUJETA, formato UNBOXING
    if angulo is None:
        for i, s in enumerate(segs):
            if s not in _EMBUDO_LETRA and s not in _EMBUDO_PALABRA:
                continue
            # hace falta un segmento para el ángulo y otro para el formato
            if i + 2 < len(segs) and not re.fullmatch(r"V\d+", segs[i + 1]):
                angulo = _ANGULO_CORTO.get(segs[i + 1], segs[i + 1].lower())
                ang_idx = i + 1
            break

    # FORMATO = primer segmento (no-versión) después del ángulo; el resto = nombre creativo
    formato, nombre = "(SIN FORMATO)", None
    if ang_idx is not None:
        picked, rest = False, []
        for s in segs[ang_idx + 1:]:
            if re.fullmatch(r"V\d+", s):
                version = version or s
            elif not picked:
                formato, picked = s, True
            else:
                rest.append(s)
        for prod in PRODUCTOS:               # por si el producto se coló pegado
            formato = formato.replace(prod, "").strip()
        formato = re.sub(r"\s+", " ", formato).strip(" -_") or "(SIN FORMATO)"
        nombre = " ".join(rest).strip() or None

    # El tipo de asset viaja pegado al final del nombre: "PROGRESO ESTATICO"
    tipo, landing = None, None
    if nombre:
        palabras = nombre.split()
        # primero el sufijo de tamaño, si lo lleva ("PROBIOTICOS VIDEO LG")
        if len(palabras) > 1 and palabras[-1] in _LANDING:
            landing = _LANDING[palabras[-1]]
            palabras = palabras[:-1]
        if palabras and palabras[-1] in _TIPO_ASSET:
            tipo = _TIPO_ASSET[palabras[-1]]
            palabras = palabras[:-1]
        nombre = " ".join(palabras).strip() or None

    return {
        "nivel": nivel, "embudo": embudo, "angulo": angulo,
        "version": version, "formato": formato, "nombre": nombre, "tipo": tipo,
        "landing": landing,
    }


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def _score(cpa, roas, hook, purchases):
    cpa_s = _clamp((CPA_MAX - cpa) / (CPA_MAX - CPA_BUENO) * 100) if purchases else 0.0
    roas_s = _clamp(roas / ROAS_OBJ * 100)
    hook_s = _clamp(hook / HOOK_OBJ * 100)
    return round(PESO_CPA * cpa_s + PESO_ROAS * roas_s + PESO_HOOK * hook_s)


def _veredicto(score, spend):
    if spend < GASTO_MIN_FIABLE:
        return ("pocos", "⚪ Pocos datos")
    if score >= 70:
        return ("escalar", "🟢 Escalar")
    if score >= 40:
        return ("vigilar", "🟡 Vigilar")
    return ("quemar", "🔴 Quemar")


def build_formats(rows):
    """rows = salida de meta_api.get_insights(level='ad').
    Devuelve la lista de formatos, cada uno con su agregado, su nota y sus creativos."""
    buckets = {}
    for r in rows:
        p = parse_ad_name(r.get("name", ""))
        b = buckets.setdefault(p["formato"], {
            "formato": p["formato"], "creativos": [],
            "spend": 0.0, "purchases": 0, "revenue": 0.0,
            "impressions": 0, "hook_imp": 0.0, "niveles": set(), "angulos": set(),
            "tipos": set(),
        })
        cre = dict(r)
        cre.update(nivel=p["nivel"], embudo=p["embudo"], angulo=p["angulo"],
                   version=p["version"], nombre=p["nombre"], tipo=p["tipo"],
                   landing=p["landing"])
        b["creativos"].append(cre)
        b["spend"] += r.get("spend", 0.0)
        b["purchases"] += r.get("purchases", 0)
        b["revenue"] += r.get("revenue", 0.0)
        b["impressions"] += r.get("impressions", 0)
        b["hook_imp"] += r.get("hook_rate", 0.0) * r.get("impressions", 0)
        if p["nivel"]:
            b["niveles"].add(p["nivel"])
        if p["angulo"]:
            b["angulos"].add(p["angulo"])
        if p["tipo"]:
            b["tipos"].add(p["tipo"])

    out = []
    for b in buckets.values():
        spend, purch, rev = b["spend"], b["purchases"], b["revenue"]
        cpa = (spend / purch) if purch else 0.0
        roas = (rev / spend) if spend else 0.0
        hook = (b["hook_imp"] / b["impressions"]) if b["impressions"] else 0.0
        score = _score(cpa, roas, hook, purch)
        vclass, vlabel = _veredicto(score, spend)
        b["creativos"].sort(key=lambda c: -c.get("spend", 0.0))
        out.append({
            "formato": b["formato"], "n_creativos": len(b["creativos"]),
            "spend": spend, "purchases": purch, "revenue": rev,
            "cpa": cpa, "roas": roas, "hook_rate": hook,
            "score": score, "veredicto_class": vclass, "veredicto": vlabel,
            "niveles": sorted(b["niveles"]), "angulos": sorted(b["angulos"]),
            "tipos": sorted(b["tipos"]),
            "creativos": b["creativos"],
        })
    out.sort(key=lambda f: (-f["score"], -f["spend"]))  # mejor nota primero
    return out
