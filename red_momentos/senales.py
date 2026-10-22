"""Señales de cada candidata a las 19:30 hora Lima (00:30 UTC), solo con lo que se sabía a esa hora.

**Velas diarias**, hasta la del día de la lista (cerrada a las 19:00 en Lima):

- ``dist_ma7``, ``dist_ma25``, ``dist_ma99``: cierre frente a cada media (%); ``ma7_ma25``, ``ma25_ma99``:
  distancia entre medias (%); ``velas_sobre_ma7``: velas seguidas cerrando sobre la MA(7);
- ``var_1d`` (apertura → cierre), ``rango_1d`` (mínimo → máximo), ``mecha_sup``, ``mecha_inf`` (parte del
  rango), ``var_3d``, ``var_7d``, ``var_30d``, ``volatilidad_14d``;
- ``vol_rel_1d`` (volumen del día frente a la media de 20 días), ``vol_rel_7d``, ``vol_usdt_log``,
  ``operaciones_rel``, ``taker_1d`` y ``taker_7d`` (parte del volumen que fueron compras a mercado);
- ``dist_max_30d``, ``dist_min_30d``, ``dist_max_365d``;
- ``explosiones_30d``, ``explosiones_90d`` (velas de +10 % o más de mínimo a máximo, como Scanner-pump),
  ``max_rango_90d``, ``dias_desde_explosion`` (la anterior), ``explosiones50_365d`` (velas de +50 %);
- ``edad_dias``: días desde la primera vela del par (hasta 730).

**Listas:** ``en_a``, ``en_b`` y en cuántos de los 7 días anteriores salió en cada una.

**Futuros** (archivos de data.binance.vision; en spot quedan vacías):

- libro de órdenes, la última foto antes de las 00:30 UTC (``bookDepth``): ``libro_deseq_02``,
  ``libro_deseq_1``, ``libro_deseq_2``, ``libro_deseq_5`` (parte de compras en USDT a ±0,2/1/2/5 % del
  precio), ``libro_prof_2`` (USDT a ±2 % frente al volumen del día), ``libro_conc_compras`` y
  ``libro_conc_ventas`` (lo que hay a 1 % frente a lo que hay a 5 %);
- ``metrics``: ``oi_rel_vol`` (interés abierto en USDT frente al volumen del día), ``oi_cambio_dia``
  (cambio del interés abierto durante la vela), ``ls_top_cuentas``, ``ls_top_posiciones``, ``ls_global``
  (relaciones long/short a las 00:30) y ``taker_ls`` (compras/ventas a mercado, mediana del día).
"""

from __future__ import annotations

import csv
import json
import math
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from .binance import VISION, Binance, Vela
from .fechas import UN_DIA, vela_utc

DIARIAS = ["dist_ma7", "dist_ma25", "dist_ma99", "ma7_ma25", "ma25_ma99", "velas_sobre_ma7", "var_1d", "rango_1d",
           "mecha_sup", "mecha_inf", "var_3d", "var_7d", "var_30d", "volatilidad_14d", "vol_rel_1d", "vol_rel_7d",
           "vol_usdt_log", "operaciones_rel", "taker_1d", "taker_7d", "dist_max_30d", "dist_min_30d",
           "dist_max_365d", "explosiones_30d", "explosiones_90d", "max_rango_90d", "dias_desde_explosion",
           "explosiones50_365d", "edad_dias"]
LISTAS = ["en_a", "en_b", "dias_en_a_7d", "dias_en_b_7d"]
LIBRO = ["libro_deseq_02", "libro_deseq_1", "libro_deseq_2", "libro_deseq_5", "libro_prof_2",
         "libro_conc_compras", "libro_conc_ventas"]
METRICAS = ["oi_rel_vol", "oi_cambio_dia", "ls_top_cuentas", "ls_top_posiciones", "ls_global", "taker_ls"]
SENALES = DIARIAS + LISTAS + LIBRO + METRICAS

EXPLOSION = 10.0  # %
HISTORIAL = 400  # días de velas diarias antes de la vela del día
EDAD_MAX = 730
ANTIGUEDAD_LIBRO = timedelta(minutes=30)  # foto del libro más antigua que se acepta
ANTIGUEDAD_METRICAS = timedelta(hours=6)


