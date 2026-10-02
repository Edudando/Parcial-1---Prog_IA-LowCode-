import json
import random
from urllib.request import Request, urlopen

# Cada Pokémon tiene pocos parámetros: vida, ataque, defensa, velocidad y sus ataques.
# Cada ataque tiene: poder y precisión (probabilidad de acertar, de 0 a 100).
POKEMONES_RESPALDO = [
    {
        "id": 25,
        "nombre": "Pikachu",
        "vida": 100,
        "ataque": 55,
        "defensa": 40,
        "velocidad": 90,
        "ataques": [
            {"nombre": "Impactrueno", "poder": 40, "precision": 100},
            {"nombre": "Rayo", "poder": 90, "precision": 70},
            {"nombre": "Ataque Rápido", "poder": 30, "precision": 100},
        ],
    },
    {
        "id": 4,
        "nombre": "Charmander",
        "vida": 110,
        "ataque": 52,
        "defensa": 43,
        "velocidad": 65,
        "ataques": [
            {"nombre": "Ascuas", "poder": 40, "precision": 100},
            {"nombre": "Lanzallamas", "poder": 90, "precision": 70},
            {"nombre": "Arañazo", "poder": 30, "precision": 100},
        ],
    },
    {
        "id": 1,
        "nombre": "Bulbasaur",
        "vida": 105,
        "ataque": 49,
        "defensa": 49,
        "velocidad": 45,
        "ataques": [
            {"nombre": "Látigo Cepa", "poder": 45, "precision": 100},
            {"nombre": "Hoja Afilada", "poder": 55, "precision": 95},
            {"nombre": "Placaje", "poder": 40, "precision": 100},
        ],
    },
    {
        "id": 7,
        "nombre": "Squirtle",
        "vida": 100,
        "ataque": 48,
        "defensa": 65,
        "velocidad": 43,
        "ataques": [
            {"nombre": "Pistola Agua", "poder": 40, "precision": 100},
            {"nombre": "Burbuja", "poder": 40, "precision": 100},
            {"nombre": "Placaje", "poder": 40, "precision": 100},
        ],
    },
]
URL_API = "https://pokeapi.co/api/v2"


def solicitar_json(url: str) -> dict:
    """Consulta una URL y devuelve su respuesta JSON."""
    solicitud = Request(url, headers={"User-Agent": "BatallaPokemon/1.0"})
    with urlopen(solicitud, timeout=8) as respuesta:
        return json.load(respuesta)


def obtener_ataques_api(datos_pokemon: dict, ataques_respaldo: list[dict]) -> list[dict]:
    """Obtiene hasta tres movimientos con poder y precisión desde PokeAPI."""
    ataques = []
    for referencia in datos_pokemon.get("moves", [])[:8]:
        try:
            datos_ataque = solicitar_json(referencia["move"]["url"])
        except (OSError, ValueError, KeyError, TypeError):
            continue

        poder = datos_ataque.get("power")
        precision = datos_ataque.get("accuracy")
        if not isinstance(poder, int) or not isinstance(precision, int):
            continue

        nombre = next(
            (item["name"] for item in datos_ataque.get("names", [])
             if item.get("language", {}).get("name") == "es"),
            datos_ataque["name"].replace("-", " ").title(),
        )
        ataques.append({"nombre": nombre, "poder": poder, "precision": precision})
        if len(ataques) == 3:
            break

    return ataques or [dict(ataque) for ataque in ataques_respaldo]


def obtener_catalogo_pokemones() -> list[dict]:
    """Obtiene de PokeAPI el catálogo completo de Pokémon disponibles."""
    datos = solicitar_json(f"{URL_API}/pokemon?limit=10000")
    return datos["results"]


