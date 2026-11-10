# Informe de la red

- Muestra las **3 mejores de cada día**, ordenadas por puntuación; el riesgo de caída se muestra al lado, sin cambiar el orden.
- Modelo elegido: **regresión logística** (el que más acertó con las 3 mejores de cada día en 6 cortes de 90 días, del 2025-03-29 al 2026-09-19).
- Prueba: 2026-09-30 a 2026-10-28 (listas reales y, para comparar, la reconstrucción de esos días), con el modelo entrenado solo con lo anterior.
- Riesgo: un segundo modelo del mismo tipo puntúa la probabilidad de caer −20 % en los 10 días sin llegar a +50 %.
- Modelo que se usa cada día: el mismo tipo, entrenado otra vez con todo lo que ya tiene resultado (hasta el 2026-10-28, 183752 filas). Las cifras de abajo son las de los modelos que no habían visto esos días.

## Comparación en los cortes

Media de los cortes. Entre paréntesis, el intervalo del 90 % (remuestreando días).

| Modelo | AUC | Llegaron de las 3 mejores | Cayeron −20 % sin llegar de las 3 mejores |
|---|---:|---:|---:|
| red neuronal (64 y 32 neuronas) | 0.639 | 19.5 % | 38.2 % |
| regresión logística (elegido) | 0.644 | 20.9 % | 39.0 % |
| árboles de gradiente | 0.648 | 20.7 % | 40.8 % |

Modelo elegido, corte por corte:

| Tramo | Filas | Llegaron (al azar) | AUC | Llegaron de las 3 mejores | La mejor del día llegó | AUC riesgo | Cayeron −20 % sin llegar, de las 3 mejores | Cayeron −20 % sin llegar, al azar |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025-03-29 a 2025-06-26 | 13449 | 1178 (8.8 %) | 0.538 | 41 de 270: 15.2 % (11-19 %) | 13.3 % | 0.662 | 44.4 % (39-51 %) | 15.3 % |
| 2025-06-27 a 2025-09-24 | 12325 | 818 (6.6 %) | 0.649 | 34 de 270: 12.6 % (10-16 %) | 18.9 % | 0.678 | 35.2 % (29-41 %) | 10.0 % |
| 2025-09-25 a 2025-12-23 | 13454 | 625 (4.6 %) | 0.698 | 56 de 270: 20.7 % (17-25 %) | 25.6 % | 0.461 | 48.9 % (43-55 %) | 37.7 % |
| 2025-12-24 a 2026-03-23 | 23083 | 830 (3.6 %) | 0.660 | 68 de 270: 25.2 % (21-29 %) | 26.7 % | 0.525 | 40.0 % (34-46 %) | 16.6 % |
| 2026-03-24 a 2026-06-21 | 16368 | 1255 (7.7 %) | 0.679 | 62 de 270: 23.0 % (19-27 %) | 28.9 % | 0.632 | 37.8 % (32-44 %) | 10.4 % |
| 2026-06-22 a 2026-09-19 | 18962 | 1044 (5.5 %) | 0.639 | 78 de 270: 28.9 % (24-34 %) | 28.9 % | 0.757 | 27.4 % (23-32 %) | 5.7 % |

## Prueba

| Tramo | Filas | Llegaron (al azar) | AUC | Llegaron de las 3 mejores | La mejor del día llegó | AUC riesgo | Cayeron −20 % sin llegar, de las 3 mejores | Cayeron −20 % sin llegar, al azar |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| prueba: reconstrucción | 647 | 38 (5.9 %) | 0.670 | 2 de 33: 6.1 % (0-12 %) | 18.2 % | 0.597 | 69.7 % (58-82 %) | 36.2 % |
| prueba: listas reales | 1358 | 93 (6.8 %) | 0.762 | 23 de 75: 30.7 % (21-40 %) | 40.0 % | 0.600 | 41.3 % (32-51 %) | 32.5 % |

AUC: probabilidad de que una moneda que llegó a +50 % puntúe más que una que no (0,5 = al azar).
Solo cuentan los días cuyos 10 días ya terminaron.

## Señales en las que más se apoya el modelo

Cuánto baja el AUC del último corte (2026-06-22 a 2026-09-19) al desordenar cada señal.

| Señal | Caída del AUC |
|---|---:|
| `libro_prof_2` | 0.0348 |
| `ls_global` | 0.0192 |
| `ls_top_cuentas` | 0.0135 |
| `oi_rel_vol` | 0.0105 |
| `vol_usdt_log` | 0.0087 |
| `ma25_ma99` | 0.0076 |
| `en_b` | 0.0073 |
| `explosiones_90d` | 0.0064 |
| `vol_rel_1d` | 0.0057 |
| `dist_max_365d` | 0.0056 |
| `dias_en_b_7d` | 0.0049 |
| `velas_sobre_ma7` | 0.0044 |
| `edad_dias` | 0.0042 |
| `dist_ma99` | 0.0036 |
| `dist_max_30d` | 0.0033 |