def diarias(velas: list[Vela], primera: Optional[date] = None) -> pd.DataFrame:
    """Señales de velas diarias para cada vela (fila = día UTC en que abre), con esa vela y las anteriores."""
    df = pd.DataFrame([(v.dia, v.open, v.high, v.low, v.close, v.volumen_usdt, v.operaciones, v.compra_taker_usdt)
                       for v in velas], columns=["dia", "o", "h", "l", "c", "qv", "n", "tq"]).set_index("dia")
    o, h, l, c, qv, n, tq = (df[k] for k in ("o", "h", "l", "c", "qv", "n", "tq"))
    ma7, ma25, ma99 = (c.rolling(k).mean() for k in (7, 25, 99))
    rango = (h / l - 1) * 100
    f = pd.DataFrame(index=df.index)
    f["dist_ma7"], f["dist_ma25"], f["dist_ma99"] = ((c / m - 1) * 100 for m in (ma7, ma25, ma99))
    f["ma7_ma25"], f["ma25_ma99"] = (ma7 / ma25 - 1) * 100, (ma25 / ma99 - 1) * 100
    sobre = (c >= ma7).astype(int)
    f["velas_sobre_ma7"] = sobre.groupby((sobre == 0).cumsum()).cumsum().where(ma7.notna())
    f["var_1d"], f["rango_1d"] = (c / o - 1) * 100, rango
    alto = (h - l).replace(0, np.nan)
    f["mecha_sup"] = (h - np.maximum(o, c)) / alto
    f["mecha_inf"] = (np.minimum(o, c) - l) / alto
    for k in (3, 7, 30):
        f[f"var_{k}d"] = (c / c.shift(k) - 1) * 100
    f["volatilidad_14d"] = c.pct_change().rolling(14).std() * 100
    f["vol_rel_1d"] = qv / qv.shift(1).rolling(20).mean()
    f["vol_rel_7d"] = qv.rolling(7).mean() / qv.shift(7).rolling(28).mean()
    f["vol_usdt_log"] = np.log10(qv + 1)
    f["operaciones_rel"] = n / n.shift(1).rolling(20).mean()
    f["taker_1d"] = tq / qv
    f["taker_7d"] = tq.rolling(7).sum() / qv.rolling(7).sum()
    f["dist_max_30d"] = (c / h.rolling(30, min_periods=1).max() - 1) * 100
    f["dist_min_30d"] = (c / l.rolling(30, min_periods=1).min() - 1) * 100
    f["dist_max_365d"] = (c / h.rolling(365, min_periods=30).max() - 1) * 100
    explosion = (rango >= EXPLOSION).astype(int)
    f["explosiones_30d"] = explosion.rolling(30, min_periods=1).sum()
    f["explosiones_90d"] = explosion.rolling(90, min_periods=1).sum()
    f["max_rango_90d"] = rango.rolling(90, min_periods=1).max()
    ordinal = pd.Series([d.toordinal() for d in df.index], index=df.index, dtype=float)
    anterior = ordinal.where(explosion == 1).shift(1).ffill()
    f["dias_desde_explosion"] = ordinal - anterior
    f["explosiones50_365d"] = (rango >= 50).astype(int).rolling(365, min_periods=1).sum()
    if primera is not None:
        f["edad_dias"] = (ordinal - primera.toordinal()).clip(upper=EDAD_MAX)
    else:
        f["edad_dias"] = np.nan
    f["_qv"] = qv  # volumen del día en USDT (para el libro y las métricas; no es una señal)
    return f.replace([np.inf, -np.inf], np.nan)


def de_listas(fecha: date, en: dict[str, set[date]]) -> dict[str, float]:
    """``en``: días en que la moneda salió en cada lista (``momento-a`` y ``momento-b``)."""
    a, b = en.get("momento-a", set()), en.get("momento-b", set())
    semana = {fecha - timedelta(days=k) for k in range(1, 8)}
    return {"en_a": float(fecha in a), "en_b": float(fecha in b),
            "dias_en_a_7d": float(len(a & semana)), "dias_en_b_7d": float(len(b & semana))}


def referencia(fecha: date) -> datetime:
    """Las 00:30 UTC (19:30 en Lima) tras el cierre de la vela del día de la lista."""
    dia = vela_utc(fecha) + UN_DIA
    return datetime(dia.year, dia.month, dia.day, 0, 30, tzinfo=timezone.utc)


def _texto(momento: datetime) -> str:
    return momento.strftime("%Y-%m-%d %H:%M:%S")


