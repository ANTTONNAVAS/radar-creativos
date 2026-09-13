# 📡 Radar de Creativos

SaaS de una sola página para alumnos: conecta su cuenta de Meta y ve
**qué creativos funcionan, por qué, y qué producir esta semana**.

## Cómo se despliega (una vez)

1. Sube esta carpeta a un repositorio de GitHub.
2. En **render.com** → *New* → *Blueprint* → elige el repositorio.
3. Listo. No hay variables de entorno que rellenar.

## Por qué no hay base de datos ni cuentas de usuario

Cada alumno pega su **token de Meta** y su **ID de cuenta**, y eso se guarda
**en su navegador** (localStorage). El servidor no almacena nada de nadie:

- no hay altas, contraseñas ni recuperación de cuenta,
- no custodiamos datos sensibles de nadie,
- un solo despliegue sirve a todos los alumnos.

## Qué hay dentro

| Archivo | Para qué |
|---|---|
| `app.py` | El servidor: una página y una llamada a la API |
| `meta_api.py` | Habla con la API de Meta |
| `formats.py` | Lee el nombre del anuncio y agrupa por formato |
| `radar.py` | El cerebro: clasifica, diagnostica el porqué, linaje y huecos |
| `templates/index.html` | Toda la interfaz y la guía del alumno |

La guía para el alumno está **dentro de la propia web** (desplegable "📖 Guía"),
así no puede perderla.
