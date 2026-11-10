# Mejoras de la red

Cambios del 9 de noviembre de 2026, después de revisar cómo le iba a la red desde que salen sus listas diarias.

## Resumen

1. **Las 3 mejores de cada día en lugar del umbral.** Del 21 de octubre al 4 de noviembre la red no mostró ninguna
   moneda: el umbral (0,353) se elegía con la red de validación y se aplicaba a la red final, entrenada con más
   datos, cuya mejor puntuación en esos días fue 0,308. El orden sí servía: en los días ya cerrados, la mejor del
   día llegó a +50 % la mitad de las veces. Ahora muestra siempre las 3 primeras del día.
2. **Se elige el modelo, no solo la configuración de la red.** Se comparan una red neuronal, una regresión
   logística y árboles de gradiente. La red no ganaba a la logística: en los 7 informes del historial la logística
   ordenaba igual o mejor la prueba.
3. **Cortes en el tiempo en lugar de una sola validación.** Cada candidato se mide en 6 tramos de 90 días,
   entrenado cada vez solo con lo anterior, y el informe da márgenes (intervalo del 90 % remuestreando días).
4. **Se elige por lo que se ve:** los aciertos de las 3 mejores de cada día, no el AUC de todas las filas juntas.
   Las **señales relativas al día** (la posición de cada moneda entre las candidatas de su día) se probaron y no
   se añadieron: no mejoraron las 3 mejores de cada día.
5. **Pesos por racha:** cada fila pesa `1/√n`, con `n` los días seguidos que esa moneda estuvo en las listas.
   Mejoró un poco las 3 mejores de cada día en los tres tipos de modelo.
6. **Riesgo de caída:** un segundo modelo puntúa la probabilidad de caer −20 % sin llegar a +50 %. De las 3
   mejores de cada día, 4 de cada 10 caían así (de todas las candidatas, 1 de cada 6 de media). Se muestra como aviso; no
   cambia el orden porque bajar las caídas costaba aciertos.

También se corrigió una cuenta: en los días que todavía tienen candidatas pendientes, las únicas con resultado
son las que ya llegaron a +50 %. Esos días ya no cuentan ni para entrenar ni para medir: hacían creer que llegaban más
de las que de verdad llegan (en la prueba con tus listas reales, «al azar» salía un 7,8 %; en los días cerrados es
un 6,9 %).

## Cómo se midió

- Los mismos datos que la red: la reconstrucción desde 2023 y tus listas reales (183 771 filas con resultado).
- **7 cortes** de 90 días (desde el 1 de enero de 2025, el 1 de abril, el 1 de julio... hasta el 19 de septiembre
  de 2026). Para cada uno, el modelo se entrena con lo anterior al corte menos 11 días y se mide en esos 90 días.
- **Tus listas reales:** del 30 de septiembre al 27 de octubre de 2026 (los días ya cerrados), con el modelo
  entrenado hasta el 19 de septiembre. Son 24 días con lista y 90 ganadoras: cada cifra cambia mucho por azar.
- **3 mejores:** de las 3 mejor puntuadas de cada día, qué parte llegó a +50 % (la media de los cortes). Al azar,
  entre el 2,6 y el 8,7 % según el corte.
- **Cayeron:** de esas 3, qué parte cayó −20 % en los 10 días sin llegar a +50 %. Al azar, el 16 % de media
  (entre el 6 y el 46 % según el corte: depende mucho de cómo iba el mercado).

## Qué modelo

| Modelo | AUC | 3 mejores: llegaron | La mejor del día llegó | 3 mejores: cayeron −20 % |
|---|---:|---:|---:|---:|
| Regresión logística | 0,657 | 18,8 % | 22,7 % | 40,1 % |
| Árboles pequeños (7 hojas, 200 árboles) | 0,648 | 18,4 % | 19,6 % | 39,9 % |
| Árboles medianos (15 hojas, 300 árboles) | 0,640 | 18,1 % | 19,9 % | 38,1 % |
| Árboles grandes (31 hojas, 600 árboles) | 0,635 | 17,2 % | 18,9 % | 37,2 % |
| Red neuronal (la de antes: 64 y 32, 5 semillas) | 0,647 | 17,5 % | 18,8 % | 38,8 % |