def del_libro(filas: Optional[list[list[str]]], instante: datetime, volumen_dia: float) -> dict[str, float]:
    """Señales de la última foto del libro (``bookDepth``) antes de ``instante``."""
    vacias = {k: math.nan for k in LIBRO}
    if not filas:
        return vacias
    hasta, desde = _texto(instante), _texto(instante - ANTIGUEDAD_LIBRO)
    fotos = [f for f in filas if f[0][:1].isdigit() and desde <= f[0] <= hasta]
    if not fotos:
        return vacias
    ultima = fotos[-1][0]
    usdt = {float(f[1]): float(f[3]) for f in fotos if f[0] == ultima}

    def deseq(p: float) -> float:
        compras, ventas = usdt.get(-p), usdt.get(p)
        if compras is None or ventas is None or compras + ventas <= 0:
            return math.nan
        return compras / (compras + ventas)

    def cociente(a: Optional[float], b: Optional[float]) -> float:
        return a / b if a is not None and b else math.nan

    prof = usdt.get(-2.0, math.nan) + usdt.get(2.0, math.nan)
    return {
        "libro_deseq_02": deseq(0.2), "libro_deseq_1": deseq(1.0), "libro_deseq_2": deseq(2.0),
        "libro_deseq_5": deseq(5.0), "libro_prof_2": prof / volumen_dia if volumen_dia else math.nan,
        "libro_conc_compras": cociente(usdt.get(-1.0), usdt.get(-5.0)),
        "libro_conc_ventas": cociente(usdt.get(1.0), usdt.get(5.0)),
    }


@dataclass
class ResumenMetricas:
    """Lo que hace falta de un archivo diario de ``metrics``."""
    primera: Optional[list[str]] = None
    ultima: Optional[list[str]] = None
    taker_mediana: float = math.nan
    madrugada: tuple[tuple[str, ...], ...] = ()  # filas hasta las 00:30 UTC


