import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from red_momentos import senales
from red_momentos.binance import Vela
from red_momentos.fechas import ms


def vela(dia, o, h, l, c, qv=100.0, n=10, tq=50.0):
    return Vela(ms(dia), o, h, l, c, 1.0, qv, n, 0.5, tq)


def serie(cierres, inicio=date(2026, 1, 1), **kw):
    return [vela(inicio + timedelta(days=i), c, c * 1.01, c * 0.99, c, **kw) for i, c in enumerate(cierres)]


def test_medias_y_variaciones():
    velas = serie([1.0] * 120 + [2.0])
    tabla = senales.diarias(velas, primera=date(2024, 3, 1))
    ultima = tabla.iloc[-1]
    assert ultima["dist_ma7"] == pytest.approx((2.0 / (8 / 7) - 1) * 100)
    assert ultima["dist_ma99"] == pytest.approx((2.0 / (100 / 99) - 1) * 100)
    assert ultima["var_7d"] == pytest.approx(100.0)
    assert tabla.iloc[0]["edad_dias"] == 671  # del 1 de marzo de 2024 al 1 de enero de 2026
    assert tabla["edad_dias"].max() == senales.EDAD_MAX  # tope
    assert math.isnan(tabla.iloc[50]["dist_ma99"])  # sin 99 velas todavía


def test_velas_sobre_ma7_seguidas():
    # Bajando, cada cierre queda bajo la MA(7); después sube tres días. Igual que Momento-A, un cierre
    # justo en la MA(7) cuenta como «sobre».
    tabla = senales.diarias(serie([10 - 0.1 * i for i in range(20)] + [9.0, 9.5, 9.6]))
    assert list(tabla["velas_sobre_ma7"].iloc[-4:]) == [0, 1, 2, 3]
    assert senales.diarias(serie([1.0] * 10))["velas_sobre_ma7"].iloc[-1] == 4  # de la 7.ª a la 10.ª


def test_explosiones_y_dias_desde_la_anterior():
    inicio = date(2026, 1, 1)
    velas = [vela(inicio + timedelta(days=i), 1, 1.01, 1, 1) for i in range(40)]
    for i in (9, 30):  # dos velas de +20 % de mínimo a máximo (la del día 9 queda fuera de las últimas 30)
        velas[i] = vela(inicio + timedelta(days=i), 1, 1.2, 1, 1.1)
    velas[39] = vela(inicio + timedelta(days=39), 1, 1.6, 1, 1.5)  # +60 %
    tabla = senales.diarias(velas)
    assert tabla.iloc[39]["explosiones_30d"] == 2  # la del día 30 y la del 39
    assert tabla.iloc[39]["explosiones_90d"] == 3
    assert tabla.iloc[39]["dias_desde_explosion"] == 9  # la anterior fue el día 30
    assert tabla.iloc[39]["explosiones50_365d"] == 1
    assert tabla.iloc[39]["max_rango_90d"] == pytest.approx(60.0)
    assert tabla.iloc[39]["var_1d"] == pytest.approx(50.0)
    assert math.isnan(tabla.iloc[5]["dias_desde_explosion"])


def test_volumen_y_compras_agresivas():
    velas = serie([1.0] * 30, qv=100.0, tq=40.0)
    velas[-1] = vela(velas[-1].dia, 1, 1.01, 0.99, 1, qv=300.0, tq=240.0)
    ultima = senales.diarias(velas).iloc[-1]
    assert ultima["vol_rel_1d"] == pytest.approx(3.0)
    assert ultima["taker_1d"] == pytest.approx(0.8)
    assert ultima["taker_7d"] == pytest.approx((6 * 40 + 240) / (6 * 100 + 300))


def test_listas_de_los_siete_dias_anteriores():
    fecha = date(2026, 10, 10)
    en = {"momento-a": {fecha, date(2026, 10, 9), date(2026, 10, 2)}, "momento-b": {date(2026, 10, 3)}}
    assert senales.de_listas(fecha, en) == {"en_a": 1.0, "en_b": 0.0, "dias_en_a_7d": 1.0, "dias_en_b_7d": 1.0}


def foto(momento, valores):
    return [[momento, f"{p:.2f}", "1", str(v)] for p, v in valores.items()]


def test_libro_ultima_foto_antes_de_las_0030():
    instante = datetime(2026, 10, 3, 0, 30, tzinfo=timezone.utc)
    vieja = {-5: 500, -2: 200, -1: 100, -0.2: 10, 0.2: 10, 1: 100, 2: 200, 5: 500}
    buena = {-5: 600, -2: 300, -1: 150, -0.2: 30, 0.2: 10, 1: 50, 2: 100, 5: 400}
    filas = ([["timestamp", "percentage", "depth", "notional"]] + foto("2026-10-03 00:29:30", vieja)
             + foto("2026-10-03 00:30:00", buena) + foto("2026-10-03 00:30:30", vieja))
    r = senales.del_libro(filas, instante, volumen_dia=1000)
    assert r["libro_deseq_02"] == pytest.approx(0.75)
    assert r["libro_deseq_2"] == pytest.approx(0.75)
    assert r["libro_deseq_5"] == pytest.approx(0.6)
    assert r["libro_prof_2"] == pytest.approx(0.4)
    assert r["libro_conc_compras"] == pytest.approx(0.25)
    assert r["libro_conc_ventas"] == pytest.approx(0.125)
    # Una foto de hace más de media hora no vale.
    sola_vieja = foto("2026-10-02 23:50:00", vieja)
    assert all(math.isnan(v) for v in senales.del_libro(sola_vieja, instante, 1000).values())
    assert all(math.isnan(v) for v in senales.del_libro(None, instante, 1000).values())