def cargar_pokemon(referencia: dict) -> dict:
    """Carga stats y movimientos de un Pokémon, con respaldo local para starters."""
    respaldo = next(
        (pokemon for pokemon in POKEMONES_RESPALDO
         if pokemon["nombre"].lower() == referencia["name"]),
        None,
    )
    ataques_respaldo = respaldo["ataques"] if respaldo else [
        {"nombre": "Ataque básico", "poder": 40, "precision": 100}
    ]

    try:
        datos = solicitar_json(referencia["url"])
        stats = {item["stat"]["name"]: item["base_stat"] for item in datos["stats"]}
        return {
            "nombre": datos["name"].replace("-", " ").title(),
            "vida": stats["hp"],
            "ataque": stats["attack"],
            "defensa": stats["defense"],
            "velocidad": stats["speed"],
            "ataques": obtener_ataques_api(datos, ataques_respaldo),
        }
    except (OSError, ValueError, KeyError, TypeError) as error:
        if respaldo is None:
            raise RuntimeError(
                f"No se pudo cargar {referencia['name']} desde PokeAPI: {error}"
            ) from error
        print(f"No se pudo cargar {respaldo['nombre']} desde PokeAPI; se usarán datos locales.")
        pokemon = {clave: valor for clave, valor in respaldo.items() if clave != "id"}
        pokemon["ataques"] = [dict(ataque) for ataque in respaldo["ataques"]]
        return pokemon


def calcular_danio(atacante, defensor, ataque):
    """Calcula el daño según el poder, el ataque, la defensa y un factor aleatorio."""
    base = ataque["poder"] * atacante["ataque"] / defensor["defensa"] / 2
    return max(1, int(base * random.uniform(0.85, 1.0)))


def atacar(atacante, defensor, ataque):
    # Primero se comprueba si el ataque acierta; si falla, no causa daño.
    print(f"¡{atacante['nombre']} usó {ataque['nombre']}!")
    if random.randint(1, 100) > ataque["precision"]:
        print("¡Pero falló!")
        return
    # Si acierta, se calcula el daño y se evita que la vida quede por debajo de cero.
    danio = calcular_danio(atacante, defensor, ataque)
    defensor["vida"] = max(0, defensor["vida"] - danio)
    print(f"{defensor['nombre']} recibió {danio} de daño.")


def mostrar_vida(jugador, rival):
    # Muestra primero la vida del rival y luego la del jugador.
    print()
    print(f"{rival['nombre']} (rival): {rival['vida']} de vida")
    print(f"{jugador['nombre']} (vos): {jugador['vida']} de vida")
    print()


def pedir_numero(mensaje, minimo, maximo):
    """Repite la pregunta hasta que el usuario escriba un número válido."""
    while True:
        texto = input(mensaje)
        if texto.isdigit() and minimo <= int(texto) <= maximo:
            return int(texto)
        print(f"Escribí un número del {minimo} al {maximo}.")


def elegir_ataque(pokemon):
    # Presenta los ataques disponibles y devuelve el que eligió el jugador.
    print(f"¿Qué ataque usa {pokemon['nombre']}?")
    for i, ataque in enumerate(pokemon["ataques"], start=1):
        print(f"  {i}) {ataque['nombre']} (poder {ataque['poder']}, precisión {ataque['precision']}%)")
    opcion = pedir_numero("> ", 1, len(pokemon["ataques"]))
    return pokemon["ataques"][opcion - 1]


def elegir_equipo(opciones: list[dict]) -> list[dict]:
    """Muestra las opciones sorteadas y permite elegir tres Pokémon distintos."""
    print("\nPokémon disponibles para este torneo:")
    for numero, pokemon in enumerate(opciones, start=1):
        nombre = pokemon.get("name", pokemon.get("nombre", "Pokémon"))
        identificador = pokemon.get("url", "").rstrip("/").rsplit("/", 1)[-1]
        print(f"  {numero}) {nombre.replace('-', ' ').title()} (ID {identificador})")

    equipo = []
    while len(equipo) < 3:
        numero = pedir_numero(f"Elegí tu Pokémon {len(equipo) + 1}/3 > ", 1, len(opciones))
        pokemon = opciones[numero - 1]
        if pokemon in equipo:
            print("Ese Pokémon ya está en tu equipo. Elegí otro.")
            continue
        equipo.append(pokemon)
    return equipo