def _f(valor: str) -> float:
    """Número de un campo de ``metrics`` (a veces viene vacío)."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        return math.nan


def resumir(filas: Optional[list[list[str]]], hasta: str = "00:30:00") -> ResumenMetricas:
    """Resume un día de ``metrics``. ``madrugada`` son sus filas hasta la hora ``hasta`` (HH:MM:SS)."""
    datos = [f for f in filas or [] if len(f) >= 8 and f[0][:1].isdigit()]
    con_oi = [f for f in datos if not math.isnan(_f(f[2]))]  # a veces una fila trae solo algunos campos
    taker = [x for x in (_f(f[7]) for f in datos) if not math.isnan(x)]
    return ResumenMetricas(con_oi[0] if con_oi else None, con_oi[-1] if con_oi else None,
                           float(np.median(taker)) if taker else math.nan,
                           tuple(tuple(f) for f in con_oi if f[0][11:] <= hasta))


def de_metricas(dia: ResumenMetricas, siguiente: ResumenMetricas, instante: datetime,
                volumen_dia: float) -> dict[str, float]:
    """Señales de ``metrics``: ``dia`` resume el día de la vela y ``siguiente``, el día de las 00:30."""
    resultado = {k: math.nan for k in METRICAS}
    hasta, desde = _texto(instante), _texto(instante - ANTIGUEDAD_METRICAS)
    previas = [f for f in ([dia.ultima] if dia.ultima else []) + list(siguiente.madrugada) if desde <= f[0] <= hasta]
    if previas:
        ultima = max(previas, key=lambda f: f[0])
        resultado["oi_rel_vol"] = _f(ultima[3]) / volumen_dia if volumen_dia else math.nan
        resultado["ls_top_cuentas"], resultado["ls_top_posiciones"], resultado["ls_global"] = (
            _f(ultima[4]), _f(ultima[5]), _f(ultima[6]))
    if dia.primera and dia.ultima:
        inicio, fin = (datetime.strptime(f[0], "%Y-%m-%d %H:%M:%S") for f in (dia.primera, dia.ultima))
        if fin - inicio >= timedelta(hours=6) and _f(dia.primera[2]) > 0:
            resultado["oi_cambio_dia"] = (_f(dia.ultima[2]) / _f(dia.primera[2]) - 1) * 100
        resultado["taker_ls"] = dia.taker_mediana
    return resultado


class Futuros:
    """Libro y métricas de futuros de data.binance.vision.

    Guarda en memoria el resumen de cada archivo de métricas (los días seguidos de un par comparten
    archivos) y, si se le da un archivo, las señales ya calculadas de cada par y día, para poder retomar.
    """

    def __init__(self, binance: Binance, cache: Optional[Path] = None) -> None:
        self.binance = binance
        self._metricas: dict[tuple[str, date], ResumenMetricas] = {}
        self._lock = threading.Lock()
        self._cache = cache
        self._hechas: dict[str, dict[str, float]] = {}
        if cache and cache.exists():
            with cache.open(encoding="utf-8") as fh:
                for linea in fh:
                    clave, valores = json.loads(linea)
                    self._hechas[clave] = {k: math.nan if v is None else v for k, v in valores.items()}

    def _url(self, tipo: str, simbolo: str, dia: date) -> str:
        return f"{VISION}/futures/um/daily/{tipo}/{simbolo}/{simbolo}-{tipo}-{dia:%Y-%m-%d}.zip"

    def libro(self, simbolo: str, instante: datetime) -> Optional[list[list[str]]]:
        limite = _texto(instante)
        return self.binance.inicio_csv(self._url("bookDepth", simbolo, instante.date()),
                                       lambda filas: filas[-1][0] > limite)

    def metricas(self, simbolo: str, dia: date) -> ResumenMetricas:
        clave = (simbolo, dia)
        with self._lock:
            if clave in self._metricas:
                return self._metricas[clave]
        resumen = resumir(self.binance._zip(self._url("metrics", simbolo, dia), solo_velas=False))
        with self._lock:
            if len(self._metricas) > 50_000:
                self._metricas.clear()
            self._metricas[clave] = resumen
        return resumen

    def senales(self, simbolo: str, fecha: date, volumen_dia: float) -> dict[str, float]:
        clave = f"{simbolo}|{fecha.isoformat()}"
        with self._lock:
            if clave in self._hechas:
                return self._hechas[clave]
        instante = referencia(fecha)
        dia = vela_utc(fecha)
        datos = del_libro(self.libro(simbolo, instante), instante, volumen_dia)
        datos.update(de_metricas(self.metricas(simbolo, dia), self.metricas(simbolo, dia + UN_DIA), instante,
                                 volumen_dia))
        with self._lock:
            self._hechas[clave] = datos
            if self._cache:
                self._cache.parent.mkdir(parents=True, exist_ok=True)
                with self._cache.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps([clave, {k: None if math.isnan(v) else v for k, v in datos.items()}]) + "\n")
        return datos


def publicado(fecha: date, ahora: datetime) -> bool:
    """Si data.binance.vision ya publicó el día de las 00:30 de esa fecha (sale al día siguiente, ~08:10 UTC)."""
    return ahora >= referencia(fecha).replace(minute=0) + timedelta(days=1, hours=10)


def numero(valor: float) -> str:
    return "" if valor is None or (isinstance(valor, float) and math.isnan(valor)) else f"{valor:.6g}"


COLUMNAS = ["fecha", "moneda", "mercado", "simbolo", "completa"] + SENALES


@dataclass
class Fila:
    fecha: date
    moneda: str
    mercado: str
    simbolo: str
    listas: tuple[str, ...]


def calcular(candidatas: Iterable[Fila], en_listas: dict[str, dict[str, set[date]]],
             velas: dict[tuple[str, str], list[Vela]], primeras: dict[tuple[str, str], Optional[date]],
             ahora: datetime, futuros, hilos: int = 16, en_vivo: bool = False) -> list[dict]:
    """Señales de cada candidata. ``velas``: velas diarias de cada par (mercado, símbolo) que cubren su fecha.

    ``futuros`` da el libro y las métricas (``Futuros`` o ``prediccion.FuturosEnVivo``). ``completa`` es 1 si
    ya estaba todo publicado; si no, se vuelve a calcular otro día. Con ``en_vivo`` se piden siempre.
    """
    candidatas = list(candidatas)
    por_par: dict[tuple[str, str], list[Fila]] = defaultdict(list)
    for c in candidatas:
        por_par[(c.mercado, c.simbolo)].append(c)

    datos: dict[tuple[date, str], dict[str, float]] = {}
    volumenes: dict[tuple[date, str], float] = {}
    con_velas: set[tuple[date, str]] = set()
    for par, filas_par in por_par.items():
        tabla = diarias(velas[par], primeras.get(par)) if velas.get(par) else None
        for c in filas_par:
            clave = (c.fecha, c.moneda)
            datos[clave] = {k: math.nan for k in SENALES}
            dia = vela_utc(c.fecha)
            if tabla is not None and dia in tabla.index:
                fila = tabla.loc[dia]
                datos[clave].update({k: float(fila[k]) for k in DIARIAS})
                volumenes[clave] = float(fila["_qv"])
                con_velas.add(clave)
            datos[clave].update(de_listas(c.fecha, en_listas.get(c.moneda, {})))

    de_futuros = [c for c in candidatas if c.mercado == "futures" and (en_vivo or publicado(c.fecha, ahora))]

    def una(c: Fila) -> tuple[tuple[date, str], dict[str, float]]:
        clave = (c.fecha, c.moneda)
        return clave, futuros.senales(c.simbolo, c.fecha, volumenes.get(clave, math.nan))

    with ThreadPoolExecutor(max_workers=hilos) as pool:
        for hechas, (clave, valores) in enumerate(pool.map(una, de_futuros), start=1):
            datos[clave].update(valores)
            if hechas % 5000 == 0:
                print(f"  futuros: {hechas} de {len(de_futuros)}", file=sys.stderr, flush=True)

    return [{"fecha": c.fecha.isoformat(), "moneda": c.moneda, "mercado": c.mercado, "simbolo": c.simbolo,
             "completa": "1" if publicado(c.fecha, ahora) and (c.fecha, c.moneda) in con_velas else "0",
             **{k: numero(datos[(c.fecha, c.moneda)][k]) for k in SENALES}} for c in candidatas]


def leer_csv(ruta: Path) -> dict[tuple[str, str], dict]:
    if not ruta.exists():
        return {}
    with ruta.open(encoding="utf-8", newline="") as fh:
        return {(f["fecha"], f["moneda"]): f for f in csv.DictReader(fh)}


def escribir_csv(ruta: Path, filas: Iterable[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as fh:
        escritor = csv.DictWriter(fh, fieldnames=COLUMNAS, lineterminator="\n")
        escritor.writeheader()
        escritor.writerows(filas)


SALIDA = Path("datos/senales.csv")


def en_que_listas(filas: Iterable) -> dict[str, dict[str, set[date]]]:
    """Moneda → lista → días en que salió (de cualquier objeto con ``fecha``, ``moneda`` y ``listas``)."""
    resultado: dict[str, dict[str, set[date]]] = defaultdict(lambda: defaultdict(set))
    for f in filas:
        for lista in f.listas:
            resultado[f.moneda][lista].add(f.fecha)
    return resultado


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    from . import listas

    parser = argparse.ArgumentParser(description="Señales de las candidatas de las listas reales a las 19:30.")
    parser.add_argument("--listas", type=Path, default=listas.RAIZ_LISTAS)
    parser.add_argument("--salida", type=Path, default=SALIDA)
    parser.add_argument("--hilos", type=int, default=16)
    args = parser.parse_args(argv)

    candidatas = listas.candidatas(args.listas)
    anteriores = leer_csv(args.salida)
    ahora = datetime.now(timezone.utc)
    hechas = {k: f for k, f in anteriores.items() if f.get("completa") == "1"}
    nuevas = [Fila(c.fecha, c.moneda, c.mercado, c.simbolo, c.listas) for c in candidatas
              if (c.fecha.isoformat(), c.moneda) not in hechas
              or (hechas[(c.fecha.isoformat(), c.moneda)]["mercado"], hechas[(c.fecha.isoformat(), c.moneda)]["simbolo"])
              != (c.mercado, c.simbolo)]

    binance = Binance()
    pares = sorted({(c.mercado, c.simbolo) for c in nuevas})
    fechas_par: dict[tuple[str, str], list[date]] = defaultdict(list)
    for c in nuevas:
        fechas_par[(c.mercado, c.simbolo)].append(vela_utc(c.fecha))

    def bajar(par: tuple[str, str]) -> tuple[tuple[str, str], list[Vela], Optional[date]]:
        dias = fechas_par[par]
        velas, _ = binance.velas_diarias(par[0], par[1], min(dias) - timedelta(days=HISTORIAL), max(dias))
        return par, velas, binance.primera_vela(*par)

    velas, primeras = {}, {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for par, v, primera in pool.map(bajar, pares):
            velas[par], primeras[par] = v, primera

    calculadas = calcular(nuevas, en_que_listas(candidatas), velas, primeras, ahora, Futuros(binance), args.hilos)
    todas = {**hechas, **{(f["fecha"], f["moneda"]): f for f in calculadas}}
    vigentes = {(c.fecha.isoformat(), c.moneda) for c in candidatas}
    escribir_csv(args.salida, [todas[k] for k in sorted(todas) if k in vigentes])
    print(f"Señales: {len(calculadas)} filas calculadas ({sum(f['completa'] == '1' for f in calculadas)} completas); "
          f"{len(hechas)} ya estaban.")
    for aviso in binance.avisos:
        print(f"Aviso: {aviso}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
