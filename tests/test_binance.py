import io
import json
import zipfile
from dataclasses import replace
from datetime import date

import pytest
import requests

from red_momentos import binance
from red_momentos.binance import Binance, vela_de_fila
from red_momentos.fechas import ms


class Respuesta:
    def __init__(self, status=200, datos=None, contenido=b"", cabeceras=None):
        self.status_code = status
        self._datos = datos
        self.content = contenido
        self.text = json.dumps(datos) if datos is not None else ""
        self.headers = cabeceras or {}

    def json(self):
        if self._datos is None:
            raise ValueError("no es JSON")
        return self._datos


class Sesion:
    """Sesión falsa: ``rutas`` relaciona el principio de la URL con una función que da la respuesta."""

    def __init__(self, rutas):
        self.rutas = rutas
        self.pedidas = []

    def get(self, url, params=None, timeout=None):
        self.pedidas.append((url, params))
        for prefijo, responder in self.rutas.items():
            if url.startswith(prefijo):
                return responder(url, params)
        return Respuesta(404)


def fila_api(dia, precio=1.0):
    return [ms(dia), str(precio), str(precio * 1.2), str(precio * 0.9), str(precio * 1.1), "100", ms(dia) + 86399999,
            "110", 50, "60", "66", "0"]


def api_con_velas(velas_por_dia):
    def responder(url, params):
        inicio, fin = params["startTime"], params["endTime"]
        filas = [fila_api(d, p) for d, p in sorted(velas_por_dia.items()) if inicio <= ms(d) <= fin]
        return Respuesta(200, filas[: params["limit"]], cabeceras={"X-MBX-USED-WEIGHT-1M": "10"})
    return responder


def zip_csv(lineas):
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as archivo:
        archivo.writestr("velas.csv", "\n".join(lineas) + "\n")
    return salida.getvalue()


def test_vela_de_fila_milisegundos_y_microsegundos():
    vela = vela_de_fila(fila_api(date(2026, 10, 1), 2.0))
    assert vela.dia == date(2026, 10, 1)
    assert (vela.open, vela.high, vela.close, vela.volumen_usdt, vela.operaciones, vela.compra_taker) == \
        (2.0, 2.4, 2.2, 110.0, 50, 60.0)
    # data.binance.vision guarda spot en microsegundos desde 2025.
    micro = [str(ms(date(2026, 10, 1)) * 1000)] + fila_api(date(2026, 10, 1))[1:]
    assert vela_de_fila(micro).dia == date(2026, 10, 1)


def test_api_por_paginas(monkeypatch):
    dias = {date(2026, 10, d): float(d) for d in range(1, 11)}
    sesion = Sesion({"https://www.binance.com": api_con_velas(dias)})
    monkeypatch.setitem(binance.MERCADOS, "futures", replace(binance.FUTUROS, por_pagina=4))
    velas, cubierto = Binance(sesion, espera=0).velas_diarias("futures", "XUSDT", date(2026, 10, 2), date(2026, 10, 9))
    assert [v.dia.day for v in velas] == list(range(2, 10))
    assert cubierto == date(2026, 10, 9)
    assert len(sesion.pedidas) == 2


def test_par_que_no_existe_devuelve_lista_vacia():
    sesion = Sesion({"https://data-api.binance.vision": lambda u, p: Respuesta(400, {"code": -1121, "msg": "Invalid symbol."})})
    velas, _ = Binance(sesion, espera=0).velas_diarias("spot", "NOUSDT", date(2026, 10, 1), date(2026, 10, 3))
    assert velas == []


def test_451_pasa_a_la_otra_direccion():
    dias = {date(2026, 10, 1): 1.0}
    sesion = Sesion({
        "https://www.binance.com": lambda u, p: Respuesta(451, {"msg": "restricted"}),
        "https://fapi.binance.com": api_con_velas(dias),
    })
    cliente = Binance(sesion, espera=0)
    velas, _ = cliente.velas_diarias("futures", "XUSDT", date(2026, 10, 1), date(2026, 10, 1))
    assert len(velas) == 1
    velas, _ = cliente.velas_diarias("futures", "XUSDT", date(2026, 10, 1), date(2026, 10, 1))
    assert sum(url.startswith("https://www.binance.com") for url, _ in sesion.pedidas) == 1  # no se vuelve a probar


