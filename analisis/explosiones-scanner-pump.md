# Explosiones de +50 % en el seguimiento de Scanner-pump

Análisis del 11 de noviembre de 2026. Pregunta: de las monedas que en un día subieron +50 % de mínimo a máximo,
¿cómo estaban el día del análisis y a qué hora sucedió la explosión?

## Resumen

- **245 explosiones** del 1 de octubre al 8 de noviembre (39 días): las monedas del seguimiento de Scanner-pump
  cuya vela diaria fue de +50 % o más de mínimo a máximo. 139 fueron **subidas** (el mínimo llegó antes que el
  máximo) y 106 **caídas** (primero el máximo y después el mínimo).
- **Las subidas pasan casi todas de noche y por la mañana, no al abrir la vela.** El mínimo suele estar cerca de
  la apertura (mediana: 21:00 hora Lima) y el +50 % sobre ese mínimo se completa, de mediana, a las **9:00 de la
  mañana siguiente**. Solo 2 de 138 lo hicieron en la primera media hora (antes de las 19:30) y 23 en las primeras
  6 horas. A las 19:30 el precio iba igual que en la apertura (mediana −0,1 %) y desde ahí quedaba de mediana
  +60 % hasta el máximo del día: **91 de las 139 subidas (65 %) todavía daban +50 % desde el precio de las
  19:30.**
- **El día del análisis, subidas y caídas se ven distintas.** Antes de una subida, la vela del análisis era
  moderada (mediana 23 % de mínimo a máximo) y la explosión trae **7,4 veces su volumen**. Antes de una caída, la
  vela del análisis ya había explotado (mediana 51 %) y el volumen apenas crece (1,4 veces): la caída es la
  vuelta de la explosión del día anterior.
- **Las listas de Momento-A y Momento-B ven pocas.** De las 211 explosiones cuyo día de análisis tiene listas,
  solo 31 (15 %) estaban en ellas ese día: 15 de 122 subidas y 16 de 89 caídas. Con los dos días anteriores, 47.
- **La red.** Desde el 21 de octubre hubo 101 explosiones en días con lista de la red; 13 eran candidatas. Con el
  modelo nuevo, la red habría mostrado 8 de ellas entre sus 3 del día, pero solo 3 fueron subidas (BLESS el 27,
  IDOL el 28 y LYN el 4 de noviembre); las otras 5 explotaron hacia abajo.

## Cómo se midió

- **Explosiones:** los archivos `datos/seguimiento/` de Scanner-pump (las monedas con vela de +10 % o más), solo
  las de `pct_rango` ≥ 50 (máximo / mínimo − 1 de la vela). Si una moneda está en spot y en futuros el mismo día,
  cuenta una vez (futuros): 228 de futuros y 17 de spot.
- **Día del análisis** (`fecha_analisis`): la vela anterior a la explosión, la que Scanner-pump guarda en
  `analisis`. Es también el día de la lista de Momento-A y Momento-B con que se compara: la red puntúa la lista de
  ese día a las 19:30 hora Lima, media hora después de que abra la vela de la explosión.
- **Hora de la explosión:** velas de 15 minutos de Binance del día de la explosión (de 19:00 a 19:00 hora Lima).
  La hora de una vela es la de su apertura, así que todo va con un margen de 15 minutos. **+50 %** es la primera
  vela en que el máximo llega a +50 % sobre el mínimo de lo que va de día.
- **La red:** las predicciones de `predicciones/`, con las listas pasadas puntuadas otra vez con el modelo nuevo
  (ver abajo). La red mide +50 % en 10 días, no en una vela: una moneda puede llegar a +50 % sin explotar en un
  día, y al revés.
- Todas las filas, en [`explosiones-scanner-pump.csv`](explosiones-scanner-pump.csv).

## A qué hora explotan (subidas)

| Momento (hora Lima) | Mediana | La mitad, entre |
|---|---|---|
| El mínimo del día | 21:00 | 19:30 y 01:15 |
| Se completa el +50 % sobre el mínimo | 09:00 | 02:45 y 12:30 |
| El máximo del día | 12:00 | 05:45 y 16:00 |

Del mínimo al +50 % pasaron de mediana 7 h 45 min (la mitad, entre 3 y 13 h 30 min).

Cuándo se completó el +50 %, por tramos de 4 horas desde la apertura:

| Tramo (hora Lima) | Subidas |
|---|---:|
| 19:00 a 23:00 | 13 |
| 23:00 a 03:00 | 23 |
| 03:00 a 07:00 | 23 |
| 07:00 a 11:00 | 30 |
| 11:00 a 15:00 | 30 |
| 15:00 a 19:00 | 19 |

