
import json
import re
import unicodedata
import urllib.request
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
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

# ----------------------------------------------------------------------
# LIGA PROMERICA: el canal depende SOLO del equipo local (regla de localía).
# No se usa ningún dato de transmisión de ESPN para esta liga.
# Inter de San Carlos transmite por FUTV (canal oficial).
# Equipos que no estén en la tabla quedan sin canal ("Por confirmar").
# ----------------------------------------------------------------------

LIGA_PROMERICA = "Liga Promerica de Costa Rica"

LOCALIA_FUTV = [
    "saprissa", "alajuelense", "herediano", "cartagines",
    "guanacasteca", "perez zeledon", "guapiles", "santa ana",
]
LOCALIA_FOX = [
    "san carlos", "sporting", "puntarenas", "escorpiones",
]


def normalizar(texto):
    texto = unicodedata.normalize("NFD", texto or "")
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    return texto.lower().strip()


def canal_por_localia(local):
    nombre = normalizar(local)
    if not nombre:
        return []
    # Inter de San Carlos NO es "San Carlos". Su canal oficial es FUTV.
    if "inter" in nombre:
        return ["FUTV"]
    if any(clave in nombre for clave in LOCALIA_FUTV):
        return ["FUTV"]
    if any(clave in nombre for clave in LOCALIA_FOX):
        return ["FOX"]
    return []


def equipo_local(competidores):
    for c in competidores:
        if c.get("homeAway") == "home":
            return c.get("team", {}).get("displayName", "")
    # Respaldo: el primero de la lista
    if competidores:
        return competidores[0].get("team", {}).get("displayName", "")
    return ""


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

    if liga == LIGA_PROMERICA:
        canales = canal_por_localia(equipo_local(equipos))
    else:
        canales = obtener_canales(evento.get("competitions", []))

    agenda.append({
        "fecha": inicio.strftime("%Y-%m-%d"),
        "hora": inicio.strftime("%H:%M"),
        "zona": "Costa Rica",
        "deporte": deporte,
        "liga": liga,
        "evento": partido,
        "canales": canales,
        "importante": False,
        "fuente": "ESPN"
    })


# ----------------------------------------------------------------------
# LIGA PROMERICA - FUENTE PRINCIPAL: 365Scores
# La página publica los partidos en su HTML con horas en UTC.
# Si 365Scores falla o no cubre un día, se usa ESPN como respaldo.
# ----------------------------------------------------------------------

URL_365 = "https://www.365scores.com/es/football/league/liga-fpd-5056/matches"

EQUIPOS_PROMERICA = [
    ("inter", "Inter de San Carlos"),      # antes que "san carlos"
    ("san carlos", "AD San Carlos"),
    ("cartagines", "Cartaginés"),
    ("herediano", "Herediano"),
    ("saprissa", "Saprissa"),
    ("alajuelense", "Alajuelense"),
    ("perez zeledon", "Pérez Zeledón"),
    ("puntarenas", "Puntarenas FC"),
    ("escorpiones", "Escorpiones Belén"),
    ("sporting", "Sporting San José"),
    ("guanacasteca", "Guanacasteca"),
    ("guapiles", "Santos de Guápiles"),
    ("santa ana", "Santa Ana"),
]

RE_FECHA_365 = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
RE_HORA_365 = re.compile(r"^(\d{1,2}):(\d{2})$")


class ExtractorTexto(HTMLParser):
    """Convierte HTML en una lista de textos visibles."""

    def __init__(self):
        super().__init__()
        self.partes = []
        self.omitir = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.omitir += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.omitir:
            self.omitir -= 1

    def handle_data(self, data):
        if not self.omitir:
            texto = " ".join(data.split())
            if texto:
                self.partes.append(texto)


def nombre_equipo(texto):
    n = normalizar(texto)
    for clave, nombre in EQUIPOS_PROMERICA:
        if clave in n:
            return nombre
    return None


def descargar_html(url):
    solicitud = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept-Language": "es-CR,es;q=0.9",
        }
    )
    with urllib.request.urlopen(solicitud, timeout=25) as respuesta:
        return respuesta.read().decode("utf-8", errors="replace")


def partidos_365scores(html):
    """Devuelve [(inicio_en_hora_CR, local, visitante)] leídos de 365Scores.
    El formato de la página es: fecha dd/mm/aaaa, y luego
    equipo local, hora H:MM (UTC), equipo visitante."""
    extractor = ExtractorTexto()
    extractor.feed(html)
    textos = extractor.partes

    resultado = []
    fecha = None
    for i, texto in enumerate(textos):
        m = RE_FECHA_365.match(texto)
        if m:
            fecha = (int(m.group(3)), int(m.group(2)), int(m.group(1)))
            continue

        m = RE_HORA_365.match(texto)
        if m and fecha and 0 < i < len(textos) - 1:
            local = nombre_equipo(textos[i - 1])
            visitante = nombre_equipo(textos[i + 1])
            if not local or not visitante:
                continue
            try:
                inicio = datetime(
                    fecha[0], fecha[1], fecha[2],
                    int(m.group(1)), int(m.group(2)),
                    tzinfo=timezone.utc
                ).astimezone(ZONA)
            except ValueError:
                continue
            resultado.append((inicio, local, visitante))

    return resultado


def agregar_partido_365(partido, agenda, vistos):
    inicio, local, visitante = partido

    if inicio < AHORA:
        return
    if not HOY <= inicio.date() <= FIN:
        return

    identificador = (LIGA_PROMERICA, local + "|" + visitante)
    if identificador in vistos:
        return
    vistos.add(identificador)

    agenda.append({
        "fecha": inicio.strftime("%Y-%m-%d"),
        "hora": inicio.strftime("%H:%M"),
        "zona": "Costa Rica",
        "deporte": "Fútbol",
        "liga": LIGA_PROMERICA,
        "evento": local + " vs. " + visitante,
        "canales": canal_por_localia(local),
        "importante": False,
        "fuente": "365Scores"
    })


def main():
    agenda = []
    errores = []
    consultas_ok = 0
    vistos = set()

    # Liga Promerica: primero 365Scores
    dias_365 = set()
    try:
        partidos_365 = partidos_365scores(descargar_html(URL_365))
        if partidos_365:
            consultas_ok += 1
            fechas_365 = [p[0].date() for p in partidos_365]
            dia_365 = min(fechas_365)
            while dia_365 <= max(fechas_365):
                dias_365.add(dia_365)
                dia_365 += timedelta(days=1)
            for partido in partidos_365:
                agregar_partido_365(partido, agenda, vistos)
            print("365Scores: " + str(len(partidos_365)) + " partidos leídos")
        else:
            errores.append("365Scores: no se encontraron partidos (se usa ESPN)")
            print("365Scores: sin partidos, se usa ESPN")
    except Exception as error:
        errores.append("365Scores: " + str(error) + " (se usa ESPN)")
        print("365Scores falló: " + str(error) + " (se usa ESPN)")

    dia = HOY
    while dia <= FIN:
        fecha_api = dia.strftime("%Y%m%d")

        for deporte, categoria, codigo, liga in LIGAS:
            # Liga Promerica ya viene de 365Scores en los días que cubre
            if liga == LIGA_PROMERICA and dia in dias_365:
                continue

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
        "version_script": "v5-365scores",
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

    print("Version del script: v5-365scores")
    print("Consultas correctas: " + str(consultas_ok))
    print("Eventos recopilados: " + str(len(agenda)))


if __name__ == "__main__":
    main()
