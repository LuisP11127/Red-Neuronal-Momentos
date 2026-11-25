# Arquitecturas de redes neuronales

Comparación del 15 de noviembre de 2026. Pregunta: ¿hay alguna arquitectura de red neuronal que elija mejor que el
modelo actual (regresión logística) las 3 monedas del día?

## Resumen

- **Ninguna gana con claridad.** La mejor en los cortes fue una red recurrente (GRU) que lee solo las 30 velas
  diarias: 21,7 % de sus 3 del día llegaron a +50 %, frente a 20,9 % de la logística. Son 0,8 puntos, ganó en 3
  cortes de 6, empató en 1 y perdió en 2, y en las listas reales le fue peor (28 % frente a 31 %). La diferencia
  cabe en el ruido.
- **Más grande es peor.** Entre los perceptrones sobre las señales, el de una capa de 32 empata con la logística
  y cada capa o neurona de más baja el resultado: 19,6 % con 64 y 32, 18,3 % con 256 y 128, 17,5 % con la red
  residual y 16,9 % con el transformador, el último de todos. Normalización por lotes y *dropout* no lo
  arreglan (18,1 %). Con unas 9.000 filas que llegaron a +50 % (de 184.000), no hay datos para una red grande.
- **Las velas en bruto ordenan peor la lista entera.** Las redes que solo ven velas tienen AUC de 0,60, frente a
  0,64 de las que ven las señales: aciertan parecido arriba de la lista, pero ordenan peor el resto.
- **El modelo actual se queda.** La logística empata con la mejor red, tarda 16 segundos en todos los cortes (la GRU,
  26 minutos) y se exporta a un JSON que la página y el workflow puntúan con numpy. Cambiarla por una GRU
  obligaría a pedir 30 velas por moneda al puntuar y a cargar PyTorch, para una mejora que no se distingue del
  azar.

## Cómo se midió

Igual que `red_momentos.red` elige su modelo: 6 cortes de 90 días (de marzo de 2025 a septiembre de 2026), cada
uno entrenado solo con lo anterior y 11 días de separación, y la prueba final con las listas reales (31 días, 93
monedas mostradas). La medida es la que se ve en la página: de las 3 mejor puntuadas de cada día, qué parte llegó a
+50 % en 10 días. Todos usan los mismos pesos por racha (1/√n) y las señales pasadas por cuantiles.

Las redes de PyTorch se entrenaron 12 épocas con AdamW (tasa 0,001, lotes de 512) y pérdida binaria ponderada, con 3
semillas por corte (el transformador, con 1: con 2 no terminaba en 2 horas en la CPU del contenedor). La puntuación
de cada corte es el promedio de las semillas.

Las redes de velas reciben las 30 velas diarias anteriores al día de la lista, con 8 canales por vela: retorno
logarítmico, rango, cuerpo, mecha superior, volumen relativo, parte compradora menos 0,5, distancia al último cierre
y una marca de si la vela existe (para monedas con menos de 30 días).

`python analisis/arquitecturas.py --cache <velas-1d> --salida <json>` lo repite (necesita `torch`); con
`--solo nombre …` mide solo esas, y las que ya están en el JSON no se vuelven a medir.

## Resultados

| Modelo | Cortes: 3 del día que llegaron | AUC | Ganó a la logística (de 6 cortes) | Listas reales | Tiempo |
|---|---:|---:|---:|---:|---:|
| GRU solo con las 30 velas | **21,7 %** | 0,602 | 3 (1 empate) | 28,0 % (26 de 93) | 26 min |
| **Regresión logística (actual)** | 20,9 % | 0,644 | — | 31,2 % (29 de 93) | 16 s |
| Perceptrón de 1 capa (32) | 20,9 % | 0,641 | 3 | 30,1 % (28 de 93) | 52 s |
| GRU con velas y señales | 20,8 % | 0,638 | 4 | 32,3 % (30 de 93) | 28 min |
| Árboles de gradiente | 20,7 % | 0,648 | 3 | 34,4 % (32 de 93) | 1 min 45 s |
| Perceptrón de 2 capas (64 y 32) | 19,6 % | 0,638 | 3 | 33,3 % (31 de 93) | 1 min 10 s |
| Red de scikit-learn (64 y 32), la anterior | 19,5 % | 0,639 | 2 | 33,3 % (31 de 93) | 1 min 47 s |
| Perceptrón profundo (128, 64, 32 y 16) | 19,3 % | 0,634 | 2 | 36,6 % (34 de 93) | 1 min 47 s |
| Convolucional solo con las velas | 19,0 % | 0,604 | 3 | 34,4 % (32 de 93) | 9 min |
| Convolucional con velas y señales | 18,8 % | 0,626 | 2 | 30,1 % (28 de 93) | 10 min |
| Perceptrón ancho (256 y 128) | 18,3 % | 0,634 | 2 | 32,3 % (30 de 93) | 1 min 55 s |
| Perceptrón (128 y 64) con normalización y *dropout* | 18,1 % | 0,639 | 3 | 31,2 % (29 de 93) | 3 min 10 s |
| Red residual (3 bloques de 128) | 17,5 % | 0,633 | 3 | 29,0 % (27 de 93) | 6 min 28 s |
| Transformador de señales (FT-Transformer, 1 semilla) | 16,9 % | 0,635 | 2 | 26,9 % (25 de 93) | 72 min |

Al azar, en los cortes llegó entre el 3,6 % y el 8,8 % de las candidatas, según el corte; en las listas reales, el
6,6 %.

Por corte, la logística y la GRU de velas:

| Corte | Logística | GRU solo con velas |
|---|---:|---:|
| mar–jun 2025 | 15 % | 15 % |
| jun–sep 2025 | 13 % | 15 % |
| sep–dic 2025 | 21 % | 31 % |
| dic 2025–mar 2026 | 25 % | 21 % |
| mar–jun 2026 | 23 % | 27 % |
| jun–sep 2026 | 29 % | 21 % |

La GRU gana sobre todo por el corte de septiembre a diciembre de 2025 (31 % frente a 21 %); pierde en el de diciembre
a marzo y en el último. Cada corte son 270 monedas mostradas, y entre semillas de la misma red la cifra se mueve 1
o 2 puntos.

En las listas reales las 14 quedan entre 27 % y 37 %, y el margen de cada una (unos ±8 puntos con 93 monedas) se
cruza con el de todas: con un mes de listas no se puede ordenar los modelos.

## Qué se puede sacar

- **Con estos datos el límite no está en el modelo.** Desde una regresión logística hasta un transformador, todos
  quedan entre 17 % y 22 %. Lo que más podría mover el resultado son otras señales o más candidatas (ver
  [Explosiones de +50 % en Scanner-pump](explosiones-scanner-pump.md): el 85 % de las explosiones no pasa por las
  listas), no otra arquitectura.
- **Las velas en bruto y las señales ven cosas algo distintas.** La GRU de velas acierta parecido arriba pero ordena
  distinto (AUC 0,60). Promediar su puntuación con la de la logística es lo único de esta comparación que valdría la
  pena probar, pero no está medido aquí.
