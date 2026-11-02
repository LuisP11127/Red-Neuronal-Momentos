# MA(5) y MA(25) del volumen: ¿anuncian una subida?

Análisis del 2 de noviembre de 2026, después de añadir las medias MA(5) y MA(25) a las barras de volumen de
los gráficos de Momento-A y Momento-B.

**La idea:** cuando la MA(5) del volumen está por debajo de la MA(25) y hay poco volumen varios días seguidos,
después viene una subida.

**Resumen:** con los datos desde 2023 la idea no se cumple: con ese patrón llegan a +50 % **menos** monedas que de
media (0,8 veces la media), todos los años. Lo que sí anuncia movimientos grandes es lo contrario, el volumen que
**crece** (MA(5) muy por encima de la MA(25)), aunque sirve para las dos direcciones: también hay más caídas
fuertes. Añadir estas medias a la red no mejora sus puntuaciones (ya mira el volumen de otra forma), así que no
se añadieron. Lo que sí mejoró la red es entrenarla también con los últimos resultados (ver el final).

## Cómo se midió

- Velas diarias de Binance (abren a las 00:00 UTC) de los 1117 pares de spot y de futuros que salen en la
  reconstrucción o en tus listas, también los que Binance ya retiró, desde 2023.
- El volumen es el de la moneda, como las barras de los gráficos de Momento-A y Momento-B, y las medias se
  calculan en la vela del día de la lista (la que cierra a las 19:00 hora Lima).
- **Tu patrón:** MA(5) < MA(25) al menos 3 días seguidos y, de las últimas 10 velas, al menos 7 con el volumen por
  debajo de su MA(25). También se probaron versiones más estrictas y más suaves.
- **El resultado**, como en las etiquetas de la red: desde la apertura de la vela siguiente, el máximo de las 10
  velas diarias siguientes; «llegó» si sube un +50 %. También se miró +20 % y la caída del mínimo (−20 %).
  Este cálculo coincide con las etiquetas de la red en el 100 % de la reconstrucción y el 99,8 % de tus listas.
- Dos grupos: todas las monedas todos los días, y las candidatas de Momento-A y Momento-B (la reconstrucción
  desde 2023 y tus listas reales).

## Resultados

**Todas las monedas, todos los días desde 2023** (938 458 filas, 756 monedas; de media llegan a +50 % el 5,4 %)

| Situación del volumen el día de la lista | Días con esta situación | Llegaron a +50 % | Frente a la media | Subieron +20 % | Cayeron −20 % |
|---|---:|---:|---:|---:|---:|
| **Tu patrón:** MA(5) < MA(25) 3+ días seguidos y 7+ de las últimas 10 velas con poco volumen | 46 % | 4,5 % | 0,82× | 22,1 % | 20,3 % |
| Tu patrón, más fuerte: 14+ días y 9+ de 10 velas | 15 % | 4,2 % | 0,78× | 21,5 % | 20,7 % |
| Sin tu patrón | 54 % | 6,2 % | 1,15× | 26,5 % | 20,7 % |
| Vuelve el volumen: MA(5) cruza sobre MA(25) tras 10+ días debajo | 2 % | 5,8 % | 1,07× | 25,3 % | 20,4 % |
| MA(5) ≥ MA(25) | 38 % | 6,7 % | 1,24× | 27,6 % | 20,9 % |
| Volumen que crece: MA(5) ≥ 1,75 × MA(25) | 9 % | 10,1 % | 1,86× | 33,2 % | 25,1 % |
| Volumen que explota: MA(5) ≥ 3 × MA(25) | 2 % | 14,0 % | 2,58× | 38,2 % | 35,3 % |

| Año | Media | Con tu patrón | Sin tu patrón | MA(5) ≥ 1,75 × MA(25) |
|---|---:|---:|---:|---:|
| 2023 | 4,8 % | 3,8 % | 5,5 % | 7,7 % |
| 2024 | 5,4 % | 3,5 % | 6,9 % | 11,7 % |
| 2025 | 5,2 % | 4,6 % | 5,6 % | 10,3 % |
| 2026 | 6,2 % | 5,4 % | 6,8 % | 10,4 % |

De las veces que llegó a +50 %, el 37,4 % tenía tu patrón, frente al 45,6 % de todos los días.

| Días seguidos con MA(5) < MA(25) | Llegaron a +50 % |
|---|---:|
| 0 (MA(5) ≥ MA(25)) | 6,7 % |
| 1-2 | 5,1 % |
| 3-5 | 4,9 % |
| 6-10 | 4,7 % |
| 11-20 | 4,3 % |
| 21 o más | 4,2 % |

**Candidatas de Momento-A y Momento-B (reconstrucción desde 2023 y tus listas reales)** (183 777 filas, 754 monedas; de media llegan a +50 % el 4,9 %)

| Situación del volumen el día de la lista | Días con esta situación | Llegaron a +50 % | Frente a la media | Subieron +20 % | Cayeron −20 % |
|---|---:|---:|---:|---:|---:|
| **Tu patrón:** MA(5) < MA(25) 3+ días seguidos y 7+ de las últimas 10 velas con poco volumen | 44 % | 4,1 % | 0,85× | 21,3 % | 16,4 % |
| Tu patrón, más fuerte: 14+ días y 9+ de 10 velas | 13 % | 3,9 % | 0,80× | 20,7 % | 16,7 % |
| Sin tu patrón | 56 % | 5,5 % | 1,12× | 24,5 % | 16,9 % |
| MA(5) ≥ MA(25) | 39 % | 6,0 % | 1,22× | 25,8 % | 17,4 % |
| Volumen que crece: MA(5) ≥ 1,75 × MA(25) | 10 % | 8,5 % | 1,75× | 29,9 % | 22,9 % |
| Volumen que explota: MA(5) ≥ 3 × MA(25) | 2 % | 11,6 % | 2,39× | 35,7 % | 33,2 % |

