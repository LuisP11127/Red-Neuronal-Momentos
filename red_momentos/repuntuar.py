"""Vuelve a puntuar las listas que se calcularon con un modelo antiguo (con umbral), con el tipo de modelo actual.

    python -m red_momentos.repuntuar

Cada predicción guarda las señales de sus candidatas, así que se pueden puntuar otra vez sin pedir nada a
Binance: el precio y la hora de la lista no cambian. Para que la nueva puntuación no haga trampa, el modelo se
entrena solo con lo que ya tenía resultado antes de la primera de esas listas (con los 11 días de separación de
siempre): el mismo tipo y configuración que ``modelo/red.json``, pero sin haber visto ninguno de esos días. Así,
lo que habría mostrado cada día es comparable con lo que muestra ahora la red cada día.

Cada lista puntuada otra vez guarda en ``repuntuada`` con qué se puntuó y lo que había mostrado antes. Volver a
ejecutarlo da el mismo resultado: solo cambian los días que se calcularon con un modelo antiguo.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from . import red
from .prediccion import CARPETA


def antiguas(carpeta: Path = CARPETA) -> list[tuple[Path, dict]]:
    """Las predicciones hechas con un modelo con umbral (o ya puntuadas otra vez por este módulo)."""
    resultado = []
    for ruta in sorted(carpeta.glob("*.json")):
        p = json.loads(ruta.read_text(encoding="utf-8"))
        if p.get("por_dia") is None or p.get("repuntuada"):
            resultado.append((ruta, p))
    return resultado


def puntuar(p: dict, modelo: red.Red, sello: dict) -> dict:
    """La predicción ``p`` con las puntuaciones, el riesgo y las que muestra ``modelo``, en su nuevo orden."""
    antes = p.get("repuntuada", {}).get("antes") or {"umbral": p.get("umbral"), "mostradas": p.get("mostradas", [])}
    monedas = [dict(m) for m in p.get("monedas", [])]
    if monedas:
        filas = [{**{k: m["senales"].get(k) for k in m["senales"]}, "mercado": m["mercado"]} for m in monedas]
        x = red.matriz(filas, modelo.entradas)
        puntos, riesgo = modelo.puntuar(x), modelo.puntuar_riesgo(x)
        orden, mostrar = modelo.orden(puntos, riesgo), modelo.mostrar(puntos, riesgo)
        for i, m in enumerate(monedas):
            m["puntuacion"] = round(float(puntos[i]), 4)
            m["riesgo"] = None if riesgo is None else round(float(riesgo[i]), 4)
            m["mostrar"] = bool(mostrar[i])
            m["_orden"] = float(orden[i])
        monedas.sort(key=lambda m: -m.pop("_orden"))
    # Las claves de una predicción nueva, en el mismo orden, y al final con qué se puntuó.
    nueva = {k: p[k] for k in ("fecha", "vela_utc", "hora") if k in p}
    nueva.update({"umbral": None, "por_dia": modelo.por_dia, "mostradas": [m["moneda"] for m in monedas if m["mostrar"]],
                  "monedas": monedas, "repuntuada": {**sello, "antes": antes}})
    return nueva


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Vuelve a puntuar las listas calculadas con un modelo antiguo.")
    parser.add_argument("--carpeta", type=Path, default=CARPETA)
    parser.add_argument("--modelo", type=Path, default=red.MODELO)
    parser.add_argument("--reconstruccion", type=Path, default=red.RECONSTRUCCION)
    args = parser.parse_args(argv)

    pendientes = antiguas(args.carpeta)
    if not pendientes:
        print("No hay listas calculadas con un modelo antiguo.")
        return 0
    actual = json.loads(args.modelo.read_text(encoding="utf-8"))
    nombre = actual.get("informe", {}).get("modelo")
    if nombre not in red.CANDIDATOS:
        print(f"El modelo actual ({args.modelo}) no dice qué tipo es: entrénalo antes con python -m red_momentos.red.",
              file=sys.stderr)
        return 1
    primera = date.fromisoformat(pendientes[0][1]["fecha"])
    todo = red.unir(red.leer_reconstruccion(args.reconstruccion), red.leer_reales())
    previo = red._antes(todo, primera)
    hasta = previo.fechas.max().astype(date).isoformat()
    print(f"Entrenando {red.NOMBRES[nombre]} con {len(previo)} filas, hasta el {hasta} (antes de la lista del {primera})",
          file=sys.stderr)
    modelo = red.entrenar_red(previo, red.CANDIDATOS[nombre])
    sello = {"modelo": nombre, "datos_hasta": hasta,
             "hora": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    for ruta, p in pendientes:
        nueva = puntuar(p, modelo, sello)
        ruta.write_text(json.dumps(nueva, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{nueva['fecha']}: antes {', '.join(nueva['repuntuada']['antes']['mostradas']) or 'ninguna'}; "
              f"ahora {', '.join(nueva['mostradas']) or 'ninguna'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
