"""Web de la red (GitHub Pages): la lista del día, el seguimiento de sus predicciones y tus estrellas.

    python -m red_momentos.web sitio

Escribe ``sitio/index.html`` y ``sitio/datos.json`` con:

- las predicciones de cada día (``predicciones/*.json``, sin las señales);
- el resultado a 10 días de cada candidata de esas listas (mínimo, máximo y si llegó a +50 %), medido desde la
  hora y el precio de la lista (``predicciones/resultados.csv``; si aún no terminó, hasta dónde va);
- las estrellas de cada día, de las listas copiadas (la red no las usa: se muestran al lado);
- el resumen del informe de la red (``modelo/red.json``).

La página pide a Binance, desde el navegador, el precio actual, el mínimo y el máximo desde la hora de la lista de
las monedas de los últimos 10 días, y las velas de los gráficos (de 1h a 1D).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import aciertos, listas, red

PLANTILLA = Path(__file__).with_name("web.html")
PREDICCIONES = Path("predicciones")


def estrellas(raiz: Path = listas.RAIZ_LISTAS) -> list[str]:
    """``"AAAA-MM-DD|MONEDA"`` de cada moneda con estrella en su día (Momento-A o Momento-B)."""
    resultado = set()
    for fecha, filas in listas.leer("momento-a", raiz).items():
        for fila in filas:
            if fila.get("estrella"):
                resultado.add(f"{fecha.isoformat()}|{listas.moneda(fila)}")
    ruta = raiz / "momento-b" / "estrellas.json"
    if ruta.exists():
        for clave, valor in json.loads(ruta.read_text(encoding="utf-8")).get("estrellas", {}).items():
            fecha, _, par = clave.partition("|")
            simbolo = par.partition(":")[2]
            if valor.get("activa") and simbolo:
                resultado.add(f"{fecha}|{listas.moneda({'simbolo': simbolo, 'base': simbolo.removesuffix('USDT')})}")
    return sorted(resultado)


def _modelo(ruta: Path) -> Optional[dict]:
    if not ruta.exists():
        return None
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    informe = datos.get("informe", {})
    evaluacion = informe.get("evaluacion", {})
    return {"umbral": datos.get("umbral"), "tramos": informe.get("tramos"),
            "validacion": evaluacion.get("validacion"), "prueba": evaluacion.get("prueba: listas reales")}


def construir(destino: Path, predicciones: Path = PREDICCIONES, resultados_csv: Path = aciertos.SALIDA,
              modelo: Path = red.MODELO, raiz_listas: Path = listas.RAIZ_LISTAS,
              ahora: Optional[datetime] = None) -> dict:
    dias = []
    for ruta in sorted(predicciones.glob("*.json"), reverse=True) if predicciones.exists() else []:
        p = json.loads(ruta.read_text(encoding="utf-8"))
        dias.append({**{k: p.get(k) for k in ("fecha", "vela_utc", "hora", "umbral")},
                     "monedas": [{k: m.get(k) for k in ("moneda", "mercado", "simbolo", "listas", "puntuacion",
                                                        "mostrar", "precio")} for m in p.get("monedas", [])]})
    predichas = {(d["fecha"], m["moneda"]) for d in dias for m in d["monedas"]}
    resultados = {}
    for (fecha, nombre), fila in aciertos.leer_csv(resultados_csv).items():
        if (fecha, nombre) in predichas:
            resultados[f"{fecha}|{nombre}"] = {"estado": fila["estado"], "referencia": fila["precio"],
                                               **{k: fila[k] for k in ("pct_maximo", "pct_minimo", "dias_hasta_50",
                                                                         "dias_vistos")}}
    datos = {"generado": (ahora or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "dias": dias, "resultados": resultados, "estrellas": estrellas(raiz_listas), "modelo": _modelo(modelo)}
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "datos.json").write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    shutil.copyfile(PLANTILLA, destino / "index.html")
    return datos


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Genera la web de la red.")
    parser.add_argument("destino", type=Path)
    args = parser.parse_args(argv)
    datos = construir(args.destino)
    print(f"Web en {args.destino}: {len(datos['dias'])} días de predicciones, {len(datos['estrellas'])} estrellas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
