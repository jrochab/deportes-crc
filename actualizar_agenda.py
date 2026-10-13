
import json
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ZONA = ZoneInfo("America/Costa_Rica")
AHORA = datetime.now(ZONA)
HOY = AHORA.date()
FIN = HOY + timedelta(days=6)

LIGAS = [
    ("Fútbol", "soccer", "eng.1", "Premier League"),
    ("Fútbol", "soccer", "esp.1", "LaLiga"),
    ("Fútbol", "soccer", "ita.1", "Serie A"),
    ("Fútbol", "soccer", "ger.1", "Bundesliga"),
    ("Fútbol", "soccer", "fra.1", "Ligue 1"),
    ("Béisbol", "baseball", "mlb", "MLB"),
    ("Baloncesto", "basketball", "nba", "NBA"),
    ("Automovilismo", "racing", "f1", "Fórmula 1"),
    ("Tenis", "tennis", "atp", "Tenis ATP"),
    ("Tenis", "tennis", "wta", "Tenis WTA"),
    ("Fútbol", "soccer", "crc.1", "Liga Promerica de Costa Rica"),
]


def consultar(url):
    solicitud = urllib.request.Request(
        url,
        headers={"User-Agent": "DEPORTES-CRC/1.0"}
    )
    with urllib.request.urlopen(solicitud, timeout=25) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def convertir_hora(fecha):
    # ESPN a veces entrega "2026-10-14T09:00Z" (sin segundos).
    fecha = fecha.replace("Z", "+00:00")
    try:
        valor = datetime.fromisoformat(fecha)
    except ValueError:
        valor = datetime.strptime(fecha, "%Y-%m-%dT%H:%M%z")
    return valor.astimezone(ZONA)


def obtener_canales(competencias):
    """Recibe una lista de 'competitions' y devuelve los canales."""
    canales = set()
    for competencia in competencias:
        for emision in competencia.get("broadcasts", []) or []:
            for nombre in emision.get("names", []) or []:
                canales.add(nombre)
            # Formato alterno que usa ESPN en algunos deportes
            media = emision.get("media", {})
            if isinstance(media, dict) and media.get("shortName"):
                canales.add(media["shortName"])
    return sorted(canales)


# ----------------------------------------------------------------------
# TENIS
# En el scoreboard de tenis, cada "event" es un TORNEO (no un partido).
# Los partidos están anidados en evento["groupings"][i]["competitions"],
# y los jugadores están en competitor["athlete"] (individuales) o
# competitor["roster"] (dobles), no en competitor["team"].
# La fecha del torneo es la de inicio, por eso hay que usar la fecha
# de cada partido.
# ----------------------------------------------------------------------

def nombre_competidor(competidor):
    atleta = competidor.get("athlete") or {}
    nombre = atleta.get("displayName") or atleta.get("shortName")
    if nombre:
        return nombre

    pareja = competidor.get("roster") or {}
    nombre = pareja.get("displayName") or pareja.get("shortDisplayName")
    if nombre:
        return nombre

    # Respaldo por si ESPN usa la estructura de equipos
    equipo = competidor.get("team") or {}
    return equipo.get("displayName", "")


def partidos_de_tenis(evento):
    """Devuelve una lista de (grupo, competencia) de un torneo."""
    resultado = []

    for grupo in evento.get("groupings", []) or []:
        nombre_grupo = (grupo.get("grouping") or {}).get("displayName", "")
        for competencia in grupo.get("competitions", []) or []:
            resultado.append((nombre_grupo, competencia))

    # Respaldo: algunos torneos traen los partidos directo en "competitions"
    if not resultado:
        for competencia in evento.get("competitions", []) or []:
            resultado.append(("", competencia))

    return resultado


