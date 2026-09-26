"""
Genera / actualiza el manifiesto de reproducción sincronizada de "Bodega-Sound".

Qué hace, paso a paso:
1. Busca en archive.org todas las sesiones con la etiqueta (subject) "Bodega-Sound".
2. Para cada una, obtiene el enlace directo al MP3 y su duración exacta
   (archive.org la calcula solo, no hace falta descargar el audio).
3. Si hay sesiones nuevas respecto al manifiesto actual, o si la ronda de
   reproducción en curso ya ha terminado, genera un nuevo orden aleatorio
   con TODAS las sesiones conocidas y reinicia el cronómetro de sincronización.
4. Sube el resultado (playlists/bodega-sound.json) al repositorio de GitHub,
   que es el archivo que lee el reproductor para saber qué suena y en qué segundo.

Se ejecuta automáticamente una vez al día mediante GitHub Actions
(ver el archivo .github/workflows/bodega-sound.yml). No necesita ningún
token configurado a mano: usa el que GitHub Actions proporciona solo.
"""

import base64
import json
import os
import random
import time
import urllib.request

SUBJECT = "Bodega-Sound"
REPO = "portalarioja-dev/syncstream"  # <-- cambia aquí si usas otro repositorio
RUTA_MANIFIESTO = "playlists/bodega-sound.json"
RAMA = "main"
API_ARCHIVE_BUSQUEDA = (
    "https://archive.org/advancedsearch.php"
    f"?q=subject%3A%22{SUBJECT}%22&fl[]=identifier&fl[]=title"
    "&rows=1000&output=json"
)


def obtener_sesiones():
    """Devuelve un diccionario {identificador: datos_de_la_sesion} con todo
    lo que hay ahora mismo en archive.org bajo la etiqueta Bodega-Sound."""
    with urllib.request.urlopen(API_ARCHIVE_BUSQUEDA) as r:
        data = json.load(r)

    sesiones = {}
    for doc in data["response"]["docs"]:
        identificador = doc["identifier"]
        with urllib.request.urlopen(f"https://archive.org/metadata/{identificador}") as r2:
            meta = json.load(r2)

        mp3 = next(
            (f for f in meta.get("files", []) if f["name"].lower().endswith(".mp3")),
            None,
        )
        if not mp3 or "length" not in mp3:
            # Archive.org aún está procesando el archivo (duración no lista).
            # Se recogerá automáticamente al día siguiente.
            continue

        sesiones[identificador] = {
            "identificador": identificador,
            "titulo": doc.get("title", identificador),
            "url": f"https://archive.org/download/{identificador}/{mp3['name']}",
            "duracion": float(mp3["length"]),
        }
    return sesiones


def leer_manifiesto_actual():
    """Lee el manifiesto que hay publicado ahora mismo en GitHub, si existe."""
    url = f"https://raw.githubusercontent.com/{REPO}/{RAMA}/{RUTA_MANIFIESTO}?_={int(time.time())}"
    try:
        with urllib.request.urlopen(url) as r:
            return json.load(r)
    except Exception:
        return None


def ronda_completada(manifiesto):
    """True si ya ha pasado tiempo suficiente como para que la ronda actual
    (todas las sesiones en su orden actual) haya terminado de sonar entera."""
    if not manifiesto or not manifiesto.get("orden"):
        return True
    duracion_total = sum(t["duracion"] for t in manifiesto["orden"])
    transcurrido = time.time() - manifiesto["epoch_inicio"]
    return transcurrido >= duracion_total


def subir_a_github(contenido):
    token = os.environ["GITHUB_TOKEN"]
    api_url = f"https://api.github.com/repos/{REPO}/contents/{RUTA_MANIFIESTO}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "bodega-sound-script",
    }

    # Hace falta el "sha" del archivo actual para poder sobrescribirlo.
    sha = None
    peticion = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(peticion) as r:
            sha = json.load(r)["sha"]
    except Exception:
        pass  # el archivo todavía no existe -> se creará por primera vez

    contenido_b64 = base64.b64encode(
        json.dumps(contenido, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("utf-8")

    payload = {
        "message": "Actualiza playlist Bodega-Sound",
        "content": contenido_b64,
        "branch": RAMA,
    }
    if sha:
        payload["sha"] = sha

    peticion = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="PUT",
    )
    with urllib.request.urlopen(peticion) as r:
        r.read()


def main():
    sesiones = obtener_sesiones()
    if not sesiones:
        print("No se encontró ninguna sesión con la etiqueta Bodega-Sound todavía.")
        return

    manifiesto_actual = leer_manifiesto_actual()
    ids_conocidos = {t["identificador"] for t in (manifiesto_actual or {}).get("orden", [])}
    hay_sesiones_nuevas = bool(set(sesiones) - ids_conocidos)

    if hay_sesiones_nuevas or ronda_completada(manifiesto_actual):
        orden = list(sesiones.values())
        random.shuffle(orden)
        nuevo_manifiesto = {
            "orden": orden,
            "epoch_inicio": time.time(),
        }
        subir_a_github(nuevo_manifiesto)
        print(f"Nueva ronda generada con {len(orden)} sesiones.")
    else:
        print("Todavía dentro de la ronda actual, no hace falta actualizar nada.")


if __name__ == "__main__":
    main()