def jugar_ronda(jugador: dict, catalogo: list[dict], equipo: list[dict], numero: int) -> bool:
    """Juega un combate con un integrante del equipo y devuelve si ganó."""
    print(f"\n=== RONDA {numero} DE 3 ===")
    posibles_rivales = [
        pokemon for pokemon in catalogo
        if pokemon.get("name", pokemon.get("nombre", "")).lower()
        not in {integrante.get("name", integrante.get("nombre", "")).lower()
                for integrante in equipo}
    ]
    referencia_rival = random.choice(posibles_rivales)
    rival = cargar_pokemon(referencia_rival)
    print(f"\n¡Adelante, {jugador['nombre']}! El rival eligió a {rival['nombre']}.")

    turno = 1
    while jugador["vida"] > 0 and rival["vida"] > 0:
        # En cada turno el jugador elige un ataque y la computadora escoge uno al azar.
        print(f"\n--- Turno {turno} ---")
        mostrar_vida(jugador, rival)
        ataque_jugador = elegir_ataque(jugador)
        ataque_rival = random.choice(rival["ataques"])  # la computadora elige al azar
        print()

        # El Pokémon con mayor velocidad ataca primero; en empate, empieza el jugador.
        if jugador["velocidad"] >= rival["velocidad"]:
            orden = [(jugador, rival, ataque_jugador), (rival, jugador, ataque_rival)]
        else:
            orden = [(rival, jugador, ataque_rival), (jugador, rival, ataque_jugador)]

        # Se ejecutan los ataques en orden y el turno termina si alguien queda sin vida.
        for atacante, defensor, ataque in orden:
            atacar(atacante, defensor, ataque)
            if defensor["vida"] == 0:
                print(f"¡{defensor['nombre']} se debilitó!")
                break
        turno += 1

    print()
    if jugador["vida"] > 0:
        print("¡GANASTE!")
        return True
    else:
        print("Perdiste...")
        return False


def jugar_torneo(catalogo: list[dict]) -> None:
    """Juega tres rondas y anuncia el resultado por cantidad de victorias."""
    if len(catalogo) < 4:
        print("Se necesitan al menos cuatro Pokémon disponibles para armar el equipo y elegir rivales.")
        return

    opciones = random.sample(catalogo, min(20, len(catalogo)))
    equipo_referencias = elegir_equipo(opciones)
    equipo = [cargar_pokemon(pokemon) for pokemon in equipo_referencias]
    print("\nTu equipo:", ", ".join(pokemon["nombre"] for pokemon in equipo))

    victorias = 0
    for numero in range(1, 4):
        if jugar_ronda(equipo[numero - 1], catalogo, equipo_referencias, numero):
            victorias += 1

    print(f"\nResultado final: {victorias} de 3 rondas ganadas.")
    if victorias >= 2:
        print("¡Ganaste el torneo!")
    else:
        print("El rival ganó el torneo.")


def main() -> None:
    """Carga el catálogo y ejecuta torneos hasta que el usuario salga."""
    print("Consultando catálogo de PokeAPI...")
    try:
        catalogo = obtener_catalogo_pokemones()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"No se pudo consultar PokeAPI: {error}")
        print("Se habilitan Pikachu y Charmander como opciones locales.")
        catalogo = [
            {"name": pokemon["nombre"].lower(),
             "url": f"{URL_API}/pokemon/{pokemon['id']}/"}
            for pokemon in POKEMONES_RESPALDO
        ]

    while True:
        try:
            jugar_torneo(catalogo)
        except RuntimeError as error:
            print(error)
        if input("\n¿Jugar otra vez? (s/n): ").strip().lower() != "s":
            print("¡Gracias por jugar!")
            break


if __name__ == "__main__":
    main()
