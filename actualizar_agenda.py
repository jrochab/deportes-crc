
import json
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Costa_Rica")
HOY = datetime.now(ZONA).date()
FIN = HOY + timedelta(days=7)

LIGAS = [
    ("Fútbol", "soccer", "eng.1", "Premier League"),
    ("Fútbol", "soccer", "esp.1", "LaLiga"),
    ("Fútbol", "soccer", "ita.1", "Serie A"),
    ("Fútbol", "soccer", "ger.1", "Bundesliga"),
    ("Fútbol", "soccer", "fra.1", "Ligue 1"),
    ("Béisbol", "baseball", "mlb", "MLB"),
    ("Baloncesto", "basketball", "nba", "NBA"),
]

def consultar(url):
    solicitud = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 DEPORTES-CRC"}
    )
    with urllib.request.urlopen(solicitud, timeout=20) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))

def convertir_hora(fecha):
    valor = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
    return valor.astimezone(ZONA)

def obtener_canales(evento):
    canales = set()
    for competencia in evento.get("competitions", []):
        for emision in competencia.get("broadcasts", []):
            for nombre in emision.get("names", []):
                canales.add(nombre)
    return sorted(canales)

agenda = []
errores = []

desde = HOY.strftime("%Y%m%d")
hasta = FIN.strftime("%Y%m%d")

for deporte, categoria, codigo, liga in LIGAS:
    url = (
        "https://site.api.espn.com/apis/site/v2/sports/"
        + categoria + "/" + codigo
        + "/scoreboard?dates=" + desde + "-" + hasta
    )

    try:
        datos = consultar(url)

        for evento in datos.get("events", []):
            try:
                inicio = convertir_hora(evento["date"])

                if not HOY <= inicio.date() <= FIN:
                    continue

                competencia = evento.get("competitions", [{}])[0]
                equipos = competencia.get("competitors", [])
                nombres = [
                    equipo.get("team", {}).get("displayName", "")
                    for equipo in equipos
                ]
                nombres = [nombre for nombre in nombres if nombre]

                partido = " vs. ".join(nombres)
                if not partido:
                    partido = evento.get("name", "Evento deportivo")

                agenda.append({
                    "fecha": inicio.strftime("%Y-%m-%d"),
                    "hora": inicio.strftime("%H:%M"),
                    "zona": "Costa Rica",
                    "deporte": deporte,
                    "liga": liga,
                    "evento": partido,
                    "canales": obtener_canales(evento),
                    "importante": False,
                    "fuente": "ESPN"
                })

            except (KeyError, TypeError, ValueError):
                continue

    except Exception as error:
        errores.append(liga + ": " + str(error))
        print("No se pudo consultar " + liga + ": " + str(error))

agenda.sort(key=lambda evento: (evento["fecha"], evento["hora"]))

resultado = {
    "actualizado": datetime.now(ZONA).isoformat(),
    "zona_horaria": "America/Costa_Rica",
    "periodo_hasta": FIN.isoformat(),
    "cantidad_eventos": len(agenda),
    "eventos": agenda,
    "fuentes_con_error": errores
}

with open("agenda.json", "w", encoding="utf-8") as archivo:
    json.dump(resultado, archivo, ensure_ascii=False, indent=2)

print("Agenda generada: " + str(len(agenda)) + " eventos.")
