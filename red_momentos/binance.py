"""Velas diarias de Binance (spot y futuros USDⓈ-M), de 00:00 UTC a 00:00 UTC.

Primero se piden a la API pública (sin claves):

- spot: ``data-api.binance.vision`` y, si falla, ``api.binance.com``;
- futuros: ``www.binance.com`` y, si falla, ``fapi.binance.com``.

Desde los servidores de GitHub (EE. UU.) ``api.binance.com`` y ``fapi.binance.com`` dan error 451; las
otras dos responden (las usa también el escaneo diario de Scanner-pump). Si ninguna dirección de un
mercado responde, se pasa a los archivos históricos de ``data.binance.vision``: uno por mes y, para el
mes en curso, uno por día. Esos archivos se publican al día siguiente, hacia las 08:00 UTC, así que con
ellos la última vela cerrada puede faltar todavía.
"""

from __future__ import annotations

import csv
import io
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

import requests

from .fechas import UN_DIA, dia_de_ms, ms

VISION = "https://data.binance.vision/data"
USER_AGENT = "Mozilla/5.0 (compatible; Red-Neuronal-Momentos)"


@dataclass(frozen=True)
class Mercado:
    clave: str
    urls: tuple[str, ...]
    ruta_velas: str
    max_velas: int
    limite_peso: int  # peso por minuto que permite Binance
    vision: str  # carpeta en data.binance.vision


SPOT = Mercado("spot", ("https://data-api.binance.vision", "https://api.binance.com"),
               "/api/v3/klines", 1000, 6000, "spot")
FUTUROS = Mercado("futures", ("https://www.binance.com", "https://fapi.binance.com"),
                  "/fapi/v1/klines", 1500, 2400, "futures/um")
MERCADOS = {SPOT.clave: SPOT, FUTUROS.clave: FUTUROS}


@dataclass(frozen=True)
class Vela:
    dia: date  # día UTC en que abre
    open: float
    high: float
    low: float
    close: float
    volumen: float  # en la moneda
    volumen_usdt: float  # en la moneda de cotización
    operaciones: int
    compra_taker: float  # parte del volumen que fueron compras a mercado (en la moneda)
    compra_taker_usdt: float


def vela_de_fila(fila: list) -> Vela:
    """Vela a partir de una fila de la API o de un CSV de data.binance.vision.

    Los archivos de spot de data.binance.vision usan microsegundos desde 2025; la API, milisegundos.
    """
    apertura = int(fila[0])
    if apertura > 10**14:
        apertura //= 1000
    return Vela(dia_de_ms(apertura), float(fila[1]), float(fila[2]), float(fila[3]), float(fila[4]),
                float(fila[5]), float(fila[7]), int(fila[8]), float(fila[9]), float(fila[10]))


class SinAPI(RuntimeError):
    """Ninguna dirección de la API responde para ese mercado."""


