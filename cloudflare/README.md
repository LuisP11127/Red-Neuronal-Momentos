# Reloj (Cloudflare)

GitHub ejecuta los workflows programados con horas de retraso (el Diario de las 19:30 salía entre las 23:30 y
la 01:00 hora Lima), pero los que se lanzan a mano arrancan en segundos. `reloj.js` es un Worker de Cloudflare
que cada día a las **00:30 UTC (19:30 hora Lima)** lanza el workflow **Diario** con la API de GitHub
(`workflow_dispatch`). El horario de `diario.yml` sigue de respaldo: si un día el Worker falla, la lista sale
igual, más tarde, y si el Worker funcionó, la ejecución tardía no repite la predicción del día.

- **Worker:** `reloj-red-neuronal-momentos`, con el Cron Trigger `30 0 * * *`.
- **Estado:** https://reloj-red-neuronal-momentos.marcaoficialf.workers.dev dice si la clave está puesta; no
  lanza nada.
- **Clave:** el secreto `GITHUB_TOKEN` del Worker (Workers & Pages → reloj-red-neuronal-momentos → Settings →
  Variables and Secrets). Es una clave fine-grained de GitHub con acceso solo a Red-Neuronal-Momentos y el
  permiso **Actions: Read and write**. Cuando caduque, se crea otra igual en
  https://github.com/settings/personal-access-tokens/new y se sustituye el secreto. Mientras tanto, el Diario
  sigue saliendo con el horario de GitHub.
- **Registros:** Workers & Pages → reloj-red-neuronal-momentos → Logs. Cada día debe salir «Lanzado
  LuisP11127/Red-Neuronal-Momentos diario.yml»; si la clave no sirve, sale el error de GitHub.

Este archivo es una copia del código desplegado: si se cambia, hay que volver a subirlo al Worker.
