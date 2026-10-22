from datetime import date, timedelta

from red_momentos import etiquetas, listas
from red_momentos.binance import Vela


def vela(dia, close=1.0, high=None, low=None):
    return Vela(dia, close, high if high is not None else close, low if low is not None else close, close,
                1.0, 1.0, 1, 0.5, 0.5)


def serie(inicio, highs, cierre=1.0):
    """Vela de referencia (``inicio``) con ``cierre`` y después una vela por cada máximo de ``highs``."""
    velas = {inicio: vela(inicio, cierre)}
    for k, high in enumerate(highs, start=1):
        dia = inicio + timedelta(days=k)
        velas[dia] = vela(dia, 1.0, high=high, low=0.9)
    return velas


FECHA = date(2026, 10, 1)  # día de la lista: su vela abre el 2 de octubre a las 00:00 UTC
INICIO = date(2026, 10, 2)


def test_llega_al_50_el_tercer_dia():
    r = etiquetas.etiquetar(FECHA, serie(INICIO, [1.1, 1.2, 1.5, 1.3, 1.6]), cubierto_hasta=date(2026, 10, 7))
    assert (r.estado, r.dias_hasta_50, r.velas, r.cierre, r.maximo) == ("llego", 3, 5, 1.0, 1.6)
    assert round(r.pct(r.maximo), 2) == 60.0
    assert round(r.pct(r.minimo), 2) == -10.0


def test_no_llega_tras_diez_dias():
    r = etiquetas.etiquetar(FECHA, serie(INICIO, [1.49] * 12), cubierto_hasta=date(2026, 10, 20))
    assert (r.estado, r.velas, r.dias_hasta_50) == ("no_llego", 10, None)  # la vela 11 no cuenta


def test_la_vela_once_no_cuenta():
    r = etiquetas.etiquetar(FECHA, serie(INICIO, [1.0] * 10 + [2.0]), cubierto_hasta=date(2026, 10, 20))
    assert r.estado == "no_llego"


def test_pendiente_y_sin_datos():
    assert etiquetas.etiquetar(FECHA, serie(INICIO, [1.2, 1.3]), cubierto_hasta=date(2026, 10, 4)).estado == "pendiente"
    # La vela del día aún no ha cerrado (o no está publicada).
    assert etiquetas.etiquetar(FECHA, {}, cubierto_hasta=date(2026, 10, 1)).estado == "pendiente"
    assert etiquetas.etiquetar(FECHA, {}, cubierto_hasta=date(2026, 10, 20)).estado == "sin_datos"


class BinanceFalso:
    def __init__(self, velas):
        self.velas = velas
        self.pedidos = []
        self.avisos = []

    def velas_diarias(self, mercado, simbolo, desde, hasta):
        self.pedidos.append((mercado, simbolo, desde, hasta))
        return [v for d, v in sorted(self.velas[simbolo.removesuffix("USDT")].items()) if desde <= d <= hasta], hasta


def candidata(fecha, nombre, listas_=("momento-a",), mercado="futures"):
    return listas.Candidata(fecha, nombre, mercado, nombre + "USDT", listas_, [])


def test_calcular_reutiliza_las_cerradas_y_compara_con_scanner_pump():
    hoy = date(2026, 10, 21)
    velas = {"A": serie(INICIO, [1.0] * 4 + [1.7] + [1.0] * 15), "B": serie(date(2026, 10, 20), [])}
    falso = BinanceFalso(velas)
    candidatas = [candidata(FECHA, "A", ("momento-a", "momento-b")), candidata(date(2026, 10, 19), "B"),
                  candidata(date(2026, 10, 21), "B")]
    explosiones = {"A": {FECHA, date(2026, 10, 6), date(2026, 10, 30)}}

    filas = etiquetas.calcular(candidatas, explosiones, falso, {}, hoy, hilos=2)
    a, b, b_abierta = filas
    assert (a["estado"], a["dias_hasta_50"], a["pct_maximo"], a["listas"]) == ("llego", "5", "70.00", "momento-a momento-b")
    assert (a["explosion_mismo_dia"], a["explosiones_despues"]) == ("1", "2026-10-06")
    assert (b["estado"], b["cierre"], b["velas"]) == ("pendiente", "1", "0")
    assert (b_abierta["estado"], b_abierta["cierre"]) == ("pendiente", "")  # su vela abre el 22 (UTC)
    assert sorted(p[1] for p in falso.pedidos) == ["AUSDT", "BUSDT"]

    # Al día siguiente, A ya está cerrada: se reutiliza sin pedir sus velas.
    anteriores = {(f["fecha"], f["moneda"]): f for f in filas}
    falso.pedidos.clear()
    filas2 = etiquetas.calcular(candidatas, explosiones, falso, anteriores, hoy + timedelta(days=1), hilos=2)
    assert filas2[0] == a
    assert [p[1] for p in falso.pedidos] == ["BUSDT"]


def test_csv_ida_y_vuelta(tmp_path):
    falso = BinanceFalso({"A": serie(INICIO, [1.6] * 10)})
    filas = etiquetas.calcular([candidata(FECHA, "A")], {}, falso, {}, date(2026, 10, 21))
    ruta = tmp_path / "etiquetas.csv"
    etiquetas.escribir_csv(ruta, filas)
    assert etiquetas.leer_csv(ruta) == {("2026-10-01", "A"): filas[0]}
    assert "| Todas | 1 | 1 | 1 | 100.0 | 0 | 0 |" in etiquetas.resumen(filas)
