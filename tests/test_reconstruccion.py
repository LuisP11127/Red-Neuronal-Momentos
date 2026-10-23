from datetime import date, timedelta

from red_momentos import reconstruccion as rc
from red_momentos.binance import Vela
from red_momentos.fechas import ms


def vela(dia, o, c, h=None, l=None):
    return Vela(ms(dia), o, h if h is not None else max(o, c), l if l is not None else min(o, c), c, 1, 1, 1, 1, 1)


def serie(cierres, inicio=date(2026, 1, 1), verde_al_final=True):
    velas = [vela(inicio + timedelta(days=i), c, c) for i, c in enumerate(cierres)]
    if verde_al_final:
        ultima = velas[-1]
        velas[-1] = vela(ultima.dia, ultima.close * 0.97, ultima.close)
    return velas


def test_regla_de_momento_a():
    # Bajada larga (MA7 < MA25 < MA99) y la última vela verde, justo sobre la MA(7).
    cierres = [100 - 0.5 * i for i in range(120)]
    cierres[-1] = sum(cierres[-8:-1]) / 7 * 1.01
    a, b = rc.reglas(serie(cierres))
    assert a[-1] and not b[-1]
    roja = serie(cierres, verde_al_final=False)
    roja[-1] = vela(roja[-1].dia, roja[-1].close * 1.02, roja[-1].close)
    assert not rc.reglas(roja)[0][-1]
    lejos = list(cierres)
    lejos[-1] = sum(cierres[-8:-1]) / 7 * 0.95  # más de 2 % bajo la MA(7)
    assert not rc.reglas(serie(lejos))[0][-1]
    assert not rc.reglas(serie(cierres[:98]))[0].any()  # sin 99 velas no hay MA(99)


def test_regla_de_momento_b():
    # Bajada y rebote: la MA(7) cruza la MA(25) pero sigue bajo la MA(99).
    cierres = [100 - 0.5 * i for i in range(110)] + [45 + 2 * i for i in range(10)]
    a, b = rc.reglas(serie(cierres))
    assert b[-1]
    assert not b[:100].any()


def test_candidatas_una_por_moneda_con_futuros_primero():
    cierres = [100 - 0.5 * i for i in range(110)] + [45 + 2 * i for i in range(10)]
    velas = serie(cierres, inicio=date(2022, 9, 25))
    pares = {rc.Par("spot", "PEPEUSDT", "PEPE"): velas, rc.Par("futures", "1000PEPEUSDT", "1000PEPE"): velas}
    resultado = rc.candidatas(pares, desde=date(2023, 1, 1))
    assert resultado and all(c.moneda == "PEPE" and c.mercado == "futures" for c in resultado)
    assert len({c.fecha for c in resultado}) == len(resultado)
    assert all(c.fecha >= date(2023, 1, 1) for c in resultado)
    # El día de la lista es el anterior al de la vela (UTC).
    ultima = resultado[-1]
    assert ultima.fecha == velas[-1].dia - timedelta(days=1)


def test_etiqueta_diaria():
    fecha = date(2026, 10, 1)  # vela del 2 de octubre; referencia: apertura del 3 (00:00 UTC)
    velas = {date(2026, 10, 3): vela(date(2026, 10, 3), 2.0, 2.1, h=2.2)}
    for k in range(1, 12):
        dia = date(2026, 10, 3) + timedelta(days=k)
        velas[dia] = vela(dia, 2.0, 2.0, h=3.0 if k == 4 else 2.5)
    r = rc.etiqueta_diaria(fecha, velas, cubierto=date(2026, 10, 20))
    assert (r.estado, r.dias_hasta_50, r.referencia) == ("llego", 5, 2.0)
    r = rc.etiqueta_diaria(fecha, {d: v for d, v in velas.items() if v.high < 3}, cubierto=date(2026, 10, 20))
    assert (r.estado, r.maximo) == ("no_llego", 2.5)
    assert rc.etiqueta_diaria(fecha, velas, cubierto=date(2026, 10, 7)).estado == "llego"  # el 7 llega a 3
    sin_meta = {d: v for d, v in velas.items() if v.high < 3}
    assert rc.etiqueta_diaria(fecha, sin_meta, cubierto=date(2026, 10, 8)).estado == "pendiente"


class Respuesta:
    def __init__(self, datos=None, texto=""):
        self._datos, self.text = datos, texto

    def json(self):
        return self._datos


