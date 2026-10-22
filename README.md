# Red-Neuronal-Momentos

Red neuronal que, cada día a las **19:30 (hora Lima)**, revisa las monedas que salieron en las listas de
seguimiento de [Momento-A](https://github.com/LuisP11127/Momento-A) y
[Momento-B](https://github.com/LuisP11127/Momento-B) y dice cuáles pueden llegar a **+50 % en los 10 días
siguientes**. [Scanner-pump](https://github.com/LuisP11127/Scanner-pump) se usa para comparar.

**Web:** https://luisp11127.github.io/Red-Neuronal-Momentos/ (cuando GitHub Pages esté activado, ver
[Workflows de GitHub](#workflows-de-github)).

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

### `datos/senales.csv`

Las señales de cada fila de `etiquetas.csv` **a las 19:30 (hora Lima)**, solo con lo que se sabía a esa
hora (la lista completa está en `red_momentos/senales.py`):

- **velas diarias** hasta la del día: distancia a las medias MA(7), MA(25) y MA(99), velas seguidas sobre
  la MA(7), variación y rango de la vela, mechas, variaciones de 3, 7 y 30 días, volatilidad, volumen frente
  a su media, número de operaciones, compras agresivas (*taker buy*), distancia al máximo y al mínimo,
  explosiones anteriores (velas de +10 % y de +50 % de mínimo a máximo) y edad del par;
- **listas**: en cuáles salió ese día y en cuántos de los 7 días anteriores;
- **futuros** (archivos de data.binance.vision): la última foto del **libro de órdenes** antes de las 00:30
  UTC (qué parte de lo que hay a ±0,2, 1, 2 y 5 % son compras, cuánto hay a ±2 % frente al volumen del día
  y cuánto está cerca del precio), y el **interés abierto** y las **relaciones long/short** (`metrics`).
  En spot quedan vacías.

`completa` vale 1 cuando ya estaba todo publicado; data.binance.vision publica cada día hacia las 08:00
UTC del día siguiente, así que las filas de los dos últimos días se completan después. A Binance le
faltan algunos días de libro (por ejemplo, el 8 de octubre de 2026): esas filas quedan sin libro.

### `datos/reconstruccion/filas.csv.gz`

Las listas de Momento-A y Momento-B **reconstruidas desde 2023** con las reglas por defecto de cada
escáner, sobre la vela diaria cerrada, con su etiqueta y sus señales. Va aparte de las listas reales: sirve
para que la red tenga más ejemplos, y sus aciertos se miden solo con las listas reales. Los filtros que se
eligen a mano en las webs no entran.

- **Momento-A:** MA(7) < MA(25) < MA(99), cierre a no más de 2 % por debajo de la MA(7) y vela verde.
- **Momento-B:** MA(7) > MA(25) y MA(7) < MA(99).

Se revisan todos los pares en USDT de spot y de futuros perpetuos que cotizaron desde 2023, **también los
que Binance ya retiró** (si no, solo quedarían las monedas que sobrevivieron), sin monedas estables, tokens
apalancados, acciones tokenizadas ni futuros que no son criptomonedas.

La etiqueta se calcula con velas diarias: la referencia es la apertura de las 00:00 UTC (19:00 en Lima) y el
máximo, el de las 10 velas diarias siguientes. En las listas reales coincide con la etiqueta exacta de las
19:30 en 834 de 835 casos.

Comparada con las listas reales del 30 de septiembre al 20 de octubre de 2026, la reconstrucción de
Momento-B tiene casi las mismas monedas (98 %). La de Momento-A coincide en el 38 %, porque la web mira la
vela en curso (muchas eran verdes al escanear y cerraron rojas) y porque a veces se usó «No exigir MA25 <
MA99».

## La red

`python -m red_momentos.red` entrena la red y escribe `modelo/red.json` (el modelo) y
`modelo/INFORME.md` (los resultados). Es un perceptrón multicapa de scikit-learn (64 y 32 neuronas); la
puntuación es la media de 5 redes entrenadas con distinta semilla. Se guarda como cuantiles y pesos en JSON y
predice con numpy, así no depende de la versión de scikit-learn.

- **Tramos por fecha**, sin mezclar días y con 11 días de separación (la etiqueta dura 10): prueba con los
  últimos 90 días (o desde el inicio de las listas reales, mientras lleven menos), validación con los 150
  días anteriores y entrenamiento con todo lo de antes. En validación y entrenamiento entran la
  reconstrucción y las listas reales de esos días, así que con el tiempo la red también aprende de tus
  listas. Entrenar cada lunes mueve los tramos.
- **Elección:** se prueban dos regularizaciones y dos números de épocas, y se queda la que mejor ordena la
  validación.
- **Umbral:** muestra una moneda si su puntuación supera el umbral más bajo con el que, en la validación, al
  menos **3 de cada 10** llegaron a +50 % (con al menos 20 monedas sobre el umbral). Si ninguno lo consigue,
  no muestra nada.
- **Comparación:** una regresión logística con las mismas señales y elegir al azar.
- La red no usa la banda de ±0,2 % del libro: Binance la publica solo desde enero de 2026 y la red
  aprendería la fecha y no la señal.
- El informe dice también en qué señales se apoya más la red.

## La predicción de cada día

`python -m red_momentos.prediccion` (paso del workflow **Diario**, a las 19:30 hora Lima) puntúa las monedas
de Momento-A y Momento-B del día cuya vela acaba de cerrar y guarda `predicciones/AAAA-MM-DD.json`: todas
las candidatas ordenadas por puntuación, el precio a esa hora, cuáles pasan el umbral (`mostrar`) y sus
señales.

Las señales son las mismas que en `datos/senales.csv`, pero el libro y las métricas de futuros se toman de
la API en ese momento, porque los archivos de data.binance.vision salen al día siguiente. La foto del libro
de la API trae hasta 1000 niveles por lado: en las monedas muy líquidas no llega a ±5 % y esas bandas quedan
vacías. Como cada predicción guarda sus señales, se pueden comparar con las de `datos/senales.csv` de la
misma moneda cuando se publiquen. Si el día ya tiene predicción no se repite, así conserva el precio de la
primera.

## La web

`python -m red_momentos.web sitio` genera la página (la publica el workflow **Web**):

- **Lista del día:** solo las monedas que pasan el umbral, cada una con su puntuación, el precio de las
  19:30, el precio actual, el máximo desde las 19:30 y si ya llegó a +50 %. Si ninguna pasa el umbral, lo
  dice y no muestra nada. Debajo, todas las candidatas del día ordenadas por puntuación.
- **Seguimiento de la red:** las monedas que mostró cada día con su resultado a 10 días (verde si llegó a
  +50 %), cuántas acertó y cuántas llegaron entre todas las candidatas de esos días, para comparar.
- **Tus estrellas** (★) al lado de cada moneda; la red no las usa.
- **Cómo decide:** el umbral y los resultados de la red en la validación y con tus listas reales.
- **Gráficos de velas 1D** (las diarias de Binance, que abren a las 00:00 UTC; se ven en hora Lima, así que
  la vela del día de la lista lleva su fecha) con **todo el historial del par**: la página pide 1000 velas por
  petición y sigue hacia atrás hasta la primera vela que tiene Binance. Llevan MA(7), MA(25) y MA(99) con los
  colores de Binance, una flecha en la vela del día de la lista y líneas en el precio de las 19:30 y en su
  +50 %. Las monedas que muestra la red tienen su gráfico en la tarjeta; cualquier moneda de las tablas se
  abre a pantalla completa (rueda o pellizco para acercar, `←` / `→` para pasar de moneda, `0` para ver todo
  el historial, `Esc` para cerrar), con el volumen y los valores de cada vela al pasar el ratón.

Los precios, el máximo de los últimos 10 días y las velas los pide la página a Binance desde tu navegador
(`api.binance.com` y `fapi.binance.com`).

## Workflows de GitHub

| Workflow | Cuándo | Qué hace |
|---|---|---|
| **Diario** (`diario.yml`) | Cada día a las 00:30 UTC (19:30 hora Lima) y a mano en **Actions → Diario → Run workflow**. | Copia las tres listas, calcula las etiquetas y las señales y guarda los cambios en `datos/`. El resumen de la ejecución trae la tabla de cuántas llegaron a +50 %. |
| **Entrenar** (`entrenar.yml`) | Cada lunes a las 01:07 UTC y a mano. | Entrena la red y guarda `modelo/`. El informe sale en el resumen de la ejecución. |
| **Reconstrucción** (`reconstruccion.yml`) | Solo a mano. | Rehace `datos/reconstruccion/filas.csv.gz`. La primera vez tarda unas 2-3 horas; lo descargado queda en la caché de Actions. |
| **Web** (`web.yml`) | Tras cada Diario, Entrenar y Reconstrucción, cada cambio en `main` y a mano. | Publica la web en GitHub Pages. |
| **Tests** (`tests.yml`) | En cada pull request y cambio en `main`. | Pasa las pruebas. |

GitHub solo ejecuta los workflows programados desde la rama principal, así que **Diario** y **Entrenar**
empiezan a correr solo cuando este código está en `main`. Para que **Web** publique la página, GitHub Pages
tiene que estar activado con **Settings → Pages → Build and deployment → Source: GitHub Actions**.

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
# Calcular las etiquetas y las señales
python -m red_momentos.etiquetas
python -m red_momentos.senales
# Reconstruir las listas desde 2023 (unas 2-3 horas; guarda lo descargado en cache/)
python -m red_momentos.reconstruccion
# Entrenar la red
python -m red_momentos.red
# Lista de la red para el día cuya vela acaba de cerrar
python -m red_momentos.prediccion
# Web (sitio/index.html y sitio/datos.json)
python -m red_momentos.web sitio
```

## Tests

```bash
pip install pytest
python -m pytest
```

> Esto es una herramienta de filtrado, no una recomendación de inversión.