CABECERA = ["create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
            "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio", "count_long_short_ratio",
            "sum_taker_long_short_vol_ratio"]


def test_metricas():
    dia = [CABECERA,
           ["2026-10-02 00:05:00", "X", "100", "1000", "2", "1.5", "1.8", "0.8"],
           ["2026-10-02 12:00:00", "X", "110", "1100", "2.1", "1.6", "1.9", ""],  # campo vacío
           ["2026-10-02 23:55:00", "X", "120", "1300", "2.2", "1.7", "2.0", "1.2"]]
    siguiente = [CABECERA,
                 ["2026-10-03 00:20:00", "X", "125", "1400", "2.5", "1.9", "2.3", "1.0"],
                 ["2026-10-03 00:35:00", "X", "999", "9999", "9", "9", "9", "9"]]  # después de las 00:30
    instante = datetime(2026, 10, 3, 0, 30, tzinfo=timezone.utc)
    r = senales.de_metricas(senales.resumir(dia), senales.resumir(siguiente), instante, volumen_dia=700)
    assert r["oi_rel_vol"] == pytest.approx(2.0)
    assert (r["ls_top_cuentas"], r["ls_top_posiciones"], r["ls_global"]) == (2.5, 1.9, 2.3)
    assert r["oi_cambio_dia"] == pytest.approx(20.0)
    assert r["taker_ls"] == pytest.approx(1.0)  # mediana de 0.8 y 1.2
    # Sin filas en las 6 horas anteriores: sin valores del momento.
    r = senales.de_metricas(senales.resumir(dia[:2]), senales.resumir(None), instante, 700)
    assert math.isnan(r["oi_rel_vol"]) and math.isnan(r["oi_cambio_dia"])


def test_publicado():
    fecha = date(2026, 10, 1)  # las 00:30 son el 3 de octubre; su archivo sale el 4 hacia las 08:10 UTC
    assert senales.referencia(fecha) == datetime(2026, 10, 3, 0, 30, tzinfo=timezone.utc)
    assert not senales.publicado(fecha, datetime(2026, 10, 4, 8, 0, tzinfo=timezone.utc))
    assert senales.publicado(fecha, datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc))


class BinanceFalso:
    def __init__(self, libros, metricas):
        self.libros, self.metricas = libros, metricas
        self.pedidos = []

    def inicio_csv(self, url, basta, tamano=0):
        self.pedidos.append(url)
        return self.libros.get(url.rsplit("/", 1)[1])

    def _zip(self, url, solo_velas=True):
        self.pedidos.append(url)
        return self.metricas.get(url.rsplit("/", 1)[1])


def test_calcular_con_futuros_y_cache(tmp_path):
    fecha = date(2026, 10, 1)
    libro = [["timestamp", "percentage", "depth", "notional"]] + foto(
        "2026-10-03 00:30:00", {-5: 600, -2: 300, -1: 150, -0.2: 30, 0.2: 10, 1: 50, 2: 100, 5: 400})
    metricas = {"XUSDT-metrics-2026-10-02.zip": [CABECERA, ["2026-10-02 23:55:00", "X", "1", "50", "2", "1", "1", "1"]]}
    falso = BinanceFalso({"XUSDT-bookDepth-2026-10-03.zip": libro}, metricas)
    velas = {("futures", "XUSDT"): serie([1.0] * 121, inicio=date(2026, 6, 4)),  # hasta el 2 de octubre
             ("spot", "YUSDT"): serie([1.0] * 121, inicio=date(2026, 6, 4))}
    candidatas = [senales.Fila(fecha, "X", "futures", "XUSDT", ("momento-a",)),
                  senales.Fila(fecha, "Y", "spot", "YUSDT", ("momento-b",)),
                  senales.Fila(date(2026, 10, 20), "X", "futures", "XUSDT", ("momento-a",))]
    ahora = datetime(2026, 10, 21, tzinfo=timezone.utc)
    cache = tmp_path / "futuros.jsonl"
    filas = senales.calcular(candidatas, senales.en_que_listas(candidatas), velas, {}, ahora,
                             senales.Futuros(falso, cache), hilos=2)
    x, y, x_reciente = filas
    assert (x["completa"], x["en_a"], x["libro_deseq_2"], x["oi_rel_vol"]) == ("1", "1", "0.75", "0.5")
    assert x["dist_ma7"] == "0"
    assert (y["completa"], y["en_b"], y["libro_deseq_2"]) == ("1", "1", "")  # spot: sin libro
    assert x_reciente["completa"] == "0"  # sus datos aún no están (y no hay velas de ese día)
    assert len(falso.pedidos) == 3  # libro, métricas del día y del siguiente; nada para la reciente

    # Con la caché no se vuelve a descargar.
    falso.pedidos.clear()
    otra = senales.calcular(candidatas[:1], {}, velas, {}, ahora, senales.Futuros(falso, cache), hilos=1)
    assert otra[0]["libro_deseq_2"] == "0.75" and falso.pedidos == []
    assert json.loads(cache.read_text().splitlines()[0])[0] == "XUSDT|2026-10-01"