def procesar_tenis(evento, deporte, liga, agenda, vistos):
    torneo = evento.get("name") or evento.get("shortName") or "Torneo"

    for grupo, competencia in partidos_de_tenis(evento):
        try:
            fecha = (
                competencia.get("date")
                or competencia.get("startDate")
                or competencia.get("startTime")
            )
            if not fecha:
                continue

            inicio = convertir_hora(fecha)

            if inicio < AHORA:
                continue

            if not HOY <= inicio.date() <= FIN:
                continue

            # Omitir partidos ya finalizados
            estado = (competencia.get("status") or {}).get("type", {})
            if estado.get("state") == "post" or estado.get("completed"):
                continue

            nombres = [
                nombre_competidor(c)
                for c in competencia.get("competitors", []) or []
            ]
            nombres = [n for n in nombres if n]

            # Evitar partidos sin rivales definidos aún (TBD / por definir)
            if len(nombres) < 2:
                continue

            identificador = (
                liga,
                competencia.get("id") or (torneo, grupo, " vs. ".join(nombres)),
            )
            if identificador in vistos:
                continue
            vistos.add(identificador)

            partido = " vs. ".join(nombres)

            agenda.append({
                "fecha": inicio.strftime("%Y-%m-%d"),
                "hora": inicio.strftime("%H:%M"),
                "zona": "Costa Rica",
                "deporte": deporte,
                "liga": liga,
                "torneo": torneo,
                "categoria": grupo,
                "evento": partido,
                "canales": obtener_canales([competencia]),
                "importante": False,
                "fuente": "ESPN"
            })

        except (KeyError, TypeError, ValueError, AttributeError):
            continue


# ----------------------------------------------------------------------
# Resto de deportes (estructura de equipos)
# ----------------------------------------------------------------------

def procesar_evento_general(evento, deporte, liga, agenda, vistos):
    inicio = convertir_hora(evento["date"])

    if inicio < AHORA:
        return

    if not HOY <= inicio.date() <= FIN:
        return

    identificador = (
        liga,
        evento.get("id", evento.get("name", "")),
    )

    if identificador in vistos:
        return
    vistos.add(identificador)

    competencia = evento.get("competitions", [{}])[0]
    equipos = competencia.get("competitors", [])

    nombres = [
        equipo.get("team", {}).get("displayName", "")
        for equipo in equipos
    ]
    nombres = [n for n in nombres if n]

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
        "canales": obtener_canales(evento.get("competitions", [])),
        "importante": False,
        "fuente": "ESPN"
    })


def main():
    agenda = []
    errores = []
    consultas_ok = 0
    vistos = set()

    dia = HOY
    while dia <= FIN:
        fecha_api = dia.strftime("%Y%m%d")

        for deporte, categoria, codigo, liga in LIGAS:
            url = (
                "https://site.api.espn.com/apis/site/v2/sports/"
                + categoria + "/" + codigo
                + "/scoreboard?dates=" + fecha_api
            )

            try:
                datos = consultar(url)
                consultas_ok += 1

                for evento in datos.get("events", []):
                    try:
                        if categoria == "tennis":
                            procesar_tenis(evento, deporte, liga, agenda, vistos)
                        else:
                            procesar_evento_general(
                                evento, deporte, liga, agenda, vistos
                            )
                    except (KeyError, TypeError, ValueError):
                        continue

            except Exception as error:
                mensaje = liga + " (" + fecha_api + "): " + str(error)
                errores.append(mensaje)
                print("Consulta fallida: " + mensaje)

        dia += timedelta(days=1)

    if consultas_ok == 0:
        raise RuntimeError(
            "Todas las consultas fallaron. No se reemplazó agenda.json."
        )

    agenda.sort(key=lambda e: (e["fecha"], e["hora"], e["evento"]))

    resultado = {
        "version_script": "tenis-v2",
        "actualizado": datetime.now(ZONA).isoformat(),
        "zona_horaria": "America/Costa_Rica",
        "periodo_hasta": FIN.isoformat(),
        "cantidad_eventos": len(agenda),
        "eventos": agenda,
        "consultas_correctas": consultas_ok,
        "fuentes_con_error": errores
    }

    with open("agenda.json", "w", encoding="utf-8") as archivo:
        json.dump(resultado, archivo, ensure_ascii=False, indent=2)

    print("Version del script: tenis-v2")
    print("Consultas correctas: " + str(consultas_ok))
    print("Eventos recopilados: " + str(len(agenda)))


if __name__ == "__main__":
    main()