class BinanceFalso:
    timeout = 5

    def __init__(self):
        self.avisos = []
        self.sesion = self

    def get(self, url, timeout=None):
        if "get-products" in url:
            return Respuesta({"data": [{"s": "AAPLBUSDT", "tags": ["bStocks"]}, {"s": "BTCUSDT", "tags": ["pow"]}]})
        return Respuesta(texto="<ListBucketResult><Prefix>data/futures/um/monthly/klines/</Prefix>"
                               "<CommonPrefixes><Prefix>data/futures/um/monthly/klines/LUNAUSDT/</Prefix></CommonPrefixes>"
                               "<CommonPrefixes><Prefix>data/futures/um/monthly/klines/BLUEBIRDUSDT/</Prefix></CommonPrefixes>"
                               "<CommonPrefixes><Prefix>data/futures/um/monthly/klines/BTCUSDT_230331/</Prefix></CommonPrefixes>"
                               "<CommonPrefixes><Prefix>data/futures/um/monthly/klines/BTCUSDT/</Prefix></CommonPrefixes>"
                               "<IsTruncated>false</IsTruncated></ListBucketResult>")

    def info(self, mercado):
        if mercado == "spot":
            return {"symbols": [
                {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "status": "TRADING", "permissionSets": [["SPOT"]]},
                {"symbol": "OLDUSDT", "baseAsset": "OLD", "quoteAsset": "USDT", "status": "BREAK", "permissionSets": [["SPOT"]]},
                {"symbol": "BTCUPUSDT", "baseAsset": "BTCUP", "quoteAsset": "USDT", "status": "BREAK", "permissionSets": [["LEVERAGED"]]},
                {"symbol": "USDCUSDT", "baseAsset": "USDC", "quoteAsset": "USDT", "status": "TRADING", "permissionSets": [["SPOT"]]},
                {"symbol": "AAPLBUSDT", "baseAsset": "AAPLB", "quoteAsset": "USDT", "status": "TRADING", "permissionSets": [["SPOT"]]},
                {"symbol": "ETHBTC", "baseAsset": "ETH", "quoteAsset": "BTC", "status": "TRADING", "permissionSets": [["SPOT"]]},
            ]}
        return {"symbols": [
            {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "contractType": "PERPETUAL", "underlyingType": "COIN"},
            {"symbol": "TSLAUSDT", "baseAsset": "TSLA", "quoteAsset": "USDT", "contractType": "TRADIFI_PERPETUAL", "underlyingType": "EQUITY"},
            {"symbol": "XAUUSDT", "baseAsset": "XAU", "quoteAsset": "USDT", "contractType": "PERPETUAL", "underlyingType": "COMMODITY"},
            {"symbol": "BTCUSDT_261225", "baseAsset": "BTC", "quoteAsset": "USDT", "contractType": "CURRENT_QUARTER", "underlyingType": "COIN"},
        ]}


def test_universo_con_retirados_y_sin_lo_que_no_es_cripto():
    pares = {(p.mercado, p.simbolo) for p in rc.universo(BinanceFalso())}
    assert pares == {("spot", "BTCUSDT"), ("spot", "OLDUSDT"), ("futures", "BTCUSDT"), ("futures", "LUNAUSDT")}


class VelasFalsas:
    def __init__(self, velas):
        self.velas = velas
        self.pedidos = []

    def velas_diarias(self, mercado, simbolo, desde, hasta):
        self.pedidos.append((desde, hasta))
        return [v for v in self.velas if desde <= v.dia <= hasta], hasta


def test_cache_de_velas(tmp_path):
    todas = [vela(date(2022, 9, 1) + timedelta(days=i), 1.0 + i, 1.0 + i) for i in range(30)]
    falso = VelasFalsas(todas)
    par = rc.Par("spot", "XUSDT", "X")
    primeras = rc.velas_cacheadas(falso, par, date(2022, 9, 20), tmp_path)
    assert len(primeras) == 20 and falso.pedidos == [(date(2022, 9, 1), date(2022, 9, 20))]
    segundas = rc.velas_cacheadas(falso, par, date(2022, 9, 30), tmp_path)
    assert segundas == todas and falso.pedidos[-1] == (date(2022, 9, 21), date(2022, 9, 30))
    rc.velas_cacheadas(falso, par, date(2022, 9, 30), tmp_path)
    assert len(falso.pedidos) == 2  # nada nuevo que pedir
    # Un par sin velas recuerda hasta dónde se revisó.
    vacio = rc.Par("spot", "NADAUSDT", "NADA")
    rc.velas_cacheadas(VelasFalsas([]), vacio, date(2022, 9, 30), tmp_path)
    otro = VelasFalsas([])
    rc.velas_cacheadas(otro, vacio, date(2022, 10, 5), tmp_path)
    assert otro.pedidos == [(date(2022, 10, 1), date(2022, 10, 5))]


def test_csv_comprimido_ida_y_vuelta(tmp_path):
    ruta = tmp_path / "f.csv.gz"
    filas = [{"a": "1", "b": "x"}, {"a": "2", "b": ""}]
    rc.escribir(ruta, ["a", "b"], filas)
    primera = ruta.read_bytes()
    rc.escribir(ruta, ["a", "b"], filas)
    assert ruta.read_bytes() == primera  # mismo contenido, mismo archivo
    assert rc.leer(ruta) == filas
