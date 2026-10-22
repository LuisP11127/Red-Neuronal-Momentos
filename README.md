# Red-Neuronal-Momentos

Red neuronal que, cada día a las **19:30 (hora Lima)**, revisa las monedas que salieron en las listas de
seguimiento de [Momento-A](https://github.com/LuisP11127/Momento-A) y
[Momento-B](https://github.com/LuisP11127/Momento-B) y dice cuáles pueden llegar a **+50 % en los 10 días
siguientes**. [Scanner-pump](https://github.com/LuisP11127/Scanner-pump) se usa para comparar.

Estado: ya están la copia diaria de las tres listas y las etiquetas (qué monedas llegaron a +50 %). Falta
lo que se describe en [Lo que falta](#lo-que-falta).

## Días y velas

Todas las velas son las diarias de Binance, que abren a las **00:00 UTC** (19:00 en Lima). Las tres listas
nombran cada día con la fecha en que abre la vela en hora de Lima, que es la del día anterior:

| Día de la lista | Vela de Binance (UTC) | En Lima |
|---|---|---|
| 2026-10-15 | abre el 16 oct a las 00:00 UTC y cierra el 17 a las 00:00 UTC | del 15 oct a las 19:00 al 16 a las 19:00 |

## Datos

### `datos/listas/`

Copia de las listas de seguimiento, un archivo por día, tal como los guarda cada repositorio:

| Carpeta | Viene de | Qué trae cada moneda |
|---|---|---|
| `momento-a/` | `Momento-A/docs/seguimiento/` | precio y hora del escaneo; la estrella (si tiene) y, desde el 19 oct, el índice de giro (`giro`) y una foto del libro de órdenes (`libro`) |
| `momento-b/` | `Momento-B/docs/seguimiento/` | lo mismo, y las estrellas aparte en `estrellas.json` |
| `scanner-pump/` | `Scanner-pump/datos/seguimiento/` | la vela de la explosión (+10 % o más) y la del día de análisis |

Los días nuevos o cambiados se copian y los que se borran en el repositorio de origen (botón **Borrar** de
su web) se borran aquí. Un archivo que no se puede leer no se copia y se conserva la copia anterior. La
red no usa las estrellas: se copian para mostrar al lado de su lista si coinciden.

### `datos/etiquetas.csv`

Una fila por moneda y día de Momento-A y Momento-B. Si la misma moneda salió en spot y en futuros, o en las
dos listas, cuenta una vez (como **No repetidas**). Se toma futuros si salió en futuros, porque es el
mercado con historial del libro de órdenes.

**Regla:** el máximo de los 10 días siguientes llega a +50 % sobre el precio de referencia.

El precio de referencia es el de las **19:30 en Lima (00:30 UTC)** después del cierre de la vela del día de
la lista, la hora a la que la red da su lista; no el precio del escaneo. Para el día «2026-10-15», la vela
cierra el 16 a las 19:00 y la referencia es el precio del 16 a las 19:30; los 10 días van hasta el 26 a las
19:30. Se mide con velas de 30 minutos: la referencia es la apertura de la vela que empieza a las 19:30.

Si la subida se contara desde el escaneo, la red aprendería a señalar monedas que ya subieron antes de las
19:30, y esa subida ya no se puede aprovechar.

| Columna | Qué es |
|---|---|
| `fecha` | día de la lista |
| `moneda`, `mercado`, `simbolo` | la moneda (sin el multiplicador: 1000PEPE → PEPE) y el par que se usa |
| `listas` | en qué listas salió ese día |
| `vela_utc` | día UTC en que abre la vela de la lista |
| `referencia` | precio a las 19:30 (hora Lima) |
| `maximo`, `pct_maximo` | el máximo de los 10 días siguientes y cuánto es frente a la referencia |
| `minimo`, `pct_minimo` | lo mismo con el mínimo |
| `dias_hasta_50` | en qué día (1 a 10) llegó a +50 % |
| `dias_vistos` | cuántos de los 10 días ya pasaron |
| `estado` | `llego`, `no_llego`, `pendiente` (aún no pasaron los 10 días o aún no son las 19:30 de ese día) o `sin_datos` |
| `explosion_mismo_dia` | `1` si ese mismo día salió en Scanner-pump |
| `explosiones_despues` | días de los 10 siguientes en que salió en Scanner-pump |

Las filas que ya tienen resultado final no se vuelven a calcular.

## Workflows de GitHub

| Workflow | Cuándo | Qué hace |
|---|---|---|
| **Diario** (`diario.yml`) | Cada día a las 00:30 UTC (19:30 hora Lima) y a mano en **Actions → Diario → Run workflow**. | Copia las tres listas, calcula las etiquetas y guarda los cambios en `datos/`. El resumen de la ejecución trae la tabla de cuántas llegaron a +50 %. |
| **Tests** (`tests.yml`) | En cada pull request y cambio en `main`. | Pasa las pruebas. |

GitHub solo ejecuta los workflows programados desde la rama principal, así que **Diario** empieza a correr
solo cuando este código está en `main`.

### Binance

Solo datos públicos, sin claves. Desde los servidores de GitHub (EE. UU.) `api.binance.com` y
`fapi.binance.com` dan error 451, así que se usan `data-api.binance.vision` (spot) y `www.binance.com`
(futuros), igual que en el escaneo diario de Scanner-pump. Si tampoco responden, las velas se leen de los
archivos de `data.binance.vision`, que se publican al día siguiente hacia las 08:00 UTC.

## Línea de comandos

Requiere Python 3.10 o superior.

```bash
pip install -r requirements.txt
# Copiar las listas desde clones locales de los tres repositorios
python -m red_momentos.listas --momento-a ../Momento-A --momento-b ../Momento-B --scanner-pump ../Scanner-pump
# Calcular las etiquetas
python -m red_momentos.etiquetas
```

## Tests

```bash
pip install pytest
python -m pytest
```

## Lo que falta

1. **Señales de cada moneda** al cierre de la vela: velas, medias, volumen y compras agresivas (*taker
   buy*), explosiones anteriores, en qué listas salió, el libro de órdenes de futuros (historial `bookDepth`
   de data.binance.vision) y el interés abierto y las relaciones long/short (`metrics`).
2. **Reconstrucción desde 2023**, aparte de las listas reales: rehacer las listas de días pasados con las
   reglas por defecto de los tres escáneres (los filtros que se eligen a mano en las webs no entran) para
   que la red tenga más ejemplos. Los aciertos se miden solo con las listas reales.
3. **La red neuronal**, que muestra una moneda solo si, en las pruebas con días pasados, al menos 3 de cada
   10 monedas con esa puntuación llegaron a +50 %. Si ninguna llega, no muestra nada.
4. **La web** en GitHub Pages con la lista del día, el seguimiento de sus propias predicciones (desde el
   precio de las 19:30) y si coinciden con tus estrellas.
