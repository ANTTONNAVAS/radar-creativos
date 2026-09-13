# 📡 Radar de Creativos

**Tu analista de creativos, trabajando todas las noches.**

Conecta tu cuenta de Meta y te dice qué creativos están funcionando, **por qué**
están funcionando, cuáles hay que apagar y **qué tienes que producir esta
semana** — con el nombre exacto de cada variante.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/ANTTONNAVAS/radar-creativos)

---

## Qué vas a ver

**📊 Campañas** — dónde va tu dinero y qué devuelve cada campaña.

**🎬 Formatos** — qué *concepto* te funciona (no el anuncio suelto): UGC,
podcast, antes-después, unboxing… con nota de 0 a 100 y veredicto.

**🤖 El Agente** — lo importante:

- **Tu plan de la semana** calculado solo, apuntando a 25-30 creativos
- **El porqué de cada creativo**, fase por fase:

  > 🔍 *Gana en gancho, guion y promesa — y se rompe en la landing*
  > ✅ **Gancho** — para el scroll · *54% (referencia 30%)*
  > ✅ **Guion** — mantiene: la mitad llega al final
  > ⚠️ **Landing** — llegan pero no añaden al carrito

- **Qué conservar y qué corregir** en cada variante
- **El nombre exacto** de la siguiente variante, listo para copiar
- **Qué probar**: cruces sin explorar, partiendo de lo que ya te funciona

**🌙 Y mientras duermes**: cada madrugada el agente revisa tu cuenta y te deja
escrito qué ha cambiado — quién empezó a ganar, qué variante superó a su
original, qué se quedó sin fuelle.

---

## Cómo se pone en marcha

1. Pulsa el botón de arriba y despliégalo en tu Render *(~3 min)*.
2. Abre tu URL y pega dos cosas: tu **token de Meta** (`ads_read`) y el **ID de
   tu cuenta publicitaria**. La guía del paso a paso está dentro de la web.
3. Ya está. Si quieres que trabaje de noche, pulsa **Activar el agente 24/7**.

Coste en Render: unos **7-8 $/mes** (servicio + disco).

---

## La regla de oro: nombra bien tus anuncios

El sistema entiende tus creativos **por el nombre**. Si nombras mal, se queda
ciego (y te avisa de cuáles no puede leer).

```
L3_M_HIN_TIMELINE_V2_PROGRESO VIDEO
 │  │   │      │      │     │      └ tipo: VIDEO o EST
 │  │   │      │      │     └ concepto del creativo
 │  │   │      │      └ número de VARIANTE ← obligatorio
 │  │   │      └ formato (TIMELINE, UGC, PODCAST…)
 │  │   └ ángulo o dolor
 │  └ embudo: T frío · M templado · B caliente
 └ nivel de consciencia (L1-L5)
```

El **número de variante** es lo que permite saber si una versión supera a la
anterior. Sin él, la rueda gira pero no aprende.

## El bucle

```
Publicas con esos nombres
   → el agente detecta cuál gana y en qué fase gana
   → haces variantes (mismo guion; cambias gancho, avatar y escenario)
   → el agente mide si la variante superó a su madre
   → la ganadora es la nueva madre → vuelta a empezar
```

Cada vuelta el sistema sabe un poco más.

---

## Tus datos

- Tu token vive **en tu navegador**. Por defecto el servidor no guarda nada.
- Si activas el agente 24/7, se guarda **cifrado** (hace falta para poder
  revisar tu cuenta de noche). Lo desactivas y **se borra**.
- Es tu propio despliegue: nadie más que tú tiene acceso.
- El token es de **solo lectura**: ve tus métricas, no puede tocar campañas ni
  gastar dinero.

## Qué hay dentro

| Archivo | Para qué |
|---|---|
| `app.py` | El servidor y el agente en segundo plano |
| `radar.py` | El cerebro: clasifica, diagnostica el porqué, linaje y huecos |
| `formats.py` | Lee el nombre del anuncio y agrupa por formato |
| `meta_api.py` | Habla con la API de Meta |
| `nocturno.py` | La ronda de cada madrugada |
| `store.py` | Lo único que se guarda, y cifrado |
| `templates/index.html` | La interfaz y la guía |
