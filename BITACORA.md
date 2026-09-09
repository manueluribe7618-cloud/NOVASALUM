# Bitácora de cambios

Este archivo registra cambios del proyecto. Es distinto del historial operativo
de facturas, abonos y demás movimientos contables.

Cada entrada debe indicar el motivo, los archivos implicados, el impacto en
datos o cálculos, las validaciones realizadas y, cuando corresponda, la
autorización de Finanzas o del dueño.

## 2026-09-09 — Separación inicial de la aplicación

- Motivo: convertir `app.py` en un punto de arranque mínimo y sacar la
  interfaz a un módulo propio.
- Alcance: estructura de aplicación (interfaz, estilos, navegación por
  pestañas); no se modifica ninguna regla contable de cartera manual.
- Archivos: `app.py` (queda en ~18 líneas: `set_page_config` + `main()`) y
  `src/ui.py` (nuevo, concentra cartera, registro/edición con 3 modos de
  impuestos, clientes y recaudo, abonos FIFO, Siigo y conciliación). También
  se ignoran los archivos temporales SQLite (`.db-wal` y `.db-shm`) para no
  exponer datos locales en Git.
- Impacto contable: ninguno. Se conservan el cálculo de totales, saldos,
  impuestos, vencimientos y aplicación de abonos existentes (motor en
  `src/database.py` sin cambios de fórmula).
- Validación: `python -m pytest tests/ -q` (4/4 pruebas de reglas de
  cartera), importación limpia de `src.ui` y `src.database`.

*Nota: hubo una rama paralela (`origin/main`, commit `71111e0`) que abordó
esta misma separación repartiendo la interfaz en `src/app_shell.py` +
`src/ui/{styles,components,layout}.py` + `src/views/{manual,siigo}.py`. Se
reconcilió el 2026-09-09 a favor de esta versión (`src/ui.py` único): la
lógica de cálculo era idéntica en ambas (byte a byte en `database.py`,
`cartera_siigo.py`, `siigo.py`), pero la de aquí tiene más validaciones,
flujos y funcionalidad. Los archivos de esa rama se eliminaron.*

## 2026-09-09 — Alcance de las dos carteras aclarado

- Decisión: NOVASALUM tendrá una cartera manual digitada por Finanzas y una
  cartera independiente de lectura desde Siigo. La comparación entre ambas se
  abordará después.
- Prioridad actual: cartera manual.
- Documentación actualizada: `ARRANQUE.md`.
- Impacto contable: ninguno; esta entrada documenta el alcance confirmado por
  el dueño del proyecto.

## 2026-09-09 — Reconciliación de ramas divergentes (local vs. GitHub)

- Motivo: existían dos reorganizaciones paralelas del mismo `app.py` — la
  local (`src/ui.py` único, con 3 modos de impuestos y reasignación de
  empresa/cliente) y la de GitHub (`src/app_shell.py` + `src/ui/*` +
  `src/views/*`, commit `71111e0` "Mejora de Cálculo y estructura").
- Revisión: se comparó cada archivo de ambas ramas contra el commit base
  (`4d4c46a`). Resultado — `src/database.py`, `src/cartera_siigo.py`,
  `src/siigo.py` y `src/formato.py` son **byte a byte idénticos** entre el
  commit original y `origin/main`: pese al nombre del commit remoto, ningún
  cálculo cambió ahí. Toda la evolución de cálculo (3 modos de impuestos,
  reasignación de empresa/cliente con guarda por abonos) es local.
- Decisión: se conserva la estructura local (`src/ui.py`). Se descartan
  `src/app_shell.py`, `src/ui/{__init__,components,layout,styles}.py` y
  `src/views/{manual,siigo}.py` por quedar superados en validaciones y
  funcionalidad. Detalle técnico: dejar ambos (`src/ui.py` y `src/ui/`)
  coexistiendo habría hecho que Python cargara el paquete `src/ui/` en vez
  del archivo `src/ui.py` — se verificó de forma empírica — así que no era
  solo redundancia, sino un riesgo real de que la interfaz mostrada fuera la
  vieja sin ningún error visible.
- Se adapta contenido de la rama remota que sí vale la pena: la disciplina de
  `BITACORA.md` (este archivo) y la sección "Alcance vigente" /
  "Próximos pasos" de `ARRANQUE.md`.
- Pendiente de decisión del dueño (no se tocó nada de esto): (1) la cartera
  manual local ya no captura NIT del cliente al crear/editar facturas — la
  versión de GitHub sí lo hacía; (2) confirmar que las tarifas de la
  plantilla "Transporte estándar" (Retefuente 2,5%, ICA 0,4%) son correctas
  para las tres empresas antes de usarla en facturas reales — esa tarifa ya
  venía del `app.py` original, no es nueva de hoy, pero nunca se confirmó con
  contabilidad.
- Impacto contable: ninguno directo — es reorganización de archivos, no de
  fórmulas. Las dos preguntas pendientes arriba sí podrían tener impacto y
  quedan explícitamente sin resolver hasta que el dueño responda.
- Validación: `python -m pytest tests/ -q` (4/4), `python -c "import src.ui,
  src.database"` limpio, y prueba aislada confirmando que `src/ui.py` (no
  `src/ui/`) es el módulo que Python realmente carga.