def test_sin_api_usa_data_binance_vision():
    def caida(url, params):
        raise requests.ConnectionError("bloqueado")

    septiembre = [",".join(map(str, fila_api(date(2026, 9, d), 1.0))) for d in (29, 30)]
    octubre_1 = ",".join(map(str, fila_api(date(2026, 10, 1), 2.0)))
    cabecera = "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore"
    vision = binance.VISION + "/futures/um"
    archivos = {
        f"{vision}/monthly/klines/XUSDT/1d/XUSDT-1d-2026-09.zip": zip_csv([cabecera] + septiembre),
        f"{vision}/daily/klines/XUSDT/1d/XUSDT-1d-2026-10-01.zip": zip_csv([cabecera, octubre_1]),
        f"{vision}/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2026-10-01.zip": zip_csv([cabecera, octubre_1]),
    }
    sesion = Sesion({
        "https://www.binance.com": caida,
        "https://fapi.binance.com": caida,
        binance.VISION: lambda url, p: Respuesta(200, contenido=archivos[url]) if url in archivos else Respuesta(404),
    })
    cliente = Binance(sesion, espera=0)
    velas, cubierto = cliente.velas_diarias("futures", "XUSDT", date(2026, 9, 30), date(2026, 10, 2))
    assert [(v.dia, v.open) for v in velas] == [(date(2026, 9, 30), 1.0), (date(2026, 10, 1), 2.0)]
    # El 2 de octubre aún no está publicado: la última vela disponible es la del 1.
    assert cubierto == date(2026, 10, 1)
    assert cliente.avisos and "data.binance.vision" in cliente.avisos[0]


def test_error_desconocido_se_avisa():
    sesion = Sesion({"https://data-api.binance.vision": lambda u, p: Respuesta(400, {"code": -1100, "msg": "Illegal"})})
    with pytest.raises(RuntimeError):
        Binance(sesion, espera=0).velas_diarias("spot", "XUSDT", date(2026, 10, 1), date(2026, 10, 1))


class SesionPorRangos:
    """Sirve un archivo respetando la cabecera Range, como data.binance.vision."""

    def __init__(self, contenido):
        self.contenido = contenido
        self.rangos = []

    def get(self, url, headers=None, timeout=None, params=None):
        fin = int(headers["Range"].split("-")[1])
        self.rangos.append(fin + 1)
        parte = self.contenido[: fin + 1]
        return Respuesta(206 if len(parte) < len(self.contenido) else 200, contenido=parte)


def test_inicio_csv_baja_solo_el_principio():
    lineas = [f"2026-10-03 {h:02d}:{m:02d}:00,-1.00,{h * 60 + m},{h * 7 + m * 13}" for h in range(24) for m in range(60)]
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", compression=zipfile.ZIP_DEFLATED) as archivo:
        archivo.writestr("libro.csv", "\n".join(["timestamp,percentage,depth,notional"] + lineas) + "\n")
    sesion = SesionPorRangos(salida.getvalue())
    cliente = Binance(sesion, espera=0)
    filas = cliente.inicio_csv("https://x/libro.zip", lambda f: f[-1][0] > "2026-10-03 00:30:00", tamano=256)
    assert filas[0] == ["timestamp", "percentage", "depth", "notional"]
    assert filas[-1][0] > "2026-10-03 00:30:00" and all(len(f) == 4 for f in filas)
    assert len(sesion.rangos) > 1 and sesion.rangos[-1] < len(sesion.contenido)  # pidió más, pero no todo
    # Si nunca basta, acaba con el archivo entero.
    todo = cliente.inicio_csv("https://x/libro.zip", lambda f: False, tamano=256)
    assert len(todo) == len(lineas) + 1


def test_inicio_csv_de_un_archivo_que_no_existe():
    class NoEsta:
        def get(self, url, headers=None, timeout=None):
            return Respuesta(404)

    assert Binance(NoEsta(), espera=0).inicio_csv("https://x/no.zip", lambda f: True) is None
