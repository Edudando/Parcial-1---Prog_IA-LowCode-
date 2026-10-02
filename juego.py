"""
juego.py — Poké Batalla de ESCRITORIO con pygame (sin navegador).

Usa el mismo motor que la web: public/pokeapi.py (datos en vivo de PokeAPI) y public/battle.py.

Requisitos: Python 3.13 y pygame
    py -3.13 -m pip install pygame        (Windows)
    python3.13 -m pip install pygame      (Linux / macOS)
Ejecutar:
    py -3.13 juego.py

Controles: mouse · 1-4 elegir ataque · Tab cambiar pestaña · Espacio/Enter adelantar texto
           M silenciar · F11 pantalla completa · Esc volver / salir
(Si en vez de pygame tenés pygame-ce, los sprites se ven animados.)
"""
import asyncio
import copy
import hashlib
import io
import math
import os
import random
import sys
import threading
import urllib.request

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(RAIZ, "public"))

import pygame               # noqa: E402

import pokeapi              # noqa: E402
from battle import Batalla  # noqa: E402
from main import resolver_id  # noqa: E402

ANCHO, ALTO = 960, 640
FPS = 60
TAM_EQUIPO = 3
DESTACADOS = [25, 6, 9, 3, 94, 143, 130, 149, 448, 282, 445, 658, 384, 150, 887, 1000]
SPR = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon"
CACHE_MEDIOS = os.path.join(RAIZ, ".cache_pokeapi", "medios")
ANIMADO = hasattr(pygame.image, "load_animation")   # solo pygame-ce

# ---------------------------------------------------------------- colores
C = {
    "fondo": (241, 244, 249), "panel": (255, 255, 255), "texto": (28, 34, 48), "suave": (91, 100, 120),
    "borde": (214, 220, 232), "acento": (227, 53, 13), "azul": (42, 117, 187), "log": (31, 38, 51),
    "log_txt": (243, 245, 249), "amarillo": (242, 201, 76), "verde": (62, 196, 109), "rojo": (235, 87, 87),
    "eficaz": (126, 226, 160), "poco": (179, 188, 205), "debil": (255, 138, 128), "gris": (217, 221, 230),
}
TIPO_COLOR = {
    "normal": (159, 161, 159), "fire": (230, 40, 41), "water": (41, 128, 239), "electric": (217, 168, 0),
    "grass": (63, 161, 41), "ice": (61, 206, 243), "fighting": (255, 128, 0), "poison": (145, 65, 203),
    "ground": (145, 81, 33), "flying": (129, 185, 239), "psychic": (239, 65, 121), "bug": (145, 161, 25),
    "rock": (175, 169, 129), "ghost": (112, 65, 112), "dragon": (80, 96, 225), "dark": (80, 65, 63),
    "steel": (96, 161, 184), "fairy": (239, 112, 239), "stellar": (64, 181, 165), "typeless": (104, 160, 144),
}
ESTADO_COLOR = {"PAR": (217, 168, 0), "QUE": (230, 40, 41), "ENV": (145, 65, 203),
                "DOR": (122, 127, 140), "CON": (61, 206, 243)}

# ---------------------------------------------------------------- asyncio en segundo plano
# La red (PokeAPI, sprites, gritos) corre en otro hilo para que la ventana nunca se congele.
_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True, name="asyncio").start()


def en_segundo_plano(corrutina):
    """Devuelve un concurrent.futures.Future: se consulta con .done() en cada frame."""
    return asyncio.run_coroutine_threadsafe(corrutina, _loop)


def _bajar_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": "poke-batalla/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


class Medios:
    """Descarga y guarda en disco sprites y gritos; los convierte a Surface/Sound en el hilo principal."""

    def __init__(self):
        self.datos = {}        # url -> bytes (b"" si falló)
        self.pedidos = set()
        self.imagenes = {}
        self.sonidos = {}
        os.makedirs(CACHE_MEDIOS, exist_ok=True)

    @staticmethod
    def _ruta(url):
        ext = os.path.splitext(url)[1][:5] or ".bin"
        return os.path.join(CACHE_MEDIOS, hashlib.sha1(url.encode()).hexdigest()[:20] + ext)

    def pedir(self, url):
        if url and url not in self.pedidos:
            self.pedidos.add(url)
            en_segundo_plano(self._bajar(url))

    async def _bajar(self, url):
        ruta = self._ruta(url)
        try:
            if os.path.exists(ruta):
                with open(ruta, "rb") as f:
                    self.datos[url] = f.read()
                return
            datos = await asyncio.get_running_loop().run_in_executor(None, _bajar_bytes, url)
            with open(ruta, "wb") as f:
                f.write(datos)
            self.datos[url] = datos
        except Exception:
            self.datos[url] = b""

    def listo(self, url):
        return url in self.datos

    def imagen(self, url, caja, espejo=False):
        """Lista de (Surface, ms) recortada al contenido y escalada para entrar en caja=(ancho, alto)."""
        if not url:
            return None
        clave = (url, caja, espejo)
        if clave in self.imagenes:
            return self.imagenes[clave]
        datos = self.datos.get(url)
        if datos is None:
            self.pedir(url)
            return None
        cuadros = None
        if datos:
            try:
                if url.endswith(".gif") and ANIMADO:
                    cuadros = pygame.image.load_animation(io.BytesIO(datos), "a.gif")
                else:
                    cuadros = [(pygame.image.load(io.BytesIO(datos), "a" + os.path.splitext(url)[1]), 0)]
                cuadros = _preparar_cuadros(cuadros, caja, espejo)
            except Exception:
                cuadros = None
        self.imagenes[clave] = cuadros
        return cuadros

    def sonido(self, url):
        if not url or not pygame.mixer.get_init():
            return None
        if url not in self.sonidos:
            datos = self.datos.get(url)
            if datos is None:
                self.pedir(url)
                return None
            try:
                self.sonidos[url] = pygame.mixer.Sound(io.BytesIO(datos)) if datos else None
            except Exception:
                self.sonidos[url] = None
        return self.sonidos[url]


