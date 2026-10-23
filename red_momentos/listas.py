"""Copia de las listas de seguimiento de Momento-A, Momento-B y Scanner-pump.

Cada repositorio guarda un archivo por día (``AAAA-MM-DD.json``) con las monedas de su lista. Aquí se
copian tal cual a ``datos/listas/<fuente>/``: los días nuevos o cambiados se sobrescriben y los que se
borraron en el repositorio de origen (botón **Borrar** de su web) se borran también aquí.

    python -m red_momentos.listas --momento-a RUTA --momento-b RUTA --scanner-pump RUTA

Las candidatas de la red salen de Momento-A y Momento-B; Scanner-pump sirve para comparar.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Fuente:
    clave: str
    repo: str
    carpeta: str  # carpeta del seguimiento dentro de su repositorio


FUENTES = (
    Fuente("momento-a", "LuisP11127/Momento-A", "docs/seguimiento"),
    Fuente("momento-b", "LuisP11127/Momento-B", "docs/seguimiento"),
    Fuente("scanner-pump", "LuisP11127/Scanner-pump", "datos/seguimiento"),
)
CANDIDATAS = ("momento-a", "momento-b")
COMPARACION = "scanner-pump"
RAIZ_LISTAS = Path("datos/listas")

_DIA = re.compile(r"^(\d{4}-\d{2}-\d{2})\.json$")
# Las estrellas de Momento-B van aparte (las de Momento-A, dentro de cada moneda). La red no las usa:
# se copian para que la web pueda mostrar si coinciden con su lista.
_OTROS = {"estrellas.json"}
# Contratos de futuros con multiplicador: 1000PEPE → PEPE, 1MBABYDOGE → BABYDOGE (igual que las webs).
_MULTIPLICADOR = re.compile(r"^(1000000|100000|10000|1000|1M)(?=[A-Z])")


def _copiable(nombre: str) -> bool:
    return bool(_DIA.match(nombre)) or nombre in _OTROS


@dataclass
class Cambios:
    nuevos: list[str] = field(default_factory=list)
    cambiados: list[str] = field(default_factory=list)
    borrados: list[str] = field(default_factory=list)
    omitidos: list[str] = field(default_factory=list)  # archivos del origen que no se pudieron leer

    def __bool__(self) -> bool:
        return bool(self.nuevos or self.cambiados or self.borrados)

    def resumen(self) -> str:
        partes = [f"{titulo} {', '.join(n.removesuffix('.json') for n in nombres)}"
                  for titulo, nombres in (("nuevos:", self.nuevos), ("cambiados:", self.cambiados),
                                          ("borrados:", self.borrados))
                  if nombres]
        return "; ".join(partes) or "sin cambios"


def _error(nombre: str, datos: bytes) -> str | None:
    """Motivo por el que un archivo del origen no se copia, o ``None`` si está bien."""
    try:
        contenido = json.loads(datos)
    except ValueError as exc:
        return f"no es JSON válido ({exc})"
    dia = _DIA.match(nombre)
    if dia:
        if not isinstance(contenido, dict) or not isinstance(contenido.get("monedas"), list):
            return "no tiene la lista «monedas»"
        if contenido.get("fecha") != dia.group(1):
            return f"su fecha ({contenido.get('fecha')}) no coincide con el nombre"
    return None


def sincronizar(origen: Path, destino: Path) -> Cambios:
    """Deja en ``destino`` los mismos días (y ``estrellas.json``) que hay en ``origen``.

    Un archivo del origen que no se puede leer no se copia, y si ya había una copia se conserva.
    """
    if not origen.is_dir():
        raise FileNotFoundError(f"no existe la carpeta {origen}")
    archivos = {p.name: p for p in origen.iterdir() if p.is_file() and _copiable(p.name)}
    if not any(_DIA.match(nombre) for nombre in archivos):
        # Un checkout fallido no debe vaciar la copia.
        raise ValueError(f"{origen} no tiene ningún día; no se toca la copia")

    destino.mkdir(parents=True, exist_ok=True)
    cambios = Cambios()
    for nombre, ruta in sorted(archivos.items()):
        datos = ruta.read_bytes()
        error = _error(nombre, datos)
        if error:
            cambios.omitidos.append(f"{nombre}: {error}")
            continue
        copia = destino / nombre
        if copia.exists():
            if copia.read_bytes() == datos:
                continue
            cambios.cambiados.append(nombre)
        else:
            cambios.nuevos.append(nombre)
        copia.write_bytes(datos)

    for copia in sorted(destino.iterdir()):
        if copia.is_file() and _copiable(copia.name) and copia.name not in archivos:
            copia.unlink()
            cambios.borrados.append(copia.name)
    return cambios


def leer(clave: str, raiz: Path = RAIZ_LISTAS) -> dict[date, list[dict]]:
    """Monedas de cada día de una lista copiada."""
    dias: dict[date, list[dict]] = {}
    for ruta in sorted((raiz / clave).glob("*.json")):
        dia = _DIA.match(ruta.name)
        if dia:
            dias[date.fromisoformat(dia.group(1))] = json.loads(ruta.read_text(encoding="utf-8"))["monedas"]
    return dias


def moneda(fila: dict) -> str:
    """La moneda de una fila, sin el multiplicador de algunos contratos de futuros."""
    return _MULTIPLICADOR.sub("", str(fila.get("base") or fila["simbolo"]))


@dataclass
class Candidata:
    fecha: date  # día de la lista (la vela que abre a las 00:00 UTC del día siguiente)
    moneda: str
    mercado: str
    simbolo: str
    listas: tuple[str, ...]  # en qué listas salió ese día
    filas: list[dict]  # las filas originales, con lo que guardó cada web al escanear


def candidatas(raiz: Path = RAIZ_LISTAS) -> list[Candidata]:
    """Las monedas de Momento-A y Momento-B de cada día, una vez por moneda («No repetidas»).

    Si la moneda salió en futuros se toma futuros, que es el mercado con historial del libro de
    órdenes; si solo salió en spot, spot.
    """
    grupos: dict[tuple[date, str], list[tuple[str, dict]]] = defaultdict(list)
    for clave in CANDIDATAS:
        for fecha, filas in leer(clave, raiz).items():
            for fila in filas:
                grupos[(fecha, moneda(fila))].append((clave, fila))

    resultado = []
    for (fecha, nombre), items in sorted(grupos.items()):
        filas = [fila for _, fila in items]
        elegida = next((f for f in filas if f["mercado"] == "futures"), filas[0])
        resultado.append(Candidata(fecha, nombre, elegida["mercado"], elegida["simbolo"],
                                   tuple(sorted({clave for clave, _ in items})), filas))
    return resultado


def explosiones(raiz: Path = RAIZ_LISTAS) -> dict[str, set[date]]:
    """Días de Scanner-pump en que cada moneda tuvo una vela de +10 % o más."""
    dias: dict[str, set[date]] = defaultdict(set)
    for fecha, filas in leer(COMPARACION, raiz).items():
        for fila in filas:
            dias[moneda(fila)].add(fecha)
    return dict(dias)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copia las listas de seguimiento de los tres repositorios a datos/listas.")
    for fuente in FUENTES:
        parser.add_argument(f"--{fuente.clave}", type=Path, metavar="REPO",
                            help=f"carpeta con el repositorio {fuente.repo}")
    parser.add_argument("--destino", type=Path, default=RAIZ_LISTAS, help="por defecto, datos/listas")
    args = parser.parse_args(argv)

    errores = 0
    for fuente in FUENTES:
        repo = getattr(args, fuente.clave.replace("-", "_"))
        if repo is None:
            continue
        try:
            cambios = sincronizar(repo / fuente.carpeta, args.destino / fuente.clave)
        except (OSError, ValueError) as exc:
            print(f"{fuente.clave}: {exc}", file=sys.stderr)
            errores += 1
            continue
        print(f"{fuente.clave}: {cambios.resumen()}")
        for omitido in cambios.omitidos:
            print(f"  no se copió {omitido}", file=sys.stderr)
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
