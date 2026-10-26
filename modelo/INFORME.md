# Informe de la red

- Entrenamiento: 2023-01-01 a 2026-04-11 (reconstrucción y listas reales de esos días).
- Validación: 2026-04-22 a 2026-09-19 (reconstrucción y listas reales de esos días).
- Prueba: 2026-09-30 a 2026-10-19 (listas reales y, para comparar, la reconstrucción de esos días).
- Red elegida: media de 5 redes con capas [64, 32], alpha 0.1 y 20 épocas.
- Umbral: 0.353 (al menos 3 de cada 10 llegaron en la validación).

| Tramo | Filas | Llegaron | Al azar | AUC red | AUC logística | Mejor del día (red) | Mostradas | Llegaron de las mostradas | Días con lista |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| entrenamiento | 150791 | 7034 (591 monedas) | 4.7 % | 0.757 | 0.702 | 19.4 % | 263 | 173 (65.8 %) | 94 de 1182 |
| validacion | 27035 | 1421 (270 monedas) | 5.3 % | 0.639 | 0.639 | 19.9 % | 36 | 11 (30.6 %) | 30 de 151 |
| prueba: reconstrucción | 664 | 55 (12 monedas) | 8.3 % | 0.722 | 0.770 | 47.4 % | 3 | 0 (0.0 %) | 3 de 19 |
| prueba: listas reales | 908 | 63 (19 monedas) | 6.9 % | 0.709 | 0.736 | 38.9 % | 4 | 1 (25.0 %) | 4 de 18 |

AUC: probabilidad de que una moneda que llegó a +50 % puntúe más que una que no (0,5 = al azar).
Mejor del día: de la moneda mejor puntuada de cada día, qué parte llegó.

## Señales en las que más se apoya la red

Cuánto baja el AUC de la validación al desordenar cada señal.

| Señal | Caída del AUC |
|---|---:|
| `libro_prof_2` | 0.0243 |
| `explosiones_90d` | 0.0226 |
| `ls_global` | 0.0090 |
| `edad_dias` | 0.0054 |
| `vol_usdt_log` | 0.0051 |
| `dist_max_365d` | 0.0045 |
| `oi_rel_vol` | 0.0033 |
| `velas_sobre_ma7` | 0.0030 |
| `explosiones_30d` | 0.0028 |
| `libro_deseq_1` | 0.0027 |
| `dist_ma7` | 0.0023 |
| `var_30d` | 0.0022 |
| `rango_1d` | 0.0021 |
| `vol_rel_1d` | 0.0021 |
| `en_a` | 0.0020 |