def _preparar_cuadros(cuadros, caja, espejo):
    cuadros = [(s.convert_alpha(), ms or 100) for s, ms in cuadros]
    zona = cuadros[0][0].get_bounding_rect()
    for s, _ in cuadros[1:]:
        zona.union_ip(s.get_bounding_rect())
    if zona.w == 0 or zona.h == 0:
        return None
    escala = min(caja[0] / zona.w, caja[1] / zona.h)
    if escala >= 1:
        escala = max(1, int(escala))   # entero: el pixel art queda nítido
    tam = (max(1, int(zona.w * escala)), max(1, int(zona.h * escala)))
    salida = []
    for s, ms in cuadros:
        s = pygame.transform.scale(s.subsurface(zona), tam)
        if espejo:
            s = pygame.transform.flip(s, True, False)
        salida.append((s, ms))
    return salida


def cuadro_actual(cuadros):
    if len(cuadros) == 1:
        return cuadros[0][0]
    total = sum(ms for _, ms in cuadros)
    t = pygame.time.get_ticks() % total
    for s, ms in cuadros:
        if t < ms:
            return s
        t -= ms
    return cuadros[-1][0]


# ---------------------------------------------------------------- dibujo
class Fuentes:
    def __init__(self):
        self.cache = {}

    def __call__(self, tam, negrita=False, italica=False):
        clave = (tam, negrita, italica)
        if clave not in self.cache:
            f = pygame.font.Font(None, tam)
            f.set_bold(negrita)
            f.set_italic(italica)
            self.cache[clave] = f
        return self.cache[clave]


F = None  # se crea al iniciar pygame


def texto(sup, txt, pos, tam=24, color=C["texto"], negrita=False, italica=False, ancla="topleft", ancho_max=None):
    fuente = F(tam, negrita, italica)
    if ancho_max:
        while txt and fuente.size(txt)[0] > ancho_max:
            txt = txt[:-2] + "."
    img = fuente.render(txt, True, color)
    rect = img.get_rect(**{ancla: pos})
    sup.blit(img, rect)
    return rect


def envolver(txt, fuente, ancho):
    palabras, lineas, actual = txt.split(" "), [], ""
    for p in palabras:
        prueba = (actual + " " + p).strip()
        if fuente.size(prueba)[0] <= ancho:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = p
    if actual:
        lineas.append(actual)
    return lineas or [""]


def aclarar(color, k=0.15):
    return tuple(min(255, int(c + (255 - c) * k)) for c in color)