Las horas con más subidas completadas fueron las 10 y las 11 de la mañana (23 de 138). Las caídas van al
revés: el máximo, de mediana, a las 22:00 y el mínimo hacia el mediodía siguiente.

**Desde las 19:30**, cuando la red calcula su lista: de mediana, el máximo del resto del día estaba +60 % por
encima (la mitad, entre +45 % y +81 %) y el mínimo −5 % por debajo.

## Cómo estaban el día del análisis

| | Subidas (139) | Caídas (106) |
|---|---:|---:|
| Vela del análisis, mínimo a máximo (mediana) | 23 % | 51 % |
| … con vela de 15 % o más | 89 (64 %) | 92 (87 %) |
| … con vela de 50 % o más | 36 (26 %) | 54 (51 %) |
| … cerró verde | 78 (56 %) | 67 (63 %) |
| Volumen de la explosión / volumen del análisis (mediana) | 7,4 veces | 1,4 veces |
| Explosión, cierre frente a apertura (mediana) | +36 % | −26 % |

Como en el análisis [qué tenían en común](que-tenian-en-comun.md), las que explotan ya se movían el día antes: 3
de cada 4 tenían una vela de 15 % o más. Lo que separa una subida de una caída es que la caída llega después de
una vela que ya había explotado, y la subida, después de una vela más moderada y con un salto grande de volumen
el día de la explosión.

## En las listas y en la red

| | Explosiones | En la lista ese día | Subidas en la lista | Caídas en la lista |
|---|---:|---:|---:|---:|
| Días con listas de Momento-A o Momento-B (desde el 30 de septiembre) | 211 | 31 | 15 de 122 | 16 de 89 |

Desde el 21 de octubre, con la red (puntuación del modelo nuevo):

| Día del análisis | Moneda | Puesto en la red | ¿La mostró? | Explosión |
|---|---|---|---|---|
| 27 oct | BLESS | 1 de 123 | sí | subida, +56 % |
| 27 oct | IDOL | 2 de 123 | sí | caída, 57 % |
| 28 oct | BLESS | 1 de 61 | sí | caída, 64 % |
| 28 oct | IDOL | 2 de 61 | sí | subida, +138 % |
| 28 oct | SOPH | 31 de 61 | no | subida, +108 % |
| 29 oct | IDOL | 2 de 54 | sí | caída, 59 % |
| 29 oct | SOPH | 10 de 54 | no | caída, 59 % |
| 30 oct | ESPORTS | 7 de 70 | no | subida, +163 % |
| 30 oct | ON | 1 de 70 | sí | caída, 62 % |
| 30 oct | UAI | 12 de 70 | no | caída, 113 % |
| 2 nov | LYN | 3 de 31 | sí | caída, 59 % |
| 4 nov | LYN | 1 de 29 | sí | subida, +52 % |
| 6 nov | ON | 5 de 40 | no | subida, +52 % |

(En una caída, el porcentaje es el de la vela de mínimo a máximo.)

## Qué se puede sacar

- **Calcular a las 19:30 no llega tarde.** Casi ninguna subida había empezado a esa hora: el movimiento se hace
  durante la noche y la mañana. Llegar antes que las 19:30 no cambiaría mucho para la explosión del día siguiente.
- **Una vela de análisis que ya explotó avisa más de una caída que de otra subida.** Puede servir como señal para
  la red, o para el riesgo de caída, pero son 39 días y pocas monedas.
- **La mayor parte de las explosiones no pasa por las listas.** Con las reglas de Momento-A y Momento-B, la red
  no puede ver el 85 % de las explosiones de Scanner-pump: para verlas habría que darle otras candidatas, no
  otro modelo.

## Listas pasadas puntuadas otra vez

Las 16 listas del 21 de octubre al 8 de noviembre que se calcularon con el modelo antiguo (con umbral, que no
mostró ninguna) están puntuadas otra vez con el tipo de modelo actual (regresión logística), entrenado solo con
datos hasta el 10 de octubre: no había visto ninguno de esos días. El precio y la hora de cada lista son los de
entonces; cada archivo guarda en `repuntuada` lo que había mostrado antes. `python -m red_momentos.repuntuar` lo
repite.

En los 8 días que ya cerraron sus 10 días (del 21 al 30 de octubre), de las 24 monedas que habría mostrado
llegaron a +50 % **11 (46 %)**; entre todas las candidatas de esos días llegó el 6 % (26 de 435). Pero esas 11 son
solo tres monedas (ON siete veces, IDOL tres, AIN una), así que la cifra dice poco todavía. Cayeron −20 % sin
llegar 7 de las 24 (29 %), casi lo mismo que todas las candidatas (30 %).
