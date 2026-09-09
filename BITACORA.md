# Bitácora de cambios

Este archivo registra cambios del proyecto. Es distinto del historial operativo
de facturas, abonos y demás movimientos contables.

Cada entrada debe indicar el motivo, los archivos implicados, el impacto en
datos o cálculos, las validaciones realizadas y, cuando corresponda, la
autorización de Finanzas o del dueño.

## 2026-09-09 — Separación inicial de la aplicación

- Motivo: convertir `app.py` en un punto de arranque mínimo y distribuir la
  interfaz en módulos con responsabilidades claras.
- Alcance: estructura de aplicación, estilos, componentes visuales, navegación
  y vistas; no se modifica ninguna regla contable de cartera manual.
- Archivos: `app.py`, `src/app_shell.py`, `src/ui/styles.py`,
  `src/ui/components.py`, `src/ui/layout.py`, `src/views/manual.py`,
  `src/views/siigo.py`, sus paquetes y la configuración de descubrimiento de
  pruebas. También se ignoran los archivos temporales SQLite (`.db-wal` y
  `.db-shm`) para no exponer datos locales en Git.
- Impacto contable: ninguno. Se conservan el cálculo de totales, saldos,
  impuestos, vencimientos y aplicación de abonos existentes.
- Validación: `python3 -m unittest discover -v` (3/3 pruebas de reglas de
  cartera), compilación de todos los módulos e importación de la aplicación
  correctas. Se verificó además la vista Streamlit con los datos de
  demostración.

## 2026-09-09 — Alcance de las dos carteras aclarado

- Decisión: NOVASALUM tendrá una cartera manual digitada por Finanzas y una
  cartera independiente de lectura desde Siigo. La comparación entre ambas se
  abordará después.
- Prioridad actual: cartera manual.
- Documentación actualizada: `ARRANQUE.md`.
- Impacto contable: ninguno; esta entrada documenta el alcance confirmado por
  el dueño del proyecto.