def pastilla(sup, txt, pos, fondo, tam=17):
    fuente = F(tam, True)
    img = fuente.render(txt.upper(), True, (255, 255, 255))
    r = pygame.Rect(pos, (img.get_width() + 14, img.get_height() + 6))
    pygame.draw.rect(sup, fondo, r, border_radius=r.h // 2)
    sup.blit(img, img.get_rect(center=r.center))
    return r


def tipos_pastillas(sup, tipos, x, y, centrar_en=None, tam=17, ancho_max=None):
    """tipos: claves en inglés o dicts {clave, nombre}. Si no entran en ancho_max, van una debajo de otra."""
    from battle import TIPOS_ES
    items = [(t["clave"], t["nombre"]) if isinstance(t, dict) else (t, TIPOS_ES.get(t, t)) for t in tipos]
    anchos = [F(tam, True).size(n.upper())[0] + 14 for _, n in items]
    filas = [list(zip(items, anchos))]
    if ancho_max and sum(anchos) + 4 * (len(anchos) - 1) > ancho_max:
        filas = [[par] for par in zip(items, anchos)]
    alto = F(tam, True).get_height() + 7
    for n, fila in enumerate(filas):
        xi = x
        if centrar_en is not None:
            xi = centrar_en - (sum(w for _, w in fila) + 4 * (len(fila) - 1)) // 2
        for (clave, nombre), w in fila:
            pastilla(sup, nombre, (xi, y + n * alto), TIPO_COLOR.get(clave, (120, 120, 120)), tam)
            xi += w + 4


def barra_ps(sup, rect, ps, ps_max):
    pct = max(0.0, min(1.0, ps / ps_max)) if ps_max else 0
    color = C["verde"] if pct > .5 else C["amarillo"] if pct > .2 else C["rojo"]
    pygame.draw.rect(sup, C["gris"], rect, border_radius=rect.h // 2)
    if pct > 0:
        pygame.draw.rect(sup, color, (rect.x, rect.y, max(rect.h, int(rect.w * pct)), rect.h), border_radius=rect.h // 2)


def pokebola(sup, centro, radio, angulo=0):
    s = pygame.Surface((radio * 2 + 4, radio * 2 + 4), pygame.SRCALPHA)
    c = (radio + 2, radio + 2)
    pygame.draw.circle(s, (255, 255, 255), c, radio)
    pygame.draw.circle(s, C["acento"], c, radio, draw_top_left=True, draw_top_right=True)
    pygame.draw.rect(s, (34, 34, 34), (2, c[1] - max(2, radio // 8), radio * 2, max(3, radio // 4)))
    pygame.draw.circle(s, (34, 34, 34), c, radio, max(2, radio // 8))
    pygame.draw.circle(s, (255, 255, 255), c, max(3, radio // 3))
    pygame.draw.circle(s, (34, 34, 34), c, max(3, radio // 3), max(2, radio // 10))
    if angulo:
        s = pygame.transform.rotate(s, angulo)
    sup.blit(s, s.get_rect(center=centro))


class Boton:
    def __init__(self, rect, etiqueta, accion, color=None, color_txt=(255, 255, 255), tam=26):
        self.rect = pygame.Rect(rect)
        self.etiqueta = etiqueta
        self.accion = accion
        self.color = color or C["acento"]
        self.color_txt = color_txt
        self.tam = tam
        self.habilitado = True

    def dibujar(self, sup):
        hover = self.habilitado and self.rect.collidepoint(pygame.mouse.get_pos())
        color = aclarar(self.color, .12) if hover else self.color
        if not self.habilitado:
            color = aclarar(self.color, .55)
        pygame.draw.rect(sup, color, self.rect, border_radius=10)
        if self.color == C["panel"]:
            pygame.draw.rect(sup, C["borde"], self.rect, 2, border_radius=10)
        texto(sup, self.etiqueta, self.rect.center, self.tam, self.color_txt, True, ancla="center")

    def clic(self, pos):
        if self.habilitado and self.rect.collidepoint(pos):
            self.accion()
            return True
        return False


def es_clic(ev):
    return ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1


# ---------------------------------------------------------------- escena: selección
def url_frente(p):
    return f"{SPR}/{p['id']}.png"


def url_espalda(p):
    return f"{SPR}/back/{p['id']}.png"


class Seleccion:
    COLS, ANCHO_C, ALTO_C, GAP = 8, 108, 146, 8
    ZONA = pygame.Rect(20, 214, 920, 300)

    def __init__(self, app):
        self.app = app
        self.fichas = {}           # id -> resumen de pokeapi
        self.orden = []            # ids en la grilla
        self.pendientes = {}       # id -> Future
        self.auto_elegir = set()
        self.seleccion = []
        self.busqueda = ""
        self.especies = []
        self.msg, self.msg_error = "Cargando Pokémon desde PokeAPI…", False
        self.fut_busqueda = None
        self.fut_batalla = None
        self.fila = 0
        self.fut_especies = en_segundo_plano(pokeapi.lista_especies())
        for i in DESTACADOS:
            self._cargar(i)
        self.b_azar = Boton((250, 574, 200, 48), "Equipo al azar", self.azar, C["panel"], C["texto"])
        self.b_pelear = Boton((510, 574, 200, 48), "¡A pelear!", self.pelear)
        self.b_sonido = Boton((880, 18, 62, 36), "", app.alternar_sonido, C["panel"], C["texto"], 20)
        pygame.key.start_text_input()

    # ---- datos
    def _cargar(self, ident, elegir=False):
        if ident not in self.orden:
            self.orden.append(ident)
        if elegir:
            self.auto_elegir.add(ident)
        if ident not in self.fichas and ident not in self.pendientes:
            self.pendientes[ident] = en_segundo_plano(pokeapi.pokemon(ident))
        elif elegir:
            self._elegir(ident)

    def _elegir(self, ident):
        self.auto_elegir.discard(ident)
        if ident not in self.seleccion and len(self.seleccion) < TAM_EQUIPO:
            self.seleccion.append(ident)

    def sugerencias(self):
        t = self.busqueda.strip().lower().replace(" ", "-")
        if not t or not self.especies:
            return []
        if t.isdigit():
            return [e for e in self.especies if str(e[0]).startswith(t)][:6]
        empieza = [e for e in self.especies if e[1].startswith(t)]
        contiene = [e for e in self.especies if t in e[1] and e not in empieza]
        return (empieza + contiene)[:6]

    def buscar(self, txt=None):
        txt = (txt or self.busqueda).strip()
        if not txt or self.fut_busqueda:
            return
        self.msg, self.msg_error = "Buscando en PokeAPI…", False

        async def tarea():
            return await resolver_id(txt)
        self.fut_busqueda = en_segundo_plano(tarea())

    def azar(self):
        self.seleccion = []
        for i in random.sample(range(1, pokeapi.MAX_ID + 1), TAM_EQUIPO):
            if i in self.orden:
                self.orden.remove(i)
            self.orden.insert(0, i)
            self._cargar(i, elegir=True)
        self.fila = 0

    def pelear(self):
        if len(self.seleccion) != TAM_EQUIPO or self.fut_batalla:
            return
        ids = list(self.seleccion)

        async def armar():
            jugador = list(await asyncio.gather(*[pokeapi.preparar(i) for i in ids]))
            return jugador, await pokeapi.equipo_rival(jugador)
        self.fut_batalla = en_segundo_plano(armar())

    # ---- ciclo
    def manejar(self, ev):
        if self.fut_batalla:
            return
        if ev.type == pygame.TEXTINPUT:
            if len(self.busqueda) < 24:
                self.busqueda += ev.text
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_BACKSPACE:
                self.busqueda = self.busqueda[:-1]
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.buscar()
            elif ev.key == pygame.K_ESCAPE:
                if self.busqueda:
                    self.busqueda = ""
                else:
                    self.app.corriendo = False
        elif ev.type == pygame.MOUSEWHEEL:
            filas = math.ceil(len(self.orden) / self.COLS)
            self.fila = max(0, min(max(0, filas - 2), self.fila - ev.y))
        elif es_clic(ev):
            for b in (self.b_azar, self.b_pelear, self.b_sonido):
                if b.clic(ev.pos):
                    return
            for rect, (ident, _) in self._rects_sugerencias():
                if rect.collidepoint(ev.pos):
                    self.busqueda = ""
                    self.buscar(str(ident))
                    return
            for rect, ident in self._rects_cartas():
                if rect.collidepoint(ev.pos) and ident in self.fichas:
                    if ident in self.seleccion:
                        self.seleccion.remove(ident)
                    elif len(self.seleccion) < TAM_EQUIPO:
                        self.seleccion.append(ident)
                    return
            for i, rect in enumerate(self._rects_equipo()):
                if rect.collidepoint(ev.pos) and i < len(self.seleccion):
                    self.seleccion.pop(i)
                    return

    def actualizar(self, dt):
        if self.fut_especies and self.fut_especies.done():
            try:
                self.especies = self.fut_especies.result()
                self.msg = "Hay 1025 para elegir."
            except Exception as e:
                self.msg, self.msg_error = f"Sin conexión con PokeAPI ({e}).", True
            self.fut_especies = None
        for ident, fut in list(self.pendientes.items()):
            if fut.done():
                del self.pendientes[ident]
                try:
                    self.fichas[ident] = fut.result()
                    self.app.medios.pedir(url_frente(self.fichas[ident]))
                    if ident in self.auto_elegir:
                        self._elegir(ident)
                except Exception:
                    if ident in self.orden:
                        self.orden.remove(ident)
        if self.fut_busqueda and self.fut_busqueda.done():
            try:
                ident = self.fut_busqueda.result()
                if ident in self.orden:
                    self.orden.remove(ident)
                self.orden.insert(0, ident)
                self.fila = 0
                self._cargar(ident, elegir=True)
                self.busqueda = ""
                self.msg, self.msg_error = f"Pokémon #{ident} agregado.", False
            except Exception as e:
                self.msg, self.msg_error = str(e), True
            self.fut_busqueda = None
        if self.fut_batalla and self.fut_batalla.done():
            try:
                jugador, rival = self.fut_batalla.result()
                self.app.cambiar(BatallaEscena(self.app, Batalla(jugador, rival)))
            except Exception as e:
                self.msg, self.msg_error = f"No se pudo armar la batalla ({e}).", True
            self.fut_batalla = None
        self.b_pelear.habilitado = len(self.seleccion) == TAM_EQUIPO
        self.b_sonido.etiqueta = "Son: sí" if self.app.sonido else "Son: no"

    # ---- geometría
    def _rects_cartas(self):
        salida = []
        for n, ident in enumerate(self.orden[self.fila * self.COLS:(self.fila + 2) * self.COLS]):
            f, c = divmod(n, self.COLS)
            salida.append((pygame.Rect(self.ZONA.x + c * (self.ANCHO_C + self.GAP),
                                       self.ZONA.y + f * (self.ALTO_C + self.GAP), self.ANCHO_C, self.ALTO_C), ident))
        return salida

    def _rects_sugerencias(self):
        return [(pygame.Rect(20, 176 + 40 * i, 560, 38), e) for i, e in enumerate(self.sugerencias())]

    def _rects_equipo(self):
        return [pygame.Rect(470 + i * 158, 70, 150, 50) for i in range(TAM_EQUIPO)]

    # ---- dibujo
    def dibujar(self, sup):
        sup.fill(C["fondo"])
        texto(sup, "Poké Batalla", (20, 16), 52, C["acento"], True)
        texto(sup, f"Python {sys.version.split()[0]} · pygame {pygame.version.ver} · datos de PokeAPI",
              (22, 56), 22, C["suave"])
        self.b_sonido.dibujar(sup)

        texto(sup, f"Tu equipo {len(self.seleccion)}/{TAM_EQUIPO}", (22, 88), 30, C["texto"], True)
        for i, r in enumerate(self._rects_equipo()):
            pygame.draw.rect(sup, C["panel"], r, border_radius=25)
            ocupado = i < len(self.seleccion)
            pygame.draw.rect(sup, C["acento"] if ocupado else C["borde"], r, 2, border_radius=25)
            if ocupado and self.seleccion[i] in self.fichas:
                p = self.fichas[self.seleccion[i]]
                img = self.app.medios.imagen(url_frente(p), (40, 40))
                if img:
                    sup.blit(img[0][0], img[0][0].get_rect(center=(r.x + 26, r.centery)))
                texto(sup, p["nombre"], (r.x + 50, r.centery), 22, C["texto"], True, ancla="midleft", ancho_max=92)
            else:
                texto(sup, "vacío", r.center, 20, C["suave"], ancla="center")

        # buscador
        caja = pygame.Rect(20, 132, 700, 42)
        pygame.draw.rect(sup, C["panel"], caja, border_radius=10)
        pygame.draw.rect(sup, C["azul"], caja, 2, border_radius=10)
        if self.busqueda:
            r = texto(sup, self.busqueda, (caja.x + 14, caja.centery), 28, C["texto"], ancla="midleft")
            if pygame.time.get_ticks() // 500 % 2:
                pygame.draw.line(sup, C["texto"], (r.right + 2, r.top), (r.right + 2, r.bottom), 2)
        else:
            texto(sup, "Escribí un nombre o número (ej. lucario, 448) y Enter…", (caja.x + 14, caja.centery),
                  24, C["suave"], ancla="midleft")
        texto(sup, self.msg, (734, 153), 19, C["acento"] if self.msg_error else C["suave"], ancla="midleft", ancho_max=210)

        # grilla
        for rect, ident in self._rects_cartas():
            self._carta(sup, rect, ident)
        filas = math.ceil(len(self.orden) / self.COLS)
        if filas > 2:
            texto(sup, f"Rueda del mouse para ver más ({self.fila + 1}/{filas - 1})",
                  (self.ZONA.centerx, 530), 19, C["suave"], ancla="center")

        for s in (self.b_azar, self.b_pelear):
            s.dibujar(sup)

        # sugerencias (encima de la grilla)
        for rect, (ident, nombre) in self._rects_sugerencias():
            hover = rect.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(sup, (232, 240, 250) if hover else C["panel"], rect)
            pygame.draw.rect(sup, C["borde"], rect, 1)
            texto(sup, f"#{ident:04d}", (rect.x + 12, rect.centery), 22, C["suave"], ancla="midleft")
            texto(sup, nombre, (rect.x + 90, rect.centery), 24, C["texto"], True, ancla="midleft")

        if self.fut_batalla:
            self.app.cargando(sup, "Descargando movimientos y armando al rival desde PokeAPI…")

    def _carta(self, sup, r, ident):
        elegida = ident in self.seleccion
        hover = r.collidepoint(pygame.mouse.get_pos())
        fondo = (253, 238, 234) if elegida else C["panel"]
        pygame.draw.rect(sup, fondo, r.move(0, -2 if hover else 0), border_radius=12)
        pygame.draw.rect(sup, C["acento"] if elegida else C["borde"], r.move(0, -2 if hover else 0), 2, border_radius=12)
        p = self.fichas.get(ident)
        if not p:
            pulso = 200 + int(30 * math.sin(pygame.time.get_ticks() / 200))
            pygame.draw.circle(sup, (pulso, pulso, pulso + 10 if pulso < 245 else 255), (r.centerx, r.y + 44), 30)
            texto(sup, f"#{ident:04d}", (r.centerx, r.y + 92), 19, C["suave"], ancla="center")
            return
        texto(sup, f"#{p['id']:04d}", (r.x + 8, r.y + 6), 16, C["suave"])
        img = self.app.medios.imagen(url_frente(p), (80, 62))
        if img:
            sup.blit(img[0][0], img[0][0].get_rect(midbottom=(r.centerx, r.y + 76)))
        texto(sup, p["nombre"], (r.centerx, r.y + 77), 22, C["texto"], True, ancla="midtop", ancho_max=r.w - 8)
        tipos_pastillas(sup, p["tipos"], 0, r.y + 94, centrar_en=r.centerx, tam=15, ancho_max=r.w - 8)
        texto(sup, f"Total {pokeapi.total_base(p)}", (r.centerx, r.bottom - 3), 16, C["suave"], ancla="midbottom")


# ---------------------------------------------------------------- escena: batalla
PALABRAS_PS = ("perdió", "retroceso", "resiente", "debilitó", "paraliz", "quemó", "envenen",
               "durmió", "congel", "despertó", "descongel")


class BatallaEscena:
    ARENA = pygame.Rect(0, 0, ANCHO, 392)
    LOG = pygame.Rect(16, 404, 454, 222)
    CTRL = pygame.Rect(486, 404, 458, 222)
    CENTRO = {"cpu": (705, 214), "jugador": (245, 386)}
    CAJA = {"cpu": (200, 170), "jugador": (250, 210)}

    def __init__(self, app, batalla):
        self.app = app
        self.b = batalla
        self.objetivo = batalla.estado()
        self.vista = copy.deepcopy(self.objetivo)
        self.mostrado = {"jugador": None, "cpu": None}
        self.barra = {"jugador": 0.0, "cpu": 0.0}
        self.entrada = {"jugador": 0, "cpu": 0}
        self.sacudida = {"jugador": -9999, "cpu": -9999}
        self.desmayo = {"jugador": None, "cpu": None}
        self.cola = list(self.objetivo["log"])
        self.lineas = []
        self.actual, self.chars, self.pausa = None, 0.0, 0.0
        self.tab = "movs"
        self.aviso = ""
        self.fondo = self._pintar_fondo()
        for lado in ("jugador", "cpu"):
            for p in self.objetivo[lado]["equipo"]:
                for url in self._urls(lado, p):
                    app.medios.pedir(url)
                app.medios.pedir(p.get("grito"))
        self.b_volver = Boton((ANCHO // 2 - 110, 360, 220, 52), "Jugar de nuevo", self.volver)

    def _urls(self, lado, p):
        if ANIMADO:
            return [p["sprites"]["frente"] if lado == "cpu" else p["sprites"]["espalda"], url_frente(p)]
        return [url_frente(p)] if lado == "cpu" else [url_espalda(p), url_frente(p)]

    def _pintar_fondo(self):
        s = pygame.Surface(self.ARENA.size)
        for y in range(self.ARENA.h):
            if y < 210:
                k = y / 210
                col = (int(159 + (217 - 159) * k), int(214 + (240 - 214) * k), int(245 + (251 - 245) * k))
            else:
                k = (y - 210) / (self.ARENA.h - 210)
                col = (int(167 - 33 * k), int(217 - 21 * k), int(143 - 29 * k))
            pygame.draw.line(s, col, (0, y), (self.ARENA.w, y))
        pygame.draw.ellipse(s, (124, 194, 106), (160, 250, 640, 330))
        for lado, (cx, cy) in self.CENTRO.items():
            w = 230 if lado == "jugador" else 200
            pygame.draw.ellipse(s, (95, 150, 90), (cx - w // 2, cy - 22, w, 40))
        return s

    # ---- reproducción del log sincronizada con la animación
    def ocupado(self):
        return bool(self.cola) or self.actual is not None

    def _lado_de(self, s):
        return "cpu" if " rival" in s else "jugador"

    def _sincronizar(self, lado):
        i = self.mostrado[lado]
        if i is not None:
            self.vista[lado]["equipo"][i] = copy.deepcopy(self.objetivo[lado]["equipo"][i])

    def _mostrar(self, lado, nombre):
        equipo = self.objetivo[lado]["equipo"]
        candidatos = [i for i, p in enumerate(equipo) if p["nombre"] == nombre]
        if not candidatos:
            return
        i = self.objetivo[lado]["activo"] if self.objetivo[lado]["activo"] in candidatos else candidatos[0]
        self.mostrado[lado] = i
        self.vista[lado]["activo"] = i
        self._sincronizar(lado)
        self.barra[lado] = float(self.vista[lado]["equipo"][i]["ps"])
        self.entrada[lado] = pygame.time.get_ticks()
        self.desmayo[lado] = None
        self.app.gritar(equipo[i].get("grito"))

    def _procesar(self, linea):
        s = linea.lstrip("¡")
        if linea.startswith("El rival envió a "):
            return self._mostrar("cpu", linea[len("El rival envió a "):].rstrip("."))
        if linea.startswith("¡Adelante, "):
            return self._mostrar("jugador", linea[len("¡Adelante, "):].rstrip("!"))
        if "volvé!" in linea or "El rival retiró" in linea:
            lado = "jugador" if "volvé!" in linea else "cpu"
            self.mostrado[lado] = None
            return
        if "absorbió" in s:
            self._sincronizar("jugador")
            self._sincronizar("cpu")
            return
        if any(p in s for p in PALABRAS_PS):
            lado = self._lado_de(s)
            self._sincronizar(lado)
            if "perdió" in s and "PS" in s:
                self.sacudida[lado] = pygame.time.get_ticks()
            if "debilitó" in s:
                self.desmayo[lado] = pygame.time.get_ticks()

    def _terminar_reproduccion(self):
        self.vista = copy.deepcopy(self.objetivo)
        for lado in ("jugador", "cpu"):
            activo = self.objetivo[lado]["activo"]
            if self.mostrado[lado] != activo and self.objetivo[lado]["equipo"][activo]["vivo"]:
                self._mostrar(lado, self.objetivo[lado]["equipo"][activo]["nombre"])
        if self.objetivo["cambio_forzado"]:
            self.tab = "equipo"

    def _clase(self, t):
        if t.startswith("—"):
            return C["amarillo"]
        if "súper eficaz" in t:
            return C["eficaz"]
        if "No es muy eficaz" in t or "No afecta" in t:
            return C["poco"]
        if "debilitó" in t or "Perdiste" in t:
            return C["debil"]
        return C["log_txt"]

    # ---- acciones
    def accion(self, acc):
        if self.ocupado() or self.objetivo["ganador"]:
            return
        turno, forzado = self.objetivo["turno"], self.objetivo["cambio_forzado"]
        try:
            self.b.jugar_turno(acc)
        except ValueError as e:
            self.aviso = str(e)
            return
        self.aviso = ""
        self.objetivo = self.b.estado()
        if not forzado:
            self.cola.append(f"— Turno {turno} —")
        self.cola.extend(self.objetivo["log"])
        if acc["tipo"] == "cambio" or not self.objetivo["cambio_forzado"]:
            self.tab = "movs"

    def volver(self):
        self.app.cambiar(Seleccion(self.app))

    def _botones_mov(self):
        p = self.objetivo["jugador"]["equipo"][self.objetivo["jugador"]["activo"]]
        x0, y0 = self.CTRL.x + 12, self.CTRL.y + 52
        return [(pygame.Rect(x0 + (i % 2) * 222, y0 + (i // 2) * 84, 214, 76), i, m)
                for i, m in enumerate(p["movimientos"])]

    def _botones_equipo(self):
        x0, y0 = self.CTRL.x + 12, self.CTRL.y + 52
        return [(pygame.Rect(x0 + (i % 2) * 222, y0 + (i // 2) * 56, 214, 50), i, p)
                for i, p in enumerate(self.objetivo["jugador"]["equipo"])]

    def _tabs(self):
        return {"movs": pygame.Rect(self.CTRL.x + 12, self.CTRL.y + 10, 214, 34),
                "equipo": pygame.Rect(self.CTRL.x + 234, self.CTRL.y + 10, 214, 34)}

    def manejar(self, ev):
        fin = self.objetivo["ganador"] and not self.ocupado()
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                return self.volver()
            if ev.key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_KP_ENTER):
                return self._adelantar()
            if ev.key == pygame.K_TAB and not self.objetivo["cambio_forzado"]:
                self.tab = "equipo" if self.tab == "movs" else "movs"
            if pygame.K_1 <= ev.key <= pygame.K_4 and self.tab == "movs":
                i = ev.key - pygame.K_1
                if i < len(self._botones_mov()):
                    self.accion({"tipo": "movimiento", "indice": i})
        elif es_clic(ev):
            if fin:
                return self.b_volver.clic(ev.pos)
            if self.LOG.collidepoint(ev.pos) or self.ARENA.collidepoint(ev.pos):
                return self._adelantar()
            for nombre, r in self._tabs().items():
                if r.collidepoint(ev.pos) and not self.objetivo["cambio_forzado"]:
                    self.tab = nombre
                    return
            if self.tab == "movs":
                for r, i, _ in self._botones_mov():
                    if r.collidepoint(ev.pos):
                        return self.accion({"tipo": "movimiento", "indice": i})
            else:
                for r, i, _ in self._botones_equipo():
                    if r.collidepoint(ev.pos):
                        return self.accion({"tipo": "cambio", "indice": i})

    def _adelantar(self):
        if self.actual is not None:
            if self.chars < len(self.actual):
                self.chars = len(self.actual)
            else:
                self.pausa = 0

    def actualizar(self, dt):
        # texto tipo máquina de escribir
        if self.actual is None and self.cola:
            self.actual = self.cola.pop(0)
            self.chars, self.pausa = 0.0, 0.32
            self._procesar(self.actual)
        if self.actual is not None:
            if self.chars < len(self.actual):
                self.chars += dt * 95
            else:
                self.pausa -= dt
                if self.pausa <= 0:
                    self.lineas.append(self.actual)
                    self.lineas = self.lineas[-40:]
                    self.actual = None
                    if not self.cola:
                        self._terminar_reproduccion()
        # barras de PS que bajan suave
        for lado in ("jugador", "cpu"):
            i = self.mostrado[lado]
            if i is None:
                continue
            p = self.vista[lado]["equipo"][i]
            paso = p["ps_max"] * 0.9 * dt
            if self.barra[lado] > p["ps"]:
                self.barra[lado] = max(p["ps"], self.barra[lado] - paso)
            elif self.barra[lado] < p["ps"]:
                self.barra[lado] = min(p["ps"], self.barra[lado] + paso)

    # ---- dibujo
    def dibujar(self, sup):
        sup.fill(C["fondo"])
        sup.blit(self.fondo, self.ARENA)
        ahora = pygame.time.get_ticks()
        for lado in ("cpu", "jugador"):
            self._pokemon(sup, lado, ahora)
        self._info(sup, "cpu", (28, 22))
        self._info(sup, "jugador", (628, 270))
        # pokébolas del rival
        for n, p in enumerate(self.vista["cpu"]["equipo"]):
            c = (42 + n * 22, 128)
            if p["vivo"]:
                pokebola(sup, c, 8)
            else:
                pygame.draw.circle(sup, (140, 140, 140), c, 8)
        self._log(sup)
        self._controles(sup)
        if self.objetivo["ganador"] and not self.ocupado():
            capa = pygame.Surface((ANCHO, ALTO), pygame.SRCALPHA)
            capa.fill((0, 0, 0, 140))
            sup.blit(capa, (0, 0))
            caja = pygame.Rect(ANCHO // 2 - 220, 210, 440, 230)
            pygame.draw.rect(sup, C["panel"], caja, border_radius=16)
            g = self.objetivo["ganador"]
            titulo = "¡Ganaste!" if g == "jugador" else "Perdiste..." if g == "cpu" else "¡Empate!"
            texto(sup, titulo, (caja.centerx, caja.y + 60), 64, C["acento"] if g != "jugador" else C["verde"],
                  True, ancla="center")
            texto(sup, f"La batalla duró {self.objetivo['turno'] - 1} turnos", (caja.centerx, caja.y + 108),
                  24, C["suave"], ancla="center")
            self.b_volver.dibujar(sup)

    def _pokemon(self, sup, lado, ahora):
        i = self.mostrado[lado]
        if i is None:
            return
        p = self.objetivo[lado]["equipo"][i]
        caja = self.CAJA[lado]
        cuadros = None
        for n, url in enumerate(self._urls(lado, p)):
            espejo = lado == "jugador" and url == url_frente(p)   # sin sprite de espalda: el de frente espejado
            cuadros = self.app.medios.imagen(url, caja, espejo)
            if cuadros or not self.app.medios.listo(url):
                break
        cx, cy = self.CENTRO[lado]
        if not cuadros:
            pokebola(sup, (cx, cy - 40), 26, (ahora // 3) % 360)
            return
        img = cuadro_actual(cuadros)
        dx = dy = 0
        t = ahora - self.sacudida[lado]
        if t < 450:
            dx = int(8 * math.sin(t / 30))
            if (t // 60) % 2:
                return  # parpadeo al recibir el golpe
        t = ahora - self.entrada[lado]
        if t < 300:
            img = pygame.transform.rotozoom(img, 0, max(0.1, t / 300))
        if self.desmayo[lado] is not None:
            t = ahora - self.desmayo[lado]
            if t > 600:
                return
            dy = int(t / 600 * 60)
            img = img.copy()
            img.set_alpha(max(0, 255 - int(t / 600 * 255)))
        sup.blit(img, img.get_rect(midbottom=(cx + dx, cy + 8 + dy)))

    def _info(self, sup, lado, pos):
        i = self.mostrado[lado]
        if i is None:
            return
        p = self.vista[lado]["equipo"][i]
        alto = 96 if lado == "jugador" else 82
        r = pygame.Rect(pos, (300, alto))
        sombra = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(sombra, (0, 0, 0, 45), sombra.get_rect(), border_radius=12)
        sup.blit(sombra, r.move(0, 4))
        pygame.draw.rect(sup, C["panel"], r, border_radius=12)
        nr = texto(sup, p["nombre"], (r.x + 14, r.y + 10), 28, C["texto"], True, ancho_max=190)
        if p.get("estado"):
            pastilla(sup, p["estado"], (nr.right + 6, r.y + 10), ESTADO_COLOR.get(p["estado"], (120, 120, 120)), 16)
        texto(sup, "Nv. 50", (r.right - 14, r.y + 12), 21, C["suave"], ancla="topright")
        tipos_pastillas(sup, p["tipos"], r.x + 14, r.y + 34)
        barra_ps(sup, pygame.Rect(r.x + 14, r.y + 60, r.w - 28, 10), self.barra[lado], p["ps_max"])
        if lado == "jugador":
            texto(sup, f"{round(self.barra[lado])} / {p['ps_max']}", (r.right - 14, r.y + 74), 21, C["suave"],
                  ancla="topright")

    def _log(self, sup):
        pygame.draw.rect(sup, C["log"], self.LOG, border_radius=14)
        fuente = F(23)
        renglones = []
        for l in self.lineas + ([self.actual[:int(self.chars)]] if self.actual is not None else []):
            color = self._clase(l if l is not self.actual else self.actual)
            for sub in envolver(l, fuente, self.LOG.w - 32):
                renglones.append((sub, color))
        alto = fuente.get_linesize() + 3
        caben = (self.LOG.h - 24) // alto
        y = self.LOG.y + 14
        for sub, color in renglones[-caben:]:
            sup.blit(fuente.render(sub, True, color), (self.LOG.x + 16, y))
            y += alto
        if self.ocupado():
            texto(sup, "Espacio / clic para adelantar", (self.LOG.right - 12, self.LOG.bottom - 8), 17,
                  (130, 140, 160), ancla="bottomright")

    def _controles(self, sup):
        pygame.draw.rect(sup, C["panel"], self.CTRL, border_radius=14)
        forzado = self.objetivo["cambio_forzado"]
        bloqueado = self.ocupado() or bool(self.objetivo["ganador"])
        for nombre, r in self._tabs().items():
            activa = self.tab == nombre
            pygame.draw.rect(sup, C["azul"] if activa else C["panel"], r, border_radius=8)
            if not activa:
                pygame.draw.rect(sup, C["borde"], r, 2, border_radius=8)
            texto(sup, "Luchar" if nombre == "movs" else "Pokémon", r.center, 26,
                  (255, 255, 255) if activa else C["texto"], True, ancla="center")
        if self.tab == "movs":
            sin_pp = all(m["pp"] == 0 for _, _, m in self._botones_mov())
            for r, i, m in self._botones_mov():
                ok = not bloqueado and not forzado and (m["pp"] > 0 or sin_pp)
                col = TIPO_COLOR.get(m["tipo"]["clave"], (120, 120, 120))
                if ok and r.collidepoint(pygame.mouse.get_pos()):
                    col = aclarar(col, .12)
                if not ok:
                    col = aclarar(col, .5)
                pygame.draw.rect(sup, col, r, border_radius=10)
                blanco = (255, 255, 255)
                texto(sup, f"{i + 1}. {m['nombre']}", (r.x + 10, r.y + 8), 25, blanco, True, ancho_max=r.w - 20)
                cat = "Físico" if m["categoria"] == "fisico" else "Especial"
                prec = f" · Prec {m['precision']}" if m["precision"] else ""
                texto(sup, f"{m['tipo']['nombre']} · {cat} · Pot {m['poder']}{prec}", (r.x + 10, r.y + 30), 17,
                      blanco, ancho_max=r.w - 20)
                if m.get("efecto"):
                    texto(sup, m["efecto"], (r.x + 10, r.y + 45), 16, blanco, italica=True, ancho_max=r.w - 20)
                texto(sup, f"PP {m['pp']}/{m['pp_max']}", (r.right - 10, r.bottom - 6), 18, blanco, True,
                      ancla="bottomright")
        else:
            if forzado and not self.ocupado():
                texto(sup, "Tu Pokémon se debilitó: elegí el siguiente.", (self.CTRL.x + 14, self.CTRL.bottom - 12),
                      20, C["acento"], True, ancla="bottomleft")
            activo = self.objetivo["jugador"]["activo"]
            for r, i, p in self._botones_equipo():
                ok = not bloqueado and p["vivo"] and i != activo
                pygame.draw.rect(sup, (232, 240, 250) if ok and r.collidepoint(pygame.mouse.get_pos()) else C["panel"], r,
                                 border_radius=10)
                pygame.draw.rect(sup, C["azul"] if i == activo else C["borde"], r, 2, border_radius=10)
                img = self.app.medios.imagen(url_frente(p), (40, 40))
                if img:
                    s = img[0][0].copy()
                    if not ok:
                        s.set_alpha(110)
                    sup.blit(s, s.get_rect(center=(r.x + 28, r.centery)))
                color = C["texto"] if ok or i == activo else C["suave"]
                texto(sup, p["nombre"], (r.x + 54, r.y + 7), 23, color, True, ancho_max=r.w - 60)
                est = f" · {p['estado']}" if p.get("estado") else ""
                sub = f"PS {p['ps']}/{p['ps_max']}{est}" if p["vivo"] else "Debilitado"
                texto(sup, sub, (r.x + 54, r.y + 28), 19, C["suave"])
        if self.aviso:
            texto(sup, self.aviso, (self.CTRL.x + 14, self.CTRL.bottom - 12), 19, C["acento"], ancla="bottomleft")


# ---------------------------------------------------------------- aplicación
class App:
    def __init__(self, ventana=True):
        global F
        pygame.init()
        try:
            pygame.mixer.init()
        except pygame.error:
            pass
        flags = pygame.SCALED | pygame.RESIZABLE if ventana else 0
        try:
            self.pantalla = pygame.display.set_mode((ANCHO, ALTO), flags)
        except pygame.error:
            self.pantalla = pygame.display.set_mode((ANCHO, ALTO))
        pygame.display.set_caption("Poké Batalla — Python + pygame + PokeAPI")
        icono = pygame.Surface((32, 32), pygame.SRCALPHA)
        F = Fuentes()
        pokebola(icono, (16, 16), 14)
        pygame.display.set_icon(icono)
        self.reloj = pygame.time.Clock()
        self.medios = Medios()
        self.sonido = bool(pygame.mixer.get_init())
        self.corriendo = True
        self.escena = Seleccion(self)

    def cambiar(self, escena):
        self.escena = escena

    def alternar_sonido(self):
        self.sonido = not self.sonido and bool(pygame.mixer.get_init())

    def gritar(self, url):
        if self.sonido:
            s = self.medios.sonido(url)
            if s:
                s.set_volume(0.3)
                s.play()

    def cargando(self, sup, mensaje):
        capa = pygame.Surface((ANCHO, ALTO), pygame.SRCALPHA)
        capa.fill((0, 0, 0, 150))
        sup.blit(capa, (0, 0))
        caja = pygame.Rect(ANCHO // 2 - 290, ALTO // 2 - 90, 580, 180)
        pygame.draw.rect(sup, C["panel"], caja, border_radius=16)
        pokebola(sup, (caja.centerx, caja.y + 62), 30, -(pygame.time.get_ticks() // 3) % 360)
        texto(sup, mensaje, (caja.centerx, caja.y + 128), 24, C["texto"], True, ancla="center")

    def paso(self, eventos):
        dt = min(self.reloj.tick(FPS) / 1000, 0.05)
        for ev in eventos:
            if ev.type == pygame.QUIT:
                self.corriendo = False
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_F11:
                pygame.display.toggle_fullscreen()
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_m and not isinstance(self.escena, Seleccion):
                self.alternar_sonido()
            else:
                self.escena.manejar(ev)
        self.escena.actualizar(dt)
        self.escena.dibujar(self.pantalla)
        pygame.display.flip()

    def correr(self):
        while self.corriendo:
            self.paso(pygame.event.get())
        pygame.quit()


if __name__ == "__main__":
    App().correr()
