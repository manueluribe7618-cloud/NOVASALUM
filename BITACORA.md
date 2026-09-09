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

## 2026-09-09 — Controles visuales claros

- Motivo: sustituir los controles oscuros por superficies blancas que se
  distingan del fondo mediante bordes visibles.
- Archivos: `.streamlit/config.toml` y `src/ui/styles.py`.
- Cambio: tema claro; botones, selectores, campos y tarjetas de tabla con
  fondo blanco y bordes grises. Las acciones principales se resaltan con azul
  en el texto y el borde.
- Impacto contable: ninguno.
- Validación: demo local recargado y comprobado visualmente con la cartera
  manual de muestra.

## 2026-09-09 — Vista general y cartera por cliente

- Motivo: hacer que la vista general de facturas no quede limitada en altura y
  permitir revisar cuánto debe cada cliente.
- Archivo: `src/views/manual.py`.
- Cambio: la tabla general se extiende según sus filas; se agregó una tabla de
  clientes con saldo pendiente y un selector buscable con los clientes ya
  registrados. El selector filtra ambas tablas.
- Impacto contable: ninguno; son agrupaciones y filtros de lectura sobre los
  saldos existentes.
- Validación: pruebas de cartera 3/3 correctas, compilación completa y demo
  verificado con el cliente Transportes Andinos SAS: se muestran sus dos
  facturas y su saldo pendiente agregado.

## 2026-09-09 — Tipografía uniforme en controles

- Motivo: mantener el mismo tamaño de fuente en los elementos interactivos;
  solo los títulos cambian de escala.
- Archivo: `src/ui/styles.py`.
- Cambio: tamaño base fijo de 14 px y altura de línea uniforme para botones y
  el selector segmentado de empresas.
- Impacto contable: ninguno.
- Validación: demo local recargado y revisión visual del selector segmentado.

## 2026-09-09 — Filtros ordenados y subpestañas de cartera manual

- Motivo: eliminar un buscador global redundante que aportaba ruido visual y
  concentrar los controles de consulta debajo de las tarjetas de resumen.
- Archivos: `src/ui/layout.py`, `src/app_shell.py` y `src/views/manual.py`.
- Cambio: la cabecera conserva solo el contexto y la acción de registrar
  abono; el selector de empresa, la búsqueda de clientes y el filtro de
  facturas se muestran juntos debajo de los indicadores. La cartera ahora se
  organiza en las subpestañas **General** y **Clientes y saldo pendiente**.
  También se retiraron los contenedores vacíos que se mostraban antes de cada
  tabla y no cumplían ninguna función.
- Impacto contable: ninguno; se reordena la presentación de los mismos datos
  manuales y no se modifican cálculos, facturas ni abonos.
- Validación: pruebas de cartera 3/3 correctas, compilación completa, revisión
  de formato de Git y demo local recargado. Se confirmó que ya no hay selector
  global ni contenedores vacíos y que las dos subpestañas están disponibles.

## 2026-09-09 — Filtros compactos y cuadrículas de cartera manual

- Motivo: ofrecer filtros comparables a los de Excel sin llenar la pantalla de
  segmentadores, mejorar la jerarquía de las tablas y retirar el NIT del flujo
  manual de registro.
- Archivos: `src/views/manual.py`, `src/ui/layout.py`,
  `src/ui/components.py`, `src/database.py`, `tests/test_database.py` y
  `requirements.txt`.
- Cambio: búsqueda general visible y un único panel desplegable **Filtros**;
  dentro se agrupan empresa, cliente, estado, fecha y saldo. Las tablas de
  cartera usan `streamlit-aggrid`, con encabezados azules, ordenamiento y
  filtros por columna. El NIT ya no se solicita, muestra ni se usa para crear
  clientes manuales nuevos; se conserva la columna interna solo para no
  alterar registros históricos ni datos de Siigo.
- Impacto contable: ninguno. Los filtros son de lectura; totales, impuestos,
  saldos, abonos y reglas FIFO no cambian.
- Validación: pruebas de cartera 3/3 correctas, compilación completa y demo
  local revisado con la tabla de biblioteca, el buscador y el botón Filtros.

## 2026-09-09 — Acciones de cartera en la cabecera

- Motivo: concentrar las acciones frecuentes en la misma ubicación y estética
  de **Registrar abono**, sin añadir controles debajo de la tabla.
- Archivos: `src/ui/layout.py`, `src/app_shell.py` y `src/views/manual.py`.
- Cambio: **Registrar factura**, **Editar factura** y **Registrar abono** se
  muestran en el bloque superior derecho de la cartera manual. Factura y
  edición se abren en ventanas de trabajo, por lo que la tabla conserva una
  apariencia limpia.
- Impacto contable: ninguno; se reutilizan los mismos formularios y las mismas
  validaciones de facturas, impuestos, abonos y auditoría.
- Validación: pruebas de cartera 4/4 correctas, compilación completa y demo
  local revisado. Se comprobó que los formularios de registro y edición abren
  correctamente desde sus botones de la cabecera.

## 2026-09-09 — Alineación del acceso a filtros

- Motivo: alinear el botón **Filtros** con el campo de búsqueda de cartera.
- Archivo: `src/views/manual.py`.
- Cambio: el botón se alinea con la base del control de búsqueda, en lugar de
  hacerlo con su rótulo.
- Impacto contable: ninguno.
- Validación: demo local recargado y revisión visual confirmada.

## 2026-09-09 — Impuestos opcionales y análisis por período

- Motivo: permitir que cada factura aplique IVA, retención e ICA solo cuando
  corresponda, y facilitar el análisis de facturación por año o mes.
- Archivos: `src/taxes.py`, `src/views/manual.py`, `src/database.py` y
  `tests/test_taxes.py`.
- Cambio: se creó un motor tributario separado. Cada concepto permite **No
  aplica**, **Porcentaje sobre subtotal** o **Valor fijo (COP)**; las tasas
  predeterminadas se centralizan en `src/taxes.py` para configurarlas después.
  La regla utilizada queda incluida en la auditoría de la factura. El panel
  compacto de filtros ahora contiene año y mes de facturación; esos filtros
  actualizan la tabla y los indicadores superiores.
- Impacto contable: los importes finales almacenados y la fórmula permanecen
  iguales: `subtotal + IVA − retefuente − ICA`; el saldo sigue siendo el total
  menos los abonos aplicados.
- Validación: 8 pruebas correctas, compilación completa y demo local revisado
  con el formulario de impuestos y los filtros de año y mes.
