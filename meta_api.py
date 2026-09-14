"""
meta_api.py — Cliente de la Meta Marketing API.

Obtiene métricas en tiempo real a 3 niveles: campaña, conjunto de anuncios
y anuncio (vídeo). Devuelve el set de métricas que se ve en Ads Manager.
"""
import os
import json
import requests

GRAPH = "https://graph.facebook.com"

LEVEL_NAME = {"campaign": "campaign_name", "adset": "adset_name", "ad": "ad_name"}
LEVEL_ID = {"campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}
LEVEL_EDGE = {"campaign": "campaigns", "adset": "adsets", "ad": "ads"}


def _version():
    return os.getenv("META_API_VERSION", "v21.0")


class MetaError(Exception):
    """Error legible para mostrar en la interfaz."""
    pass


# Caché de respuestas de la Graph API. Los límites de Meta van ligados al GASTO
# de la cuenta: una cuenta nueva con poco gasto tiene un cupo mínimo y el panel
# (drill-down + auto-refresco) lo agotaba → "User request limit reached" y
# pantallas vacías. Con caché: 3 min de datos frescos, y si Meta limita se
# sirve el último dato bueno (hasta 6h) en vez de dejar la vista en blanco.
_CACHE = {}
_TTL_FRESCO = 180
_TTL_RESCATE = 6 * 3600


def _get(path, params):
    import hashlib
    import json as _json
    import time as _time
    key = hashlib.sha1(
        (path + "|" + _json.dumps({k: str(v) for k, v in params.items()},
                                  sort_keys=True)).encode()).hexdigest()
    ahora = _time.time()
    hit = _CACHE.get(key)
    if hit and ahora - hit[0] < _TTL_FRESCO:
        return hit[1]

    url = f"{GRAPH}/{_version()}/{path}"
    try:
        r = requests.get(url, params=params, timeout=40)
        data = r.json()
    except requests.RequestException as e:
        if hit and ahora - hit[0] < _TTL_RESCATE:
            return hit[1]
        raise MetaError(f"No se pudo conectar con Meta: {e}")
    if "error" in data:
        if hit and ahora - hit[0] < _TTL_RESCATE:
            return hit[1]          # mejor dato de hace un rato que pantalla vacía
        msg = data["error"].get("message", "Error desconocido de Meta")
        if "request limit" in msg.lower() or data["error"].get("code") in (4, 17, 32):
            raise MetaError("Meta ha limitado temporalmente las consultas de esta "
                            "cuenta (cupo de la API, sube con el gasto). Espera 1-2 "
                            "minutos y recarga.")
        raise MetaError(msg)
    _CACHE[key] = (ahora, data)
    if len(_CACHE) > 500:          # que no crezca sin límite
        _CACHE.pop(next(iter(_CACHE)))
    return data


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _sum_action(actions, *types):
    """Suma el valor de las action_type que coincidan (para vídeo)."""
    total = 0.0
    if actions:
        for a in actions:
            if a.get("action_type") in types:
                total += _f(a.get("value"))
    return total


def _pick(items, priority):
    """Devuelve el valor del PRIMER action_type de la lista de prioridad que exista
    (evita el doble conteo de Meta, que devuelve la misma compra en varios action_type).
    Si ninguno coincide exacto, cae al primero cuyo tipo termine igual (p.ej. *purchase)."""
    if not items:
        return 0.0
    idx = {}
    for a in items:
        t = a.get("action_type")
        if t is not None:
            idx[t] = _f(a.get("value"))
    for t in priority:
        if t in idx:
            return idx[t]
    suffix = priority[-1].split(".")[-1] if priority else ""
    for t, v in idx.items():
        if suffix and t.endswith(suffix):
            return v
    return 0.0


# Orden de prioridad de action_types (compra, carrito, checkout)
PURCHASE_PRI = ["omni_purchase", "offsite_conversion.fb_pixel_purchase",
                "onsite_web_purchase", "web_in_store_purchase", "purchase"]
ATC_PRI = ["omni_add_to_cart", "offsite_conversion.fb_pixel_add_to_cart", "add_to_cart"]
CHECKOUT_PRI = ["omni_initiated_checkout",
                "offsite_conversion.fb_pixel_initiate_checkout", "initiate_checkout"]
LPV_PRI = ["omni_landing_page_view", "landing_page_view"]
ADD_PAYMENT_PRI = ["omni_add_payment_info",
                   "offsite_conversion.fb_pixel_add_payment_info", "add_payment_info"]


def _get_entities(token, account, level, parent_id=None):
    """Devuelve dict id -> {name, effective_status, presupuesto}.
    Si estamos metidos en un padre, pedimos SUS hijos directamente
    ({campaign_id}/adsets o {adset_id}/ads), no todos los de la cuenta."""
    node = parent_id if (parent_id and level != "campaign") else f"act_{account}"
    fields = "name,effective_status"
    if level in ("campaign", "adset"):
        # El presupuesto vive en el objeto (no en insights). Solo campaña/conjunto.
        fields += ",daily_budget,lifetime_budget"
    data = _get(
        f"{node}/{LEVEL_EDGE[level]}",
        {"fields": fields, "limit": 500, "access_token": token},
    )
    return {e["id"]: e for e in data.get("data", [])}


def _budget_str(ent, level):
    """Texto de presupuesto tal como lo muestra Ads Manager."""
    if level == "ad":
        return "—"
    daily = ent.get("daily_budget")
    life = ent.get("lifetime_budget")
    if daily and _f(daily) > 0:
        return f"{_f(daily) / 100:.2f} €/día"
    if life and _f(life) > 0:
        return f"{_f(life) / 100:.2f} €"
    # Campaña sin presupuesto propio = presupuesto a nivel de conjunto (CBO off)
    return "No compartido"


def list_ad_accounts(token):
    """Lista las cuentas publicitarias a las que el token tiene acceso,
    para elegirlas fácil en Configuración (nombre + id)."""
    if not token:
        return []
    data = _get("me/adaccounts",
                {"fields": "name,account_id", "limit": 200, "access_token": token})
    out = []
    for a in data.get("data", []):
        out.append({"account_id": a.get("account_id", ""),
                    "name": a.get("name", "(sin nombre)")})
    return out


def get_insights(token, account, level="campaign", date_preset="last_7d",
                 filters=None, parent_id=None, time_range=None):
    """
    level: campaign | adset | ad
    date_preset: today | yesterday | last_7d | last_30d | maximum
    filters: lista de filtros de Meta para "meternos" dentro de un padre
             (p.ej. solo los conjuntos de una campaña), o None.
    parent_id: id del padre (campaña/conjunto) cuando estamos metidos dentro.
    Devuelve lista de filas con todas las métricas.
    """
    if not token or not account:
        raise MetaError("Falta el token o el ID de cuenta. Configúralos en la app.")
    if level not in LEVEL_NAME:
        level = "campaign"

    act = f"act_{account}"
    entities = _get_entities(token, account, level, parent_id)

    idf, namef = LEVEL_ID[level], LEVEL_NAME[level]
    # Pedimos los MISMOS campos que calcula Meta (no recalculamos nada por
    # nuestra cuenta) para que los números salgan idénticos a Ads Manager.
    fields = (
        f"{idf},{namef},spend,impressions,frequency,cpm,"
        "cost_per_inline_link_click,unique_ctr,unique_inline_link_click_ctr,"
        "unique_outbound_clicks,"
        "actions,action_values,cost_per_action_type,purchase_roas,"
        "video_p25_watched_actions,video_p50_watched_actions,"
        "video_p75_watched_actions,video_p95_watched_actions"
    )
    params = {
        "level": level,
        "fields": fields,
        # Usa la MISMA atribución que ves en Ads Manager (si no, los números bailan)
        "use_unified_attribution_setting": "true",
        "limit": 500,
        "access_token": token,
    }
    if time_range:
        params["time_range"] = json.dumps(time_range)
    else:
        params["date_preset"] = date_preset
    # Si venimos "metidos" dentro de una campaña/conjunto, filtramos por el padre
    if filters:
        params["filtering"] = json.dumps(filters)
    ins = _get(f"{act}/insights", params)

    # Insights SOLO trae entidades con entrega. Las cruzamos con la lista
    # completa para que también salgan las que aún no han gastado (todo a 0),
    # igual que en el Administrador de Anuncios.
    ins_by_id = {r.get(idf): r for r in ins.get("data", [])}
    all_ids = list(entities.keys())
    for iid in ins_by_id:
        if iid not in entities:
            all_ids.append(iid)

    rows = []
    for eid in all_ids:
        ent = entities.get(eid, {})
        r = ins_by_id.get(eid, {})
        status = ent.get("effective_status", "")
        # Ocultar borradas/archivadas que además no tienen gasto (como Ads Manager)
        if status in ("DELETED", "ARCHIVED") and eid not in ins_by_id:
            continue
        spend = _f(r.get("spend"))
        impressions = int(_f(r.get("impressions")))
        purchases = _pick(r.get("actions", []), PURCHASE_PRI)
        revenue = _pick(r.get("action_values", []), PURCHASE_PRI)
        atc = _pick(r.get("actions", []), ATC_PRI)
        lpv = _pick(r.get("actions", []), LPV_PRI)            # Visitas a la página de destino
        add_payment = _pick(r.get("actions", []), ADD_PAYMENT_PRI)  # Info de pago agregada
        # Clics salientes únicos y reproducciones de 3 s (para el HOOK RATE).
        # Las de 3 s salen de actions->video_view (NO de las que solo arrancan).
        uoc = _sum_action(r.get("unique_outbound_clicks", []), "outbound_click")
        v3 = _sum_action(r.get("actions", []), "video_view")

        roas_list = r.get("purchase_roas", [])
        roas = _f(roas_list[0].get("value")) if roas_list else 0.0
        # Si Meta no devuelve ROAS pero sí hay ingresos, lo calculamos
        if not roas and spend > 0 and revenue > 0:
            roas = revenue / spend

        # CPA (coste por compra) TAL CUAL lo da Meta. Solo si no lo devuelve,
        # caemos al cálculo gasto/compras para no dejarlo vacío.
        cpa_meta = _pick(r.get("cost_per_action_type", []), PURCHASE_PRI)
        cpa = cpa_meta if cpa_meta else ((spend / purchases) if purchases else 0.0)

        # Coste por artículo agregado al carrito, TAL CUAL lo da Meta.
        cpatc_meta = _pick(r.get("cost_per_action_type", []), ATC_PRI)
        cost_cart = cpatc_meta if cpatc_meta else ((spend / atc) if atc else 0.0)

        # Columnas del preset ECOM (verificadas número a número con Ads Manager)
        checkout = _pick(r.get("actions", []), CHECKOUT_PRI)      # Pagos iniciados
        cost_checkout_meta = _pick(r.get("cost_per_action_type", []), CHECKOUT_PRI)
        cost_checkout = cost_checkout_meta if cost_checkout_meta else (
            (spend / checkout) if checkout else 0.0)
        cost_lpv_meta = _pick(r.get("cost_per_action_type", []), LPV_PRI)
        cost_lpv = cost_lpv_meta if cost_lpv_meta else ((spend / lpv) if lpv else 0.0)

        rows.append({
            "id": eid,
            "name": r.get(namef) or ent.get("name", "(sin nombre)"),
            "status": status,
            "spend": spend,
            "budget": _budget_str(ent, level),
            # El presupuesto en número (Meta lo da en céntimos): hace falta
            # para poder sugerir la cifra exacta a la que subirlo.
            "budget_num": round(_f(ent.get("daily_budget") or 0) / 100, 2),
            "impressions": impressions,
            "frequency": _f(r.get("frequency")),
            "cpm": _f(r.get("cpm")),
            "cpc_link": _f(r.get("cost_per_inline_link_click")),  # CPC (enlace)
            # CTR único de clics en el ENLACE (la columna del preset ECOM de Ads
            # Manager); si Meta no lo trae, caemos al CTR único general.
            "ctr_unique": _f(r.get("unique_inline_link_click_ctr")) or _f(r.get("unique_ctr")),
            "outbound_unique": int(uoc),                          # Clics salientes únicos
            "lpv": int(lpv),                                      # Visitas a la LP
            "add_to_cart": int(atc),
            "add_payment": int(add_payment),
            "purchases": int(purchases),
            "cpa": cpa,
            "revenue": revenue,
            "roas": roas,
            # --- Métricas personalizadas (calculadas, verificadas con tu captura) ---
            "hook_rate": (v3 / impressions * 100) if impressions else 0.0,
            "speed": (lpv / uoc * 100) if uoc else 0.0,          # Visitas LP / clics salientes
            "carrito": (atc / lpv * 100) if lpv else 0.0,        # Art. carrito / Visitas LP
            "cost_cart": cost_cart,                               # Coste por carrito agregado
            "cform": (purchases / atc * 100) if atc else 0.0,    # Compras / Art. carrito
            # --- Preset ECOM de Ads Manager (mismas columnas y fórmulas) ---
            "cost_lpv": cost_lpv,                                 # Coste por visita a LP
            "checkout": int(checkout),                            # Pagos iniciados
            "cost_checkout": cost_checkout,                       # Coste por pago iniciado
            "atc_pct": (atc / lpv * 100) if lpv else 0.0,        # ADD TO CART
            "checkout_pct": (checkout / lpv * 100) if lpv else 0.0,  # INICIO CHECKOUT
            "cr": (purchases / lpv * 100) if lpv else 0.0,       # CR
            "v25": int(_sum_action(r.get("video_p25_watched_actions", []), "video_view")),
            "v50": int(_sum_action(r.get("video_p50_watched_actions", []), "video_view")),
            "v75": int(_sum_action(r.get("video_p75_watched_actions", []), "video_view")),
            "v95": int(_sum_action(r.get("video_p95_watched_actions", []), "video_view")),
        })

    rows.sort(key=lambda x: (x["status"] != "ACTIVE", -x["spend"]))
    return rows


def get_daily(token, account, date_preset="last_7d", time_range=None):
    """Totales de la CUENTA día a día (para 'cómo ha ido cada día').
    Usa time_increment=1 → una fila por día. Devuelve lista ordenada por fecha.
    time_range: dict {"since":"YYYY-MM-DD","until":"YYYY-MM-DD"} para un rango exacto
    (tiene prioridad sobre date_preset)."""
    if not token or not account:
        raise MetaError("Falta el token o el ID de cuenta. Configúralos en la app.")
    act = f"act_{account}"
    params = {
        "level": "account",
        "fields": "spend,impressions,actions,action_values,purchase_roas",
        "time_increment": 1,
        "use_unified_attribution_setting": "true",
        "limit": 500,
        "access_token": token,
    }
    if time_range:
        params["time_range"] = json.dumps(time_range)
    else:
        params["date_preset"] = date_preset
    data = _get(f"{act}/insights", params)
    days = []
    for r in data.get("data", []):
        spend = _f(r.get("spend"))
        purchases = _pick(r.get("actions", []), PURCHASE_PRI)
        revenue = _pick(r.get("action_values", []), PURCHASE_PRI)
        lpv = _pick(r.get("actions", []), LPV_PRI)
        atc = _pick(r.get("actions", []), ATC_PRI)
        roas_list = r.get("purchase_roas", [])
        roas = _f(roas_list[0].get("value")) if roas_list else (
            revenue / spend if spend > 0 else 0.0)
        cpa = (spend / purchases) if purchases else 0.0
        days.append({
            "date": r.get("date_start"),
            "spend": spend,
            "impressions": int(_f(r.get("impressions"))),
            "purchases": int(purchases),
            "revenue": revenue,
            "roas": roas,
            "cpa": cpa,
            "lpv": int(lpv),
            "atc": int(atc),
        })
    days.sort(key=lambda d: d["date"] or "")
    return days


def account_summary(rows):
    """Totales agregados para las tarjetas de arriba."""
    total_spend = sum(r["spend"] for r in rows)
    total_rev = sum(r["revenue"] for r in rows)
    total_purch = sum(r["purchases"] for r in rows)
    active = sum(1 for r in rows if r["status"] == "ACTIVE")
    roas = (total_rev / total_spend) if total_spend else 0
    cpa = (total_spend / total_purch) if total_purch else 0
    return {
        "total_spend": total_spend,
        "total_revenue": total_rev,
        "total_purchases": total_purch,
        "active_campaigns": active,
        "total_campaigns": len(rows),
        "roas": roas,
        "cpa": cpa,
    }


def serie_diaria_ads(token, account, date_preset="last_14d", time_range=None, nivel="ad"):
    """Día a día de CADA anuncio en una sola llamada (time_increment=1).

    Es lo que permite dibujar la evolución de un creativo sin esperar a
    acumular histórico: Meta ya guarda el desglose por día, solo hay que
    pedírselo. Devuelve {ad_id: [ {dia, spend, ventas, roas, cpa, ctr}, ... ]}.
    """
    if not token or not account:
        raise MetaError("Falta el token o el ID de cuenta.")
    idf = {"ad": "ad_id", "adset": "adset_id", "campaign": "campaign_id"}[nivel]
    namef = {"ad": "ad_name", "adset": "adset_name", "campaign": "campaign_name"}[nivel]
    params = {
        "level": nivel,
        "fields": f"{idf},{namef},spend,impressions,frequency,"
                  "unique_inline_link_click_ctr,actions,action_values,purchase_roas",
        "time_increment": 1,
        "use_unified_attribution_setting": "true",
        "limit": 500,
        "access_token": token,
    }
    if time_range:
        params["time_range"] = json.dumps(time_range)
    else:
        params["date_preset"] = date_preset

    out = {}
    data = _get(f"act_{account}/insights", params)
    for r in data.get("data", []):
        spend = _f(r.get("spend"))
        ventas = _pick(r.get("actions", []), PURCHASE_PRI)
        ingresos = _pick(r.get("action_values", []), PURCHASE_PRI)
        roas_l = r.get("purchase_roas", [])
        roas = _f(roas_l[0].get("value")) if roas_l else (ingresos / spend if spend else 0.0)
        out.setdefault(r.get(idf, ""), []).append({
            "dia": r.get("date_start", ""),
            "nombre": r.get(namef, ""),
            "spend": round(spend, 2),
            "ventas": int(ventas),
            "ingresos": round(ingresos, 2),
            "roas": round(roas, 2),
            "cpa": round(spend / ventas, 2) if ventas else 0.0,
            "ctr": round(_f(r.get("unique_inline_link_click_ctr")), 2),
            "frecuencia": round(_f(r.get("frequency")), 2),
            "impresiones": int(_f(r.get("impressions"))),
        })
    for v in out.values():
        v.sort(key=lambda x: x["dia"])
    return out
