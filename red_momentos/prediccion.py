"""Predicción diaria de las 19:30 (hora Lima, 00:30 UTC).

Puntúa las monedas de Momento-A y Momento-B del día cuya vela acaba de cerrar, con las señales de ese
momento, y guarda ``predicciones/AAAA-MM-DD.json`` (fecha del día de las listas) con todas las candidatas, su
puntuación, el precio a esa hora y las que pasan el umbral de la red.

Las señales son las mismas que en ``datos/senales.csv``, pero el libro y las métricas de futuros salen de la
API de Binance, porque los archivos de data.binance.vision se publican al día siguiente:

- libro: una foto en ese momento (``/fapi/v1/depth``, hasta 1000 niveles por lado), con lo que hay en
  órdenes a ±0,2, 1, 2, 3, 4 y 5 % del precio medio. Si los 1000 niveles no llegan al borde de una banda
  (pasa en las monedas muy líquidas), esa banda queda vacía;
- métricas: las del día de la vela y lo que va del siguiente (``/futures/data/...``), con las mismas
  columnas que los archivos ``metrics``.

Cada predicción guarda también sus señales, para compararlas con las de ``datos/senales.csv`` de la misma
moneda cuando se publiquen. Si el día ya tiene predicción no se repite (conserva el precio de la primera),
salvo con ``--forzar``.

    python -m red_momentos.prediccion [--forzar]
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import listas, red, senales
from .binance import Binance
from .fechas import UN_DIA, dia_lista, ms, ultima_vela_cerrada, vela_utc

CARPETA = Path("predicciones")
BANDAS = (0.2, 1.0, 2.0, 3.0, 4.0, 5.0)
METRICAS_API = [  # (endpoint, campo) en el orden de las columnas de los archivos metrics
    ("openInterestHist", "sumOpenInterest"), ("openInterestHist", "sumOpenInterestValue"),
    ("topLongShortAccountRatio", "longShortRatio"), ("topLongShortPositionRatio", "longShortRatio"),
    ("globalLongShortAccountRatio", "longShortRatio"), ("takerlongshortRatio", "buySellRatio"),
]


def _texto(milisegundos: int) -> str:
    return datetime.fromtimestamp(milisegundos / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def bandas_del_libro(libro: dict, instante: datetime) -> list[list[str]]:
    """Una foto del libro de la API con el formato de ``bookDepth`` (USDT acumulados a ±p % del precio medio)."""
    compras = [(float(p), float(q)) for p, q in libro.get("bids") or []]
    ventas = [(float(p), float(q)) for p, q in libro.get("asks") or []]
    if not compras or not ventas:
        return []
    medio = (compras[0][0] + ventas[0][0]) / 2
    momento = instante.strftime("%Y-%m-%d %H:%M:%S")
    filas = []
    for p in BANDAS:
        limite = medio * (1 - p / 100)
        if compras[-1][0] <= limite:  # el libro descargado llega al borde de la banda
            filas.append([momento, f"{-p:.2f}", "", str(sum(pr * q for pr, q in compras if pr >= limite))])
        limite = medio * (1 + p / 100)
        if ventas[-1][0] >= limite:
            filas.append([momento, f"{p:.2f}", "", str(sum(pr * q for pr, q in ventas if pr <= limite))])
    return filas


class FuturosEnVivo:
    """Libro y métricas de futuros de la API, con la misma interfaz que ``senales.Futuros``."""

    def __init__(self, binance: Binance, ahora: datetime) -> None:
        self.binance = binance
        self.ahora = ahora

    def _metricas(self, simbolo: str, desde: int, hasta: int) -> list[list[str]]:
        """Filas con las columnas de los archivos ``metrics``, a partir de los endpoints de la API."""
        por_momento: dict[int, list[str]] = {}
        for ruta in dict.fromkeys(r for r, _ in METRICAS_API):
            datos = self.binance._get("futures", f"/futures/data/{ruta}", {
                "symbol": simbolo, "period": "5m", "startTime": desde, "endTime": hasta, "limit": 500})
            for d in datos:
                t = int(d["timestamp"])
                fila = por_momento.setdefault(t, [_texto(t), simbolo] + [""] * len(METRICAS_API))
                for columna, (r, campo) in enumerate(METRICAS_API, start=2):
                    if r == ruta:
                        fila[columna] = str(d.get(campo, ""))
        return [por_momento[t] for t in sorted(por_momento)]

    def senales(self, simbolo: str, fecha: date, volumen_dia: float) -> dict[str, float]:
        instante = self.ahora
        dia = vela_utc(fecha)
        libro = self.binance._get("futures", "/fapi/v1/depth", {"symbol": simbolo, "limit": 1000}, forma=dict)
        datos = senales.del_libro(bandas_del_libro(libro, instante), instante + timedelta(seconds=1), volumen_dia)
        # Un día por petición (la API da como mucho 500 filas de 5 minutos, las más recientes).
        ahora_ms = int(instante.timestamp() * 1000)
        del_dia = self._metricas(simbolo, ms(dia), ms(dia + UN_DIA) - 1)
        siguiente = self._metricas(simbolo, ms(dia + UN_DIA), ahora_ms)
        datos.update(senales.de_metricas(senales.resumir(del_dia),
                                         senales.resumir(siguiente, hasta=instante.strftime("%H:%M:%S")),
                                         instante + timedelta(seconds=1), volumen_dia))
        return datos


def precio(binance: Binance, mercado: str, simbolo: str) -> Optional[float]:
    ruta = "/api/v3/ticker/price" if mercado == "spot" else "/fapi/v1/ticker/price"
    try:
        return float(binance._get(mercado, ruta, {"symbol": simbolo}, forma=dict)["price"])
    except (KeyError, ValueError, RuntimeError):
        return None


def predecir(fecha: date, binance: Binance, modelo: red.Red, ahora: datetime,
             raiz_listas: Path = listas.RAIZ_LISTAS) -> dict:
    todas = listas.candidatas(raiz_listas)
    del_dia = [c for c in todas if c.fecha == fecha]
    filas = [senales.Fila(c.fecha, c.moneda, c.mercado, c.simbolo, c.listas) for c in del_dia]
    dia = vela_utc(fecha)

    def bajar(par: tuple[str, str]):
        velas, _ = binance.velas_diarias(par[0], par[1], dia - timedelta(days=senales.HISTORIAL), dia)
        return par, [v for v in velas if v.dia <= dia], binance.primera_vela(*par)

    velas, primeras = {}, {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for par, v, primera in pool.map(bajar, sorted({(f.mercado, f.simbolo) for f in filas})):
            velas[par], primeras[par] = v, primera

    calculadas = senales.calcular(filas, senales.en_que_listas(todas), velas, primeras, ahora,
                                  FuturosEnVivo(binance, ahora), hilos=8, en_vivo=True)
    puntos = modelo.puntuar(red.matriz(calculadas)) if calculadas else []
    monedas = []
    for c, fila, p in zip(del_dia, calculadas, puntos):
        monedas.append({
            "moneda": c.moneda, "mercado": c.mercado, "simbolo": c.simbolo, "listas": list(c.listas),
            "puntuacion": round(float(p), 4), "mostrar": modelo.umbral is not None and float(p) >= modelo.umbral,
            "precio": precio(binance, c.mercado, c.simbolo),
            "senales": {k: (float(fila[k]) if fila[k] != "" else None) for k in senales.SENALES},
        })
    monedas.sort(key=lambda m: -m["puntuacion"])
    return {"fecha": fecha.isoformat(), "vela_utc": dia.isoformat(),
            "hora": ahora.strftime("%Y-%m-%dT%H:%M:%SZ"), "umbral": modelo.umbral,
            "mostradas": [m["moneda"] for m in monedas if m["mostrar"]], "monedas": monedas}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Lista de la red para el día cuya vela acaba de cerrar.")
    parser.add_argument("--modelo", type=Path, default=red.MODELO)
    parser.add_argument("--carpeta", type=Path, default=CARPETA)
    parser.add_argument("--forzar", action="store_true", help="rehacer la predicción si el día ya la tiene")
    args = parser.parse_args(argv)

    if not args.modelo.exists():
        print(f"No hay modelo en {args.modelo}: primero hay que entrenar la red.", file=sys.stderr)
        return 0
    ahora = datetime.now(timezone.utc)
    fecha = dia_lista(ultima_vela_cerrada(ahora))
    ruta = args.carpeta / f"{fecha.isoformat()}.json"
    if ruta.exists() and not args.forzar:
        print(f"El día {fecha} ya tiene predicción ({ruta}).")
        return 0
    binance = Binance()
    resultado = predecir(fecha, binance, red.Red.cargar(args.modelo), ahora)
    if not resultado["monedas"]:
        print(f"Las listas del {fecha} están vacías: no hay nada que predecir.")
        return 0
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(resultado, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    mostradas = resultado["mostradas"]
    print(f"Predicción del {fecha}: {len(resultado['monedas'])} candidatas; "
          + (f"la red muestra {len(mostradas)}: {', '.join(mostradas)}" if mostradas else "ninguna pasa el umbral"))
    for aviso in binance.avisos:
        print(f"Aviso: {aviso}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
