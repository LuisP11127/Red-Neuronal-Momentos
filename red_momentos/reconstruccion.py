"""Reconstrucción de las listas desde 2023 con las reglas por defecto de los escáneres.

Va aparte de las listas reales: sirve para que la red tenga más ejemplos, y los aciertos se miden solo
con las listas reales. Los filtros que se eligen a mano en las webs no entran.

- **Momento-A:** MA(7) < MA(25) < MA(99), cierre a no más de 2 % por debajo de la MA(7) y vela verde.
- **Momento-B:** MA(7) > MA(25) y MA(7) < MA(99).

Se evalúa cada vela diaria cerrada (las webs miran la vela en curso cuando escaneas) de todos los pares en
USDT de spot y futuros perpetuos que cotizaron desde 2023, también los que Binance ya retiró: si no, solo
quedarían las monedas que sobrevivieron. Igual que en los escáneres se dejan fuera las monedas estables, los
tokens apalancados, las acciones tokenizadas y, en futuros, lo que no es una criptomoneda.

La etiqueta es la misma regla que la de las listas reales, pero con velas diarias: la referencia es la
apertura de la vela siguiente (00:00 UTC, 19:00 en Lima, media hora antes que en las listas reales) y el
máximo, el de las 10 velas diarias siguientes. ``python -m red_momentos.reconstruccion --comparar`` mide
cuánto se parece a la etiqueta exacta en las listas reales.

    python -m red_momentos.reconstruccion [--cache cache/velas-1d]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import sys
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from . import etiquetas, senales
from .binance import Binance, Vela
from .fechas import UN_DIA, dia_lista, ultima_vela_cerrada, vela_utc
from .listas import moneda

INICIO = date(2023, 1, 1)
CALENTAMIENTO = date(2022, 9, 1)  # 99 velas antes del 1 de enero de 2023, para tener la MA(99)
CACHE = Path("cache/velas-1d")
SALIDA = Path("datos/reconstruccion/filas.csv.gz")

# Las mismas que dejan fuera Momento-A y Momento-B.
ESTABLES = frozenset({
    "USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "PAX", "USDS", "USDSB", "USDE", "PYUSD", "USD1",
    "XUSD", "BFUSD", "RLUSD", "USDF", "AEUR", "EURI", "EUR", "GBP", "TRY", "BRL", "ARS", "MXN", "JPY",
})
# Futuros retirados que ya no salen en exchangeInfo y no son criptomonedas (índices).
INDICES = frozenset({"BLUEBIRDUSDT", "FOOTBALLUSDT", "DEFIUSDT", "BTCDOMUSDT"})
PRODUCTOS = "https://www.binance.com/bapi/asset/v2/public/asset-service/product/get-products?includeEtf=true"
LISTADO_VISION = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"


@dataclass(frozen=True)
class Par:
    mercado: str
    simbolo: str
    base: str


def _apalancado(info: dict) -> bool:
    permisos = {p for grupo in info.get("permissionSets") or [] for p in grupo} | set(info.get("permissions") or [])
    return "LEVERAGED" in permisos and "SPOT" not in permisos


def _acciones(binance: Binance) -> set[str]:
    """Pares spot que Binance etiqueta como acciones tokenizadas (bStocks)."""
    try:
        resp = binance.sesion.get(PRODUCTOS, timeout=binance.timeout)
        productos = resp.json()["data"]
    except Exception:  # no es la API oficial: si falla, se avisa y se sigue
        binance.avisos.append("no se pudo consultar qué pares spot son acciones tokenizadas")
        return set()
    return {p["s"] for p in productos if any("stock" in str(t).lower() for t in p.get("tags") or [])}


def _futuros_en_vision(binance: Binance) -> list[str]:
    """Todos los futuros USDⓈ-M con historial en data.binance.vision (también los que ya no salen en exchangeInfo)."""
    prefijo, marcador, simbolos = "data/futures/um/monthly/klines/", "", []
    while True:
        consulta = urllib.parse.urlencode({"delimiter": "/", "prefix": prefijo, "marker": marcador})
        xml = binance.sesion.get(f"{LISTADO_VISION}?{consulta}", timeout=binance.timeout).text
        prefijos = [p for p in re.findall(r"<Prefix>([^<]*)</Prefix>", xml) if p != prefijo]
        simbolos += [p[len(prefijo):].strip("/") for p in prefijos]
        if "<IsTruncated>true</IsTruncated>" not in xml or not prefijos:
            return simbolos
        marcador = prefijos[-1]


def universo(binance: Binance) -> list[Par]:
    pares: list[Par] = []
    acciones = _acciones(binance)
    for s in binance.info("spot")["symbols"]:
        if (s.get("quoteAsset") == "USDT" and s.get("baseAsset") not in ESTABLES and not _apalancado(s)
                and s["symbol"] not in acciones):
            pares.append(Par("spot", s["symbol"], s["baseAsset"]))

    conocidos = set()
    for s in binance.info("futures")["symbols"]:
        conocidos.add(s["symbol"])
        if (s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL"
                and s.get("underlyingType", "COIN") == "COIN" and s.get("baseAsset") not in ESTABLES):
            pares.append(Par("futures", s["symbol"], s["baseAsset"]))
    for simbolo in _futuros_en_vision(binance):
        if simbolo.endswith("USDT") and simbolo not in conocidos and simbolo not in INDICES:
            pares.append(Par("futures", simbolo, simbolo.removesuffix("USDT")))
    return sorted(pares, key=lambda p: (p.mercado, p.simbolo))


# --- Caché de velas diarias ---------------------------------------------------------------------------

def _leer_cache(ruta: Path) -> list[Vela]:
    if not ruta.exists():
        return []
    with ruta.open(encoding="utf-8", newline="") as fh:
        return [Vela(int(f[0]), *map(float, f[1:7]), int(f[7]), float(f[8]), float(f[9]))
                for f in csv.reader(fh)]


def velas_cacheadas(binance: Binance, par: Par, hasta: date, carpeta: Path = CACHE) -> list[Vela]:
    """Velas diarias del par desde ``CALENTAMIENTO``; solo se piden las que faltan en la caché."""
    ruta = carpeta / par.mercado / f"{par.simbolo}.csv"
    estado = carpeta / par.mercado / f"{par.simbolo}.hasta"
    velas = _leer_cache(ruta)
    revisado = date.fromisoformat(estado.read_text().strip()) if estado.exists() else CALENTAMIENTO - UN_DIA
    desde = max(revisado, velas[-1].dia if velas else revisado) + UN_DIA
    if desde > hasta:
        return velas
    nuevas, cubierto = binance.velas_diarias(par.mercado, par.simbolo, desde, hasta)
    nuevas = [v for v in nuevas if v.dia <= cubierto and (not velas or v.dia > velas[-1].dia)]
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if nuevas:
        with ruta.open("a", encoding="utf-8", newline="") as fh:
            csv.writer(fh, lineterminator="\n").writerows(
                [v.apertura, v.open, v.high, v.low, v.close, v.volumen, v.volumen_usdt, v.operaciones,
                 v.compra_taker, v.compra_taker_usdt] for v in nuevas)
    estado.write_text(cubierto.isoformat())
    return velas + nuevas


# --- Reglas -------------------------------------------------------------------------------------------

def _media(valores: np.ndarray, n: int) -> np.ndarray:
    resultado = np.full(len(valores), np.nan)
    if len(valores) >= n:
        acumulado = np.cumsum(np.insert(valores, 0, 0.0))
        resultado[n - 1:] = (acumulado[n:] - acumulado[:-n]) / n
    return resultado


def reglas(velas: list[Vela]) -> tuple[np.ndarray, np.ndarray]:
    """Para cada vela, si cumple la regla de Momento-A y la de Momento-B (con las velas anteriores)."""
    cierre = np.array([v.close for v in velas])
    apertura = np.array([v.open for v in velas])
    ma7, ma25, ma99 = _media(cierre, 7), _media(cierre, 25), _media(cierre, 99)
    with np.errstate(invalid="ignore"):
        a = (ma7 < ma25) & (ma25 < ma99) & (cierre >= ma7 * 0.98) & (cierre > apertura)
        b = (ma7 > ma25) & (ma7 < ma99)
    return a, b


@dataclass
class Reconstruida:
    fecha: date  # día de la lista
    moneda: str
    mercado: str
    simbolo: str
    listas: tuple[str, ...]


def candidatas(velas_por_par: dict[Par, list[Vela]], desde: date = INICIO) -> list[Reconstruida]:
    """Las monedas que habrían salido en Momento-A o Momento-B cada día, una vez por moneda."""
    grupos: dict[tuple[date, str], list[tuple[Par, str]]] = defaultdict(list)
    for par, velas in velas_por_par.items():
        if len(velas) < 99:
            continue
        a, b = reglas(velas)
        for i in np.flatnonzero(a | b):
            fecha = dia_lista(velas[i].dia)
            if fecha < desde:
                continue
            nombre = moneda({"base": par.base, "simbolo": par.simbolo})
            if a[i]:
                grupos[(fecha, nombre)].append((par, "momento-a"))
            if b[i]:
                grupos[(fecha, nombre)].append((par, "momento-b"))

    resultado = []
    for (fecha, nombre), items in sorted(grupos.items()):
        par = next((p for p, _ in items if p.mercado == "futures"), items[0][0])
        resultado.append(Reconstruida(fecha, nombre, par.mercado, par.simbolo, tuple(sorted({l for _, l in items}))))
    return resultado


def etiqueta_diaria(fecha: date, velas: dict[date, Vela], cubierto: date) -> etiquetas.Resultado:
    """La regla con velas diarias: referencia en la apertura de la vela siguiente (00:00 UTC)."""
    siguiente = vela_utc(fecha) + UN_DIA
    primera = velas.get(siguiente)
    if primera is None:
        return etiquetas.Resultado(estado="pendiente" if siguiente > cubierto else "sin_datos")
    r = etiquetas.Resultado(referencia=primera.open)
    meta = primera.open * (1 + etiquetas.OBJETIVO / 100)
    for k in range(etiquetas.VENTANA):
        dia = siguiente + timedelta(days=k)
        vela = velas.get(dia)
        if dia > cubierto:
            break
        r.dias_vistos = k + 1
        if vela is None:
            continue
        r.maximo = vela.high if r.maximo is None else max(r.maximo, vela.high)
        r.minimo = vela.low if r.minimo is None else min(r.minimo, vela.low)
        if r.dias_hasta_50 is None and vela.high >= meta:
            r.dias_hasta_50 = k + 1
    if r.dias_hasta_50 is not None:
        r.estado = "llego"
    elif r.dias_vistos == etiquetas.VENTANA:
        r.estado = "no_llego"
    return r


COLUMNAS = ["fecha", "moneda", "mercado", "simbolo", "listas", "referencia", "maximo", "pct_maximo", "minimo",
            "pct_minimo", "dias_hasta_50", "estado"]


def filas(recons: list[Reconstruida], velas_por_simbolo: dict[tuple[str, str], list[Vela]],
          cubierto: date) -> list[dict]:
    indices = {clave: {v.dia: v for v in velas} for clave, velas in velas_por_simbolo.items()}
    resultado = []
    for c in recons:
        r = etiqueta_diaria(c.fecha, indices[(c.mercado, c.simbolo)], cubierto)
        resultado.append({
            "fecha": c.fecha.isoformat(), "moneda": c.moneda, "mercado": c.mercado, "simbolo": c.simbolo,
            "listas": " ".join(c.listas), "referencia": etiquetas._num(r.referencia),
            "maximo": etiquetas._num(r.maximo), "pct_maximo": etiquetas._num(r.pct(r.maximo), 2),
            "minimo": etiquetas._num(r.minimo), "pct_minimo": etiquetas._num(r.pct(r.minimo), 2),
            "dias_hasta_50": "" if r.dias_hasta_50 is None else str(r.dias_hasta_50), "estado": r.estado,
        })
    return resultado


def escribir(ruta: Path, columnas: list[str], filas_: Iterable[dict]) -> None:
    """CSV comprimido; ``mtime=0`` para que el mismo contenido dé el mismo archivo."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(ruta, "wb", mtime=0) as crudo, io.TextIOWrapper(crudo, encoding="utf-8", newline="") as fh:
        escritor = csv.DictWriter(fh, fieldnames=columnas, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(filas_)


def leer(ruta: Path) -> list[dict]:
    with gzip.open(ruta, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def descargar(binance: Binance, pares: list[Par], hasta: date, carpeta: Path, hilos: int) -> dict[Par, list[Vela]]:
    hechos = 0

    def uno(par: Par) -> tuple[Par, list[Vela]]:
        return par, velas_cacheadas(binance, par, hasta, carpeta)

    resultado = {}
    with ThreadPoolExecutor(max_workers=hilos) as pool:
        for par, velas in pool.map(uno, pares):
            resultado[par] = velas
            hechos += 1
            if hechos % 200 == 0:
                print(f"  velas: {hechos} de {len(pares)} pares", file=sys.stderr)
    return resultado


def _primeras(binance: Binance, pares: list[Par], ruta: Path, hilos: int) -> dict[tuple[str, str], Optional[date]]:
    """Primera vela de cada par (para la edad), guardada en la caché."""
    guardadas = json.loads(ruta.read_text()) if ruta.exists() else {}
    faltan = [p for p in pares if f"{p.mercado}:{p.simbolo}" not in guardadas]
    with ThreadPoolExecutor(max_workers=hilos) as pool:
        for par, primera in zip(faltan, pool.map(lambda p: binance.primera_vela(p.mercado, p.simbolo), faltan)):
            guardadas[f"{par.mercado}:{par.simbolo}"] = primera.isoformat() if primera else None
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(guardadas, sort_keys=True))
    return {(p.mercado, p.simbolo): date.fromisoformat(guardadas[f"{p.mercado}:{p.simbolo}"])
            if guardadas[f"{p.mercado}:{p.simbolo}"] else None for p in pares}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Reconstruye las listas desde 2023 con las reglas por defecto.")
    parser.add_argument("--cache", type=Path, default=CACHE, help="carpeta de la caché de velas diarias")
    parser.add_argument("--salida", type=Path, default=SALIDA)
    parser.add_argument("--hilos", type=int, default=16)
    args = parser.parse_args(argv)

    binance = Binance()
    pares = universo(binance)
    print(f"Universo: {sum(p.mercado == 'spot' for p in pares)} pares spot y "
          f"{sum(p.mercado == 'futures' for p in pares)} de futuros", file=sys.stderr)
    hasta = ultima_vela_cerrada()
    velas = descargar(binance, pares, hasta, args.cache, args.hilos)
    recons = candidatas(velas)
    por_simbolo = {(p.mercado, p.simbolo): v for p, v in velas.items()}
    resultado = filas(recons, por_simbolo, hasta)
    print(f"Candidatas: {len(resultado)}; calculando sus señales", file=sys.stderr)
    primeras = _primeras(binance, pares, args.cache / "primeras.json", args.hilos)
    futuros = senales.Futuros(binance, args.cache / "futuros.jsonl")
    con_senales = senales.calcular(recons, senales.en_que_listas(recons), por_simbolo, primeras,
                                   datetime.now(timezone.utc), futuros, args.hilos)
    for fila, sen in zip(resultado, con_senales):
        fila.update({k: sen[k] for k in ["completa"] + senales.SENALES})
    escribir(args.salida, COLUMNAS + ["completa"] + senales.SENALES, resultado)
    finales = [f for f in resultado if f["estado"] in etiquetas.FINALES]
    llegaron = sum(f["estado"] == "llego" for f in finales)
    print(f"Candidatas: {len(resultado)}; con resultado: {len(finales)}; llegaron a +50 %: {llegaron}")
    for aviso in binance.avisos:
        print(f"Aviso: {aviso}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
