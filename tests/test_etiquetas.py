from datetime import date, datetime, timedelta, timezone

from red_momentos import etiquetas, listas
from red_momentos.binance import Vela
from red_momentos.etiquetas import DIA_MS, PASO, referencia_ms
from red_momentos.fechas import ms

LIMA = timezone(timedelta(hours=-5))
FECHA = date(2026, 10, 1)  # su vela abre el 2 de octubre a las 00:00 UTC y cierra el 3 a las 00:00 UTC
INICIO = referencia_ms(FECHA)  # 3 de octubre, 00:30 UTC = 2 de octubre, 19:30 en Lima


def velas_30m(desde, cantidad, high=1.0, saltos=None, apertura_inicial=1.0):
    """``cantidad`` velas de 30 minutos desde ``desde``; ``saltos`` cambia el máximo de algunas (índice → máximo).

    Añade antes una vela de 00:00 a 00:30 UTC con un máximo enorme, que no debe contar.
    """
    saltos = saltos or {}
    velas = {desde - PASO: Vela(desde - PASO, 1.0, 9.0, 1.0, 1.0, 1, 1, 1, 0.5, 0.5)}
    for i in range(cantidad):
        t = desde + i * PASO
        apertura = apertura_inicial if i == 0 else 1.0
        velas[t] = Vela(t, apertura, saltos.get(i, high), 0.9, 1.0, 1, 1, 1, 0.5, 0.5)
    return velas


def test_la_referencia_es_las_1930_de_lima():
    momento = datetime.fromtimestamp(INICIO / 1000, timezone.utc)
    assert momento == datetime(2026, 10, 3, 0, 30, tzinfo=timezone.utc)
    assert momento.astimezone(LIMA).strftime("%Y-%m-%d %H:%M") == "2026-10-02 19:30"


def test_llega_al_50_el_tercer_dia():
    # La vela 100 (50 horas después de las 19:30) está en el tercer día.
    velas = velas_30m(INICIO, 4 * 48, high=1.1, saltos={100: 1.5, 150: 1.6})
    r = etiquetas.etiquetar(FECHA, velas, cubierto=INICIO + 4 * DIA_MS - PASO)
    assert (r.estado, r.dias_hasta_50, r.dias_vistos, r.referencia, r.maximo) == ("llego", 3, 4, 1.0, 1.6)
    assert round(r.pct(r.maximo), 2) == 60.0
    assert round(r.pct(r.minimo), 2) == -10.0


def test_no_llega_tras_diez_dias_y_lo_de_despues_no_cuenta():
    velas = velas_30m(INICIO, 11 * 48, high=1.49, saltos={10 * 48: 2.0})  # +100 % justo al terminar
    r = etiquetas.etiquetar(FECHA, velas, cubierto=INICIO + 11 * DIA_MS)
    assert (r.estado, r.dias_vistos, r.dias_hasta_50, r.maximo) == ("no_llego", 10, None, 1.49)


def test_la_referencia_es_la_apertura_de_las_1930():
    # Si a las 19:30 abre en 2, hace falta llegar a 3.
    velas = velas_30m(INICIO, 10 * 48, high=2.9, apertura_inicial=2.0)
    assert etiquetas.etiquetar(FECHA, velas, cubierto=INICIO + 10 * DIA_MS).estado == "no_llego"


def test_pendiente_y_sin_datos():
    velas = velas_30m(INICIO, 2 * 48, high=1.2)
    r = etiquetas.etiquetar(FECHA, velas, cubierto=INICIO + 2 * DIA_MS - PASO)
    assert (r.estado, r.dias_vistos) == ("pendiente", 2)
    # Aún no son las 19:30 de ese día (o los datos no están publicados).
    assert etiquetas.etiquetar(FECHA, {}, cubierto=INICIO - PASO).estado == "pendiente"
    assert etiquetas.etiquetar(FECHA, {}, cubierto=INICIO + 20 * DIA_MS).estado == "sin_datos"


class BinanceFalso:
    def __init__(self, series):
        self.series = series
        self.pedidos = []
        self.avisos = []

    def velas(self, mercado, simbolo, intervalo, desde, hasta):
        assert intervalo == "30m"
        self.pedidos.append(simbolo)
        serie = self.series[simbolo.removesuffix("USDT")]
        return [v for t, v in sorted(serie.items()) if desde <= t <= hasta], hasta


def candidata(fecha, nombre, listas_=("momento-a",), mercado="futures"):
    return listas.Candidata(fecha, nombre, mercado, nombre + "USDT", listas_, [])


def test_calcular_reutiliza_las_cerradas_y_compara_con_scanner_pump():
    ahora = ms(date(2026, 10, 21)) + 12 * 3_600_000  # 21 de octubre, 12:00 UTC
    b_inicio = referencia_ms(date(2026, 10, 19))  # 21 de octubre, 00:30 UTC
    series = {"A": velas_30m(INICIO, 12 * 48, high=1.0, saltos={4 * 48 + 3: 1.7}),
              "B": velas_30m(b_inicio, 24, high=1.1)}
    falso = BinanceFalso(series)
    candidatas = [candidata(FECHA, "A", ("momento-a", "momento-b")), candidata(date(2026, 10, 19), "B"),
                  candidata(date(2026, 10, 21), "B")]
    explosiones = {"A": {FECHA, date(2026, 10, 6), date(2026, 10, 30)}}

    filas = etiquetas.calcular(candidatas, explosiones, falso, {}, ahora, hilos=2)
    a, b, b_futura = filas
    assert (a["estado"], a["dias_hasta_50"], a["pct_maximo"], a["listas"]) == ("llego", "5", "70.00", "momento-a momento-b")
    assert (a["explosion_mismo_dia"], a["explosiones_despues"]) == ("1", "2026-10-06")
    assert (b["estado"], b["referencia"], b["pct_maximo"], b["dias_vistos"]) == ("pendiente", "1", "10.00", "0")
    assert (b_futura["estado"], b_futura["referencia"]) == ("pendiente", "")  # su 19:30 es el 22 en Lima
    assert sorted(falso.pedidos) == ["AUSDT", "BUSDT"]

    # Al día siguiente, A ya está cerrada: se reutiliza sin pedir sus velas.
    anteriores = {(f["fecha"], f["moneda"]): f for f in filas}
    falso.pedidos.clear()
    filas2 = etiquetas.calcular(candidatas, explosiones, falso, anteriores, ahora + DIA_MS, hilos=2)
    assert filas2[0] == a
    assert falso.pedidos == ["BUSDT"]


def test_csv_ida_y_vuelta(tmp_path):
    falso = BinanceFalso({"A": velas_30m(INICIO, 10 * 48, high=1.6)})
    filas = etiquetas.calcular([candidata(FECHA, "A")], {}, falso, {}, INICIO + 12 * DIA_MS)
    ruta = tmp_path / "etiquetas.csv"
    etiquetas.escribir_csv(ruta, filas)
    assert etiquetas.leer_csv(ruta) == {("2026-10-01", "A"): filas[0]}
    assert "| Todas | 1 | 1 | 1 | 100.0 | 0 | 0 |" in etiquetas.resumen(filas)