Las diferencias son pequeñas (con 7 cortes de ~270 monedas mostradas cada uno, el margen de la media es de ±1-2
puntos), pero van en la misma dirección: cuanto más complejo el modelo, más se aprende el pasado y peor elige las
3 mejores. Los árboles grandes no se dejaron como candidatos.

## Pesos por racha y señales relativas al día

| Modelo | Sin nada | Con señales del día | Con pesos | Con las dos |
|---|---:|---:|---:|---:|
| Regresión logística | 18,8 % | 16,7 % | 19,7 % | 18,5 % |
| Árboles pequeños | 18,4 % | 18,0 % | 19,0 % | — |
| Red neuronal (64 y 32; con 5 semillas sin nada, con 3 lo demás) | 17,5 % | — | 18,3 % | 18,2 % |

(3 mejores de cada día: llegaron a +50 %, media de los 7 cortes.)

- **Pesos:** mejoran en los tres modelos, poco pero siempre. Se dejaron.
- **Señales del día** (posición entre las candidatas del día en tamaño de la vela, volatilidad, volumen relativo,
  variaciones, distancia al mínimo y al máximo, explosiones, edad, libro e interés abierto): suben algo el AUC de
  los árboles y de la red, pero no mejoran las 3 mejores de cada día en ningún modelo. No se añadieron.

## Riesgo de caída

Con la regresión logística, ordenando las candidatas de distintas formas:

| Orden | 3 mejores: llegaron | 3 mejores: cayeron −20 % sin llegar |
|---|---:|---:|
| Puntuación | 18,8 % | 40,1 % |
| Puntuación − riesgo / 4 | 17,8 % | 36,3 % |
| Puntuación × (1 − riesgo) | 17,6 % | 37,8 % |
| Puntuación × (1 − 2 × riesgo) | 15,8 % | 32,6 % |
| Puntuación / riesgo | 9,0 % | 21,4 % |

El modelo de riesgo ordena las caídas con un AUC de 0,63 de media (de 0,49 a 0,77 según el corte), y su
puntuación va cada vez más unida a la de +50 % (correlación de −0,2 en 2025 y de 0,5 en 2026): las monedas que
más pueden subir son las que más pueden caer. Evitar las caídas cuesta aciertos casi uno a uno, así que el orden
sigue siendo el de la puntuación y el riesgo se muestra al lado de cada moneda, para decidir con él.

`RIESGO_PESO` en `red_momentos/red.py` deja ordenar por puntuación × (1 − peso × riesgo) si se prefiere arriesgar
menos.

## El modelo que queda

Con todo junto (pesos por racha, sin señales del día, solo días cerrados), `python -m red_momentos.red` compara los
tres modelos en 6 cortes de 90 días, del 29 de marzo de 2025 al 19 de septiembre de 2026:

| Modelo | AUC | 3 mejores: llegaron | 3 mejores: cayeron −20 % sin llegar |
|---|---:|---:|---:|
| Red neuronal (64 y 32, 3 semillas) | 0,639 | 19,5 % | 38,2 % |
| **Regresión logística (elegida)** | 0,644 | **20,9 %** | 39,0 % |
| Árboles de gradiente | 0,648 | 20,7 % | 40,8 % |

Con tus listas reales (del 30 de septiembre al 28 de octubre, 25 días cerrados), la logística entrenada hasta el 19
de septiembre habría mostrado 75 monedas y **llegaron 23 (31 %, entre el 21 y el 40 %)**; al azar llegó el 6,8 %.
La mejor de cada día llegó 10 de 25 días. De esas 75, 31 cayeron −20 % sin llegar (41 %; al azar, el 33 %).

Cada lunes se vuelve a elegir entre los tres: con diferencias tan pequeñas, la elección puede cambiar de una
semana a otra sin que eso signifique mucho. Todo está en [`modelo/INFORME.md`](../modelo/INFORME.md).
