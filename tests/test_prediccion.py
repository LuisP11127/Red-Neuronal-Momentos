import math
from datetime import date, datetime, timezone

import pytest

from red_momentos import prediccion, senales
from red_momentos.fechas import ms

INSTANTE = datetime(2026, 10, 3, 0, 30, 5, tzinfo=timezone.utc)


def test_bandas_del_libro_como_bookdepth():
    # Precio medio 100. Compras a 99.9, 99, 97 y 90; ventas a 100.1, 101, 104 y 110.
    libro = {"bids": [["99.9", "1"], ["99", "2"], ["97", "1"], ["90", "1"]],
             "asks": [["100.1", "1"], ["101", "1"], ["104", "2"], ["110", "1"]]}
    filas = prediccion.bandas_del_libro({"bids": libro["bids"][:1] + libro["bids"][1:], "asks": libro["asks"]}, INSTANTE)
    usdt = {float(f[1]): float(f[3]) for f in filas}
    medio = (99.9 + 100.1) / 2
    assert medio == 100
    assert usdt[-0.2] == pytest.approx(99.9)
    assert usdt[-1.0] == pytest.approx(99.9 + 198)
    assert usdt[-5.0] == pytest.approx(99.9 + 198 + 97)
    assert usdt[2.0] == pytest.approx(100.1 + 101)
    assert usdt[5.0] == pytest.approx(100.1 + 101 + 208)
    # El libro corto no llega a ±5 %: esa banda no se inventa.
    corto = prediccion.bandas_del_libro({"bids": libro["bids"][:2], "asks": libro["asks"][:2]}, INSTANTE)
    assert {float(f[1]) for f in corto} == {-0.2, -1.0, 0.2, 1.0}
    assert prediccion.bandas_del_libro({"bids": [], "asks": []}, INSTANTE) == []

    r = senales.del_libro(filas, INSTANTE, volumen_dia=1000)
    assert r["libro_deseq_02"] == pytest.approx(99.9 / (99.9 + 100.1))
    assert not math.isnan(r["libro_deseq_5"])
    assert math.isnan(senales.del_libro(corto, INSTANTE, 1000)["libro_deseq_5"])


class ApiFalsa:
    def __init__(self):
        self.pedidos = []
        t0 = ms(date(2026, 10, 2))
        self.momentos = [t0 + k * 300_000 for k in range(0, 24 * 12 + 7)]  # del 2 a las 00:00 al 3 a las 00:30

    def _get(self, mercado, ruta, params, forma=list):
        self.pedidos.append((ruta, params.get("startTime"), params.get("endTime")))
        if ruta == "/fapi/v1/depth":
            return {"bids": [["0.995", "1000"], ["0.9", "1000"]], "asks": [["1.005", "500"], ["1.1", "500"]]}
        datos = []
        for t in self.momentos:
            if not params["startTime"] <= t <= params["endTime"]:
                continue
            k = (t - self.momentos[0]) // 300_000
            if ruta.endswith("openInterestHist"):
                datos.append({"timestamp": t, "sumOpenInterest": str(100 + k), "sumOpenInterestValue": str(1000 + k)})
            elif ruta.endswith("takerlongshortRatio"):
                datos.append({"timestamp": t, "buySellRatio": "1.2"})
            else:
                datos.append({"timestamp": t, "longShortRatio": {"topLongShortAccountRatio": "2",
                                                                 "topLongShortPositionRatio": "3",
                                                                 "globalLongShortAccountRatio": "4"}[ruta.rsplit("/", 1)[1]]})
        return datos


def test_futuros_en_vivo():
    api = ApiFalsa()
    datos = prediccion.FuturosEnVivo(api, INSTANTE).senales("XUSDT", date(2026, 10, 1), volumen_dia=1000)
    assert datos["libro_deseq_1"] == pytest.approx(995 / (995 + 502.5))
    ultima_oi = 1000 + 24 * 12 + 6  # la fila de las 00:30
    assert datos["oi_rel_vol"] == pytest.approx(ultima_oi / 1000)
    assert (datos["ls_top_cuentas"], datos["ls_top_posiciones"], datos["ls_global"], datos["taker_ls"]) == (2, 3, 4, 1.2)
    assert datos["oi_cambio_dia"] == pytest.approx(((100 + 287) / 100 - 1) * 100)
    # Un día por petición: el de la vela y lo que va del siguiente.
    rangos = {(a, b) for r, a, b in api.pedidos if r.endswith("openInterestHist")}
    assert rangos == {(ms(date(2026, 10, 2)), ms(date(2026, 10, 3)) - 1),
                      (ms(date(2026, 10, 3)), int(INSTANTE.timestamp() * 1000))}
