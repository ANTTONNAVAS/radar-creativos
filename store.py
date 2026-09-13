# -*- coding: utf-8 -*-
"""
store.py — Lo único que guardamos, y cómo lo guardamos.

Por defecto el Radar no almacena NADA: el token vive en el navegador del
alumno. Pero para que el agente trabaje de noche (cuando nadie tiene el
navegador abierto) el servidor necesita poder entrar en su cuenta. Así que
quien ACTIVA el agente 24/7 nos deja su token, y aquí se guarda **cifrado**.

Reglas que se respetan siempre:
  · El token se cifra en reposo (Fernet). En la base de datos no hay nada legible.
  · El alumno puede desactivar el agente y su token se BORRA, no se marca.
  · No guardamos nada más: ni email, ni contraseñas, ni datos de sus clientes.
"""
import base64
import hashlib
import os
import sqlite3
import secrets
from datetime import datetime

from cryptography.fernet import Fernet

DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(DATA_DIR, "radar.db")


def _clave():
    """Clave de cifrado derivada del secreto del servidor. Si cambia el
    secreto, los tokens guardados dejan de poder leerse (y hay que volver a
    activar el agente) — que es justo lo que debe pasar."""
    secreto = os.getenv("CLAVE_TOKENS") or os.getenv("SECRET_KEY") or "radar-dev-local"
    return base64.urlsafe_b64encode(hashlib.sha256(secreto.encode()).digest())


def cifra(txt):
    return Fernet(_clave()).encrypt((txt or "").encode()).decode()


def descifra(txt):
    try:
        return Fernet(_clave()).decrypt((txt or "").encode()).decode()
    except Exception:
        return ""


def conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    return c


def init():
    c = conn()
    c.execute("""
        CREATE TABLE IF NOT EXISTS cuentas (
            codigo TEXT PRIMARY KEY,        -- identifica al alumno, sin datos personales
            nombre TEXT DEFAULT '',         -- solo para que se reconozca ("SAFORA")
            token_cif TEXT NOT NULL,        -- token de Meta CIFRADO
            cuenta TEXT NOT NULL,           -- id de cuenta publicitaria
            rango TEXT DEFAULT 'last_7d',
            alta TEXT NOT NULL,
            ultima_revision TEXT DEFAULT ''
        )""")
    # Foto de cada creativo por día: es lo que permite comparar hoy con ayer.
    c.execute("""
        CREATE TABLE IF NOT EXISTS fotos (
            codigo TEXT NOT NULL, dia TEXT NOT NULL, ad_name TEXT NOT NULL,
            familia TEXT DEFAULT '', etiqueta TEXT DEFAULT '',
            estado TEXT DEFAULT '', score INTEGER DEFAULT 0,
            spend REAL DEFAULT 0, purchases INTEGER DEFAULT 0, roas REAL DEFAULT 0,
            PRIMARY KEY (codigo, dia, ad_name)
        )""")
    # Lo que el agente encontró esa noche, ya redactado.
    c.execute("""
        CREATE TABLE IF NOT EXISTS novedades (
            codigo TEXT NOT NULL, dia TEXT NOT NULL,
            tipo TEXT NOT NULL,             -- gano / perdio / supera / nuevo / murio
            texto TEXT NOT NULL,
            etiqueta TEXT DEFAULT ''
        )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_nov ON novedades(codigo, dia)")
    c.commit()
    c.close()


def alta_cuenta(nombre, token, cuenta, rango="last_7d"):
    """Activa el agente 24/7 para un alumno. Devuelve su código."""
    init()
    codigo = secrets.token_urlsafe(9)
    c = conn()
    c.execute("INSERT INTO cuentas (codigo,nombre,token_cif,cuenta,rango,alta) "
              "VALUES (?,?,?,?,?,?)",
              (codigo, (nombre or "").strip()[:40], cifra(token), cuenta, rango,
               datetime.now().isoformat(timespec="seconds")))
    c.commit()
    c.close()
    return codigo


def baja_cuenta(codigo):
    """Desactiva el agente y BORRA el token. Sin rastro."""
    c = conn()
    n = c.execute("DELETE FROM cuentas WHERE codigo=?", (codigo,)).rowcount
    c.execute("DELETE FROM fotos WHERE codigo=?", (codigo,))
    c.execute("DELETE FROM novedades WHERE codigo=?", (codigo,))
    c.commit()
    c.close()
    return n


def cuentas():
    init()
    c = conn()
    filas = c.execute("SELECT * FROM cuentas").fetchall()
    c.close()
    return [{**dict(f), "token": descifra(f["token_cif"])} for f in filas]


def get_cuenta(codigo):
    c = conn()
    f = c.execute("SELECT * FROM cuentas WHERE codigo=?", (codigo,)).fetchone()
    c.close()
    return {**dict(f), "token": descifra(f["token_cif"])} if f else None


def guarda_foto(codigo, dia, creativos):
    c = conn()
    for x in creativos:
        c.execute("INSERT OR REPLACE INTO fotos "
                  "(codigo,dia,ad_name,familia,etiqueta,estado,score,spend,purchases,roas) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (codigo, dia, x["ad_name"], x["familia"], x["etiqueta"],
                   x["estado"], x["score"], x["spend"], x["purchases"], x["roas"]))
    c.execute("UPDATE cuentas SET ultima_revision=? WHERE codigo=?",
              (datetime.now().isoformat(timespec="seconds"), codigo))
    c.commit()
    c.close()


def foto_anterior(codigo, dia):
    """La foto más reciente ANTERIOR a hoy: con lo que se compara."""
    c = conn()
    d = c.execute("SELECT MAX(dia) d FROM fotos WHERE codigo=? AND dia<?",
                  (codigo, dia)).fetchone()["d"]
    if not d:
        c.close()
        return {}
    filas = c.execute("SELECT * FROM fotos WHERE codigo=? AND dia=?", (codigo, d)).fetchall()
    c.close()
    return {f["ad_name"]: dict(f) for f in filas}


def guarda_novedades(codigo, dia, items):
    c = conn()
    c.execute("DELETE FROM novedades WHERE codigo=? AND dia=?", (codigo, dia))
    for it in items:
        c.execute("INSERT INTO novedades (codigo,dia,tipo,texto,etiqueta) VALUES (?,?,?,?,?)",
                  (codigo, dia, it["tipo"], it["texto"], it.get("etiqueta", "")))
    c.commit()
    c.close()


def ultimas_novedades(codigo):
    """Lo que encontró el agente la última vez que revisó."""
    c = conn()
    d = c.execute("SELECT MAX(dia) d FROM novedades WHERE codigo=?", (codigo,)).fetchone()["d"]
    if not d:
        c.close()
        return {"dia": "", "items": []}
    filas = c.execute("SELECT tipo,texto,etiqueta FROM novedades WHERE codigo=? AND dia=?",
                      (codigo, d)).fetchall()
    c.close()
    return {"dia": d, "items": [dict(f) for f in filas]}


# --- Marca de la última ronda del agente (para no repetirla el mismo día) ---
def _kv():
    c = conn()
    c.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    c.commit()
    return c


def get_kv(k, defecto=""):
    c = _kv()
    f = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    c.close()
    return f["v"] if f else defecto


def set_kv(k, v):
    c = _kv()
    c.execute("INSERT OR REPLACE INTO kv (k,v) VALUES (?,?)", (k, str(v)))
    c.commit()
    c.close()