| Año | Media | Con tu patrón | Sin tu patrón | MA(5) ≥ 1,75 × MA(25) |
|---|---:|---:|---:|---:|
| 2023 | 4,1 % | 3,0 % | 4,9 % | 6,6 % |
| 2024 | 3,4 % | 2,1 % | 4,4 % | 7,1 % |
| 2025 | 5,8 % | 5,6 % | 6,0 % | 10,6 % |
| 2026 | 5,4 % | 4,7 % | 6,0 % | 8,9 % |

De las veces que llegó a +50 %, el 37,2 % tenía tu patrón, frente al 43,9 % de todos los días.

| Días seguidos con MA(5) < MA(25) | Llegaron a +50 % |
|---|---:|
| 0 (MA(5) ≥ MA(25)) | 6,0 % |
| 1-2 | 4,5 % |
| 3-5 | 4,1 % |
| 6-10 | 4,4 % |
| 11-20 | 3,8 % |
| 21 o más | 4,2 % |

## Qué quiere decir

1. **La idea no se cumple.** Con poco volumen varios días seguidos llegan a +50 % menos monedas que de media, y
   cuanto más dura la sequía de volumen, menos (del 6,7 % sin sequía al 4,2 % tras 21 días o más). Pasa los cuatro
   años y en los dos grupos. Que el volumen vuelva después de la sequía (la MA(5) cruza por encima de la MA(25))
   tampoco ayuda: queda en la media.
2. **Por qué parece cumplirse:** el patrón es muy frecuente (casi la mitad de los días), así que muchas subidas
   lo tienen antes (el 37 % de las que llegaron a +50 %). Pero lo tiene un porcentaje aún mayor de los días en los
   que no pasó nada.
3. **Lo que sí sirve: el volumen que crece.** Con la MA(5) del volumen 1,75 veces por encima de la MA(25), llegan a
   +50 % casi el doble que de media, y con 3 veces, 2,4-2,6 veces la media, todos los años. Pero las caídas de −20 %
   también son más frecuentes (del 20 % al 25-35 %): avisa de que viene un **movimiento grande**, no de hacia dónde.
   En el gráfico, la MA(5) muy por encima de la MA(25) dice «esta moneda se está moviendo»; la dirección hay que
   buscarla en otras cosas.

## ¿Ayudan a la red?

Se entrenó la red con tres señales nuevas (MA(5)/MA(25) del volumen, días seguidos con MA(5) < MA(25) y velas
con poco volumen de las últimas 10) y sin ellas, con los mismos datos, configuración y semillas, en cinco cortes
en el tiempo (se entrena con lo anterior a cada corte y se mide en los 90 días siguientes):

| Corte | AUC sin ellas | AUC con ellas | 2 % mejor puntuado: llegaron (sin / con) |
|---|---:|---:|---:|
| 2025-04-01 | 0,621 | 0,618 | 22,0 % / 23,4 % |
| 2025-08-01 | 0,624 | 0,627 | 13,2 % / 15,1 % |
| 2025-12-01 | 0,658 | 0,656 | 9,3 % / 9,3 % |
| 2026-04-01 | 0,657 | 0,654 | 21,8 % / 22,1 % |
| 2026-07-21 | 0,612 | 0,602 | 16,7 % / 16,3 % |

El AUC baja de media 0,003 y lo demás cambia dentro del ruido. La red ya mira el volumen con `vol_rel_1d`
(volumen del día frente a su media de 20 días) y `vol_rel_7d` (media de 7 días frente a las 28 anteriores), que
recogen lo mismo. Por eso no se añadieron.

## Entrenar con los últimos resultados

La red se elegía y se medía dejando fuera de su entrenamiento los ~170 días más recientes (la validación y la
prueba), y tus listas reales caían todas en la prueba: entrenarla otra vez no le enseñaba nada nuevo. En los
mismos cinco cortes, la red entrenada con todo lo que ya tenía resultado acertó más arriba de la lista, que es
lo que se ve:

| Corte | AUC (ahora / con lo último) | 2 % mejor puntuado (ahora / con lo último) | Mejor moneda del día (ahora / con lo último) |
|---|---:|---:|---:|
| 2025-04-01 | 0,621 / 0,573 | 22,0 % / 23,8 % | 15,6 % / 17,8 % |
| 2025-08-01 | 0,624 / 0,661 | 13,2 % / 15,1 % | 16,7 % / 16,7 % |
| 2025-12-01 | 0,658 / 0,686 | 9,3 % / 9,8 % | 11,1 % / 12,2 % |
| 2026-04-01 | 0,657 / 0,647 | 21,8 % / 25,2 % | 14,4 % / 22,2 % |
| 2026-07-21 | 0,612 / 0,624 | 16,7 % / 21,6 % | 13,3 % / 18,9 % |

Con el umbral elegido como siempre (en la validación), las monedas que pasan el umbral acertaron más con la red
entrenada con lo último en los tres cortes en que hubo umbral (30 % → 33 %, 8 % → 10 % y 14 % → 36 %). Desde
ahora, cada entrenamiento (el de cada lunes o el del botón **Entrenar la red ahora** de la web) elige la
configuración y el umbral como antes y, al final, entrena la red que se usa con todo lo que ya tiene resultado.