class _Peso:
    """Peso usado en el minuto en curso, según la cabecera ``X-MBX-USED-WEIGHT-1M`` de Binance."""

    def __init__(self, limite: int, margen: float = 0.8) -> None:
        self._tope = int(limite * margen)
        self._usado = 0
        self._minuto = 0
        self._lock = threading.Lock()

    def esperar(self) -> None:
        with self._lock:
            ahora = time.time()
            if int(ahora // 60) == self._minuto and self._usado >= self._tope:
                time.sleep((self._minuto + 1) * 60 - ahora + 0.5)

    def anotar(self, usado: Optional[str]) -> None:
        if usado and usado.isdigit():
            with self._lock:
                self._minuto = int(time.time() // 60)
                self._usado = int(usado)


class Binance:
    def __init__(self, sesion: Any = None, usar_api: bool = True, timeout: float = 20.0,
                 reintentos: int = 4, espera: float = 2.0) -> None:
        self.sesion = sesion or requests.Session()
        if hasattr(self.sesion, "headers"):
            self.sesion.headers["User-Agent"] = USER_AGENT
        self.timeout = timeout
        self.reintentos = reintentos
        self.espera = espera  # segundos antes del primer reintento (se dobla en cada uno)
        self._urls = {clave: list(m.urls) for clave, m in MERCADOS.items()}
        self._api = {clave: usar_api for clave in MERCADOS}
        self._peso = {clave: _Peso(m.limite_peso) for clave, m in MERCADOS.items()}
        self._cobertura: dict[tuple[str, date], date] = {}
        self._lock = threading.Lock()
        self.avisos: list[str] = []

    def velas_diarias(self, mercado: str, simbolo: str, desde: date, hasta: date) -> tuple[list[Vela], date]:
        """Velas cerradas de ``desde`` a ``hasta`` (días UTC, ambos incluidos).

        Devuelve también el último día que la fuente ya tiene publicado: si una vela posterior falta, es
        porque no existe todavía, no porque el par dejara de cotizar.
        """
        if self._api[mercado]:
            try:
                return self._velas_api(mercado, simbolo, desde, hasta), hasta
            except SinAPI as exc:
                with self._lock:
                    if self._api[mercado]:
                        self._api[mercado] = False
                        self.avisos.append(f"{mercado}: {exc}; se usan los archivos de data.binance.vision")
        return self._velas_vision(mercado, simbolo, desde, hasta), self._cubierto_vision(mercado, hasta)

    # --- API -------------------------------------------------------------------------------------

    def _velas_api(self, mercado: str, simbolo: str, desde: date, hasta: date) -> list[Vela]:
        m = MERCADOS[mercado]
        velas: list[Vela] = []
        inicio = desde
        while inicio <= hasta:
            limite = min(m.max_velas, (hasta - inicio).days + 1)
            filas = self._get(mercado, m.ruta_velas, {
                "symbol": simbolo, "interval": "1d", "limit": limite,
                "startTime": ms(inicio), "endTime": ms(hasta + UN_DIA) - 1,
            })
            if not filas:
                break
            velas.extend(v for v in map(vela_de_fila, filas) if desde <= v.dia <= hasta)
            inicio = dia_de_ms(int(filas[-1][0])) + UN_DIA
        return velas

    def _get(self, mercado: str, ruta: str, params: dict) -> list:
        """GET a la API. Un par que no existe en ese mercado devuelve una lista vacía."""
        fallos = 0
        ultimo = "sin respuesta"
        while True:
            with self._lock:
                if not self._urls[mercado]:
                    raise SinAPI(f"ninguna dirección de la API responde ({ultimo})")
                base = self._urls[mercado][0]
            self._peso[mercado].esperar()
            try:
                resp = self.sesion.get(base + ruta, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                ultimo = f"{base}: {exc.__class__.__name__}"
                fallos += 1
                if fallos >= 2:
                    self._descartar(mercado, base)
                    fallos = 0
                else:
                    time.sleep(self.espera)
                continue

            self._peso[mercado].anotar(resp.headers.get("X-MBX-USED-WEIGHT-1M"))
            if resp.status_code == 200:
                try:
                    datos = resp.json()
                except ValueError:
                    datos = None
                if isinstance(datos, list):
                    return datos
                # Una página que no es la API (p. ej. la comprobación anti-robots de la web de Binance).
                ultimo = f"{base} no devolvió datos de la API"
                self._descartar(mercado, base)
            elif resp.status_code == 400 and _codigo(resp) == -1121:
                return []  # «Invalid symbol»: el par no existe (o ya no) en este mercado
            elif resp.status_code in (202, 403, 451):
                ultimo = f"{base}: {resp.status_code}"
                self._descartar(mercado, base)
            elif resp.status_code in (418, 429) and fallos < self.reintentos:
                fallos += 1
                espera = resp.headers.get("Retry-After", "")
                time.sleep(int(espera) if espera.isdigit() else 60)
            elif resp.status_code >= 500 and fallos < self.reintentos:
                fallos += 1
                time.sleep(self.espera * 2 ** fallos)
            else:
                raise RuntimeError(f"{base}{ruta} {params}: {resp.status_code} {resp.text[:200]}")

    def _descartar(self, mercado: str, base: str) -> None:
        with self._lock:
            if base in self._urls[mercado]:
                self._urls[mercado].remove(base)

    # --- data.binance.vision ---------------------------------------------------------------------

    def _velas_vision(self, mercado: str, simbolo: str, desde: date, hasta: date) -> list[Vela]:
        carpeta = f"{VISION}/{MERCADOS[mercado].vision}"
        velas: dict[date, Vela] = {}
        mes = desde.replace(day=1)
        while mes <= hasta:
            siguiente = (mes + timedelta(days=32)).replace(day=1)
            filas = self._zip(f"{carpeta}/monthly/klines/{simbolo}/1d/{simbolo}-1d-{mes:%Y-%m}.zip")
            if filas is None:
                # El mes en curso (o uno recién terminado) solo está en archivos diarios.
                dia, fin = max(desde, mes), min(hasta, siguiente - UN_DIA)
                filas = []
                while dia <= fin:
                    filas += self._zip(f"{carpeta}/daily/klines/{simbolo}/1d/{simbolo}-1d-{dia:%Y-%m-%d}.zip") or []
                    dia += UN_DIA
            for fila in filas:
                vela = vela_de_fila(fila)
                if desde <= vela.dia <= hasta:
                    velas[vela.dia] = vela
            mes = siguiente
        return [velas[d] for d in sorted(velas)]

    def _cubierto_vision(self, mercado: str, hasta: date) -> date:
        """Último día publicado en data.binance.vision (se comprueba con BTCUSDT)."""
        clave = (mercado, hasta)
        if clave not in self._cobertura:
            carpeta = f"{VISION}/{MERCADOS[mercado].vision}/daily/klines/BTCUSDT/1d"
            dia = hasta
            while dia > hasta - timedelta(days=3) and self._zip(f"{carpeta}/BTCUSDT-1d-{dia:%Y-%m-%d}.zip") is None:
                dia -= UN_DIA
            self._cobertura[clave] = dia
        return self._cobertura[clave]

    def _zip(self, url: str) -> Optional[list[list[str]]]:
        """Filas del CSV de un archivo de data.binance.vision, o ``None`` si no existe."""
        for intento in range(self.reintentos + 1):
            try:
                resp = self.sesion.get(url, timeout=self.timeout)
            except requests.RequestException:
                resp = None
            if resp is not None and resp.status_code == 404:
                return None
            if resp is not None and resp.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(resp.content)) as archivo:
                    texto = archivo.read(archivo.namelist()[0]).decode("utf-8")
                # Los de futuros traen una cabecera («open_time,open,...»); los de spot, no.
                return [fila for fila in csv.reader(io.StringIO(texto)) if fila and fila[0].isdigit()]
            if intento < self.reintentos:
                time.sleep(self.espera * 2 ** intento)
        raise RuntimeError(f"data.binance.vision no responde: {url}")


def _codigo(resp: Any) -> Optional[int]:
    try:
        return int(resp.json().get("code"))
    except (ValueError, TypeError, AttributeError):
        return None
