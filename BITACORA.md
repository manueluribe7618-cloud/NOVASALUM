# Bitácora de cambios

Este archivo registra cambios del proyecto. Es distinto del historial operativo
de facturas, abonos y demás movimientos contables.

Cada entrada debe indicar el motivo, los archivos implicados, el impacto en
datos o cálculos, las validaciones realizadas y, cuando corresponda, la
autorización de Finanzas o del dueño.

## 2026-09-16 — Clic sobre un cliente abre su detalle; anchos fijos

- Solicitud del dueño: al investigar un cliente, poder dar clic sobre su fila
  en «Clientes y saldo pendiente» y ver sus facturas, sin retirar el buscador
  del detalle — los dos caminos siguen disponibles. Además, que ese cuadro
  tenga anchos fijos, para visualizarlo siempre bien.
- Clic: un clic sencillo (o Enter) sobre cualquier celda de la fila selecciona
  al cliente en el buscador del detalle, que se abre debajo con su estado de
  cuenta por empresa. Cada gesto lleva su propio identificador y se consume
  una sola vez, igual que el doble clic de edición: sin eso, el clic viejo
  pisaría al buscador en cada rerun y sería imposible cambiar de cliente.
- Anchos: Saldo pendiente (190 px), Facturas con saldo (215 px) y Empresas
  (230 px) quedan cerrados y sin arrastre; la razón social se queda con todo
  el espacio restante para leerse completa. La grilla compartida acepta ahora
  un ajuste puntual de columnas sin conocer ninguna regla de negocio.
- De paso: la prueba «sin detalle» de la vista Siigo seguía afirmando la
  columna Estado, retirada el 2026-09-15 al entrar «Días en cartera»; se
  actualizó y se cubrió la columna nueva (conteo desde la emisión, cero para
  fechas futuras y raya para fecha ausente), que no tenía ninguna prueba.
- Archivos: `src/ui/grid.py`, `src/views/manual.py`,
  `tests/test_detalle_por_clic.py` (nuevo) y `tests/test_siigo_vista.py`.
- Impacto contable: ninguno. Es navegación y presentación; no cambia ningún
  importe, fórmula, abono ni el registro de movimientos.
- Validación: 211 pruebas en verde y pyflakes limpio. Verificado además en el
  navegador con datos de demostración en una base temporal: el clic abre el
  estado de cuenta del cliente, el buscador sigue eligiendo por su cuenta sin
  que el clic anterior lo devuelva, los tres anchos quedan aplicados (medidos
  en la grilla: 190/215/230) y el encabezado «Facturas con saldo» se lee
  completo. No se tocó la cartera real.

## 2026-09-15 — Dueño confirma las dos reglas de conciliación

- Decisión del dueño: aprueba los dos veredictos de comparación que la
  revisión completa del mismo día dejó pendientes de su confirmación.
  1. Cuando Siigo no entregó alguno de los conceptos comparados (saldo, IVA,
     retefuente, ICA o descuento), la factura sale **«Falta dato de Siigo»**
     y no «Cuadrado»: no se puede afirmar que cuadre ni que descuadre algo que
     no se comparó.
  2. El **descuento se compara** entre la cartera manual y la de Siigo; si no
     coincide, la factura sale **«Diferencia impuestos»**.
- Motivo: un «Cuadrado» que no comparó nada no sirve para supervisar la
  cartera, y el descuento existe en las dos carteras desde el 2026-09-14.
- Dónde vive: `src/views/conciliacion.py` (`CONCEPTOS_COMPARADOS` y
  `_build_reconciliation`) y `src/ui/components.py` (`ESTADO_META`,
  `DATO_INCOMPLETO` → «Falta dato de Siigo»). Cubierto por
  `tests/test_conciliacion.py`.
- Archivos de esta entrada: `BITACORA.md` y `ARRANQUE.md` (solo registro de
  la autorización; no hay cambios de código).
- Impacto contable: ninguno. Son veredictos de comparación; ningún importe,
  fórmula ni abono cambia.
- Validación: suite completa en verde, sin cambios de código.

## 2026-09-15 — Abono visible junto a los importes de la factura

- Problema reportado: el cuadro de abono inicial estaba después de las tres
  columnas de impuestos y de «Total a cobrar», fuera de la parte visible al
  comenzar la digitación en el diálogo largo.
- Cambio: «Subtotal», «Descuento» y «Abono ya recibido (COP) · opcional»
  aparecen en una misma fila. Al escribir un abono aparecen su fecha y
  referencia debajo; la vista previa del saldo permanece después del total.
  El botón independiente «Registrar abono» y el guardado conjunto no cambian.
- Archivos: `src/views/manual.py`, `tests/test_invoice_form.py`.
- Impacto contable: ninguno. No cambian importes, fórmulas, abonos aplicados,
  auditoría ni reglas de validación; es un ajuste de ubicación y rótulo.
- Validación: prueba del formulario para el rótulo y la secuencia de los tres
  campos, más la suite completa con Python 3.12 y Streamlit 1.60 sobre bases
  temporales. No se escribió en Supabase.

## 2026-09-15 — Corrección de defectos encontrados en la revisión completa

- Motivo: revisión de todo el proyecto solicitada por el dueño. Se corrigen los
  defectos hallados. Ningún cambio toca la fórmula del total, la base de los
  impuestos, el redondeo ni el motor FIFO.

- **Entorno de desarrollo inservible.** El Python del sistema en macOS (3.9
  contra LibreSSL) no trae `hashlib.scrypt`, del que depende el control de
  acceso: `src/autenticacion.py` reventaba al importarse y tres archivos de
  prueba ni cargaban. Además había Streamlit 1.50 instalado y el proyecto
  requiere 1.58 o superior. Se fija Python 3.12 en `.python-version`, se apunta
  `.claude/launch.json` al intérprete del entorno virtual y se documenta el
  arranque en `ARRANQUE.md`.

- **Pérdida silenciosa de facturas en producción.** Si `SUPABASE_DB_URL` falta
  o está mal escrita en los Secrets de Streamlit Cloud, la aplicación no
  fallaba: guardaba en un archivo SQLite dentro del contenedor, que se borra en
  cada reinicio. Ahora `app_shell.disco_efimero()` reconoce ese servidor (por el
  montaje `/mount/src`, o por `NOVASALUM_EXIGE_NUBE=1` en cualquier otro
  hospedaje) y la aplicación se detiene con el motivo y la solución, antes de
  que se pueda digitar nada. Verificado en la aplicación real.

- **TLS degradado sin avisar.** Si faltaba `certs/supabase-root-2021-ca.pem`,
  `_url_con_tls` caía a `sslmode=require`, que cifra pero no comprueba la
  identidad del servidor. Ahora levanta un error. Por ese canal viaja la
  cartera completa.

- **La conciliación declaraba «CUADRADO» sin haber comparado nada.** Un dato que
  Siigo no entregó se convertía en cero, así que una factura manual en cero
  contra un dato ausente salía cuadrada. Se añade el estado **«Falta dato de
  Siigo»**: esas facturas no están cuadradas ni descuadradas, y se dice
  cuántas son. Es la misma regla de honestidad que ya usaba la cartera Siigo.

- **La conciliación no comparaba el descuento**, pese a existir en las dos
  carteras desde el 2026-09-14. Ahora se compara y se muestra en la tabla y en
  las dos fichas. Cambia el veredicto de la comparación: una factura cuyo
  descuento difiera pasa a «Diferencia impuestos». No cambia ningún importe.

- **Retenciones mal clasificadas por su nombre.** La condición aceptaba «ICA»
  como subcadena, de modo que una retefuente llamada «servicios LOGISTICA» —en
  una empresa de logística— se contabilizaba como ICA. Ahora se compara contra
  palabras completas. Afecta solo al desglose informativo de la cartera Siigo.

- **Los indicadores de la cartera Siigo ignoraban los filtros:** sumaban todas
  las facturas encima de una tabla que mostraba solo las filtradas, dos cifras
  distintas en la misma pantalla. Como estas vistas se envían como imagen, la
  contradicción viajaba con ellas. Las tarjetas siguen arriba, pero ahora
  cuentan lo visible.

- **Dos diálogos seguían rompiéndose.** El arreglo del 2026-09-15 cubrió el de
  registrar factura pero no los otros dos: «Editar factura» se cerraba al tocar
  el primer campo (dependía del doble clic, que se consume una sola vez) y
  «Registrar abono» se quedaba pegado al cerrarlo sin guardar. La factura en
  edición pasa a vivir en la sesión y los tres diálogos declaran su cierre.
  Cerrar sesión ahora también apaga esas banderas.

- **El ingreso pagaba un scrypt completo en cada clic.** `usuario_actual()`
  corre en cada rerun y solo necesita el usuario y la revisión, pero recalculaba
  el hash: ~30 ms y 16 MB por interacción. Se memoriza la credencial vigente por
  su revisión (la llave es un HMAC con clave aleatoria del proceso, no la
  contraseña). Medido: 17,1 ms → 0,014 ms. Cambiar la contraseña en los Secrets
  sigue invalidando la anterior de inmediato.

- **Pruebas que iban a fallar solas.** Tres archivos fijaban fechas de 2026 con
  vencimientos a 30 días; al pasar el calendario el estado derivado cambiaba a
  VENCIDA y las aserciones caían sin que nadie tocara el código. Las fechas
  quedan relativas al día real.

- Archivos: `src/app_shell.py`, `src/database.py`, `src/autenticacion.py`,
  `src/cartera_siigo.py`, `src/views/conciliacion.py`, `src/views/siigo.py`,
  `src/views/manual.py`, `src/ui/components.py`, `src/ui/ingreso.py`,
  `.claude/launch.json`, `.python-version`, `.gitignore`, `ARRANQUE.md` y los
  archivos de prueba.

- Impacto contable: ninguno sobre importes ya guardados. La fórmula, la base de
  los impuestos, el redondeo y FIFO quedan idénticos. Los dos cambios que sí
  alteran un veredicto son de comparación, no de dinero: el descuento entra en
  la conciliación, y una factura sin dato de Siigo deja de contarse como
  cuadrada. **Ambos confirmados por el dueño el 2026-09-15.**

- Validación: **200 pruebas en verde** (146 antes; 54 nuevas) con Python 3.12 y
  Streamlit 1.60, y pyflakes limpio en todo el proyecto. Cinco archivos nuevos
  cubren lo que no tenía ninguna prueba: la conciliación completa —que tenía 292
  líneas y cero cobertura—, la clasificación fiscal de la cartera Siigo, los
  diálogos, el estado VENCIDA con sus días de mora, las guardas que impiden
  cruzar dinero entre clientes y empresas, y las dos guardas de almacenamiento.
  La aplicación se arrancó y se comprobó que la guarda de disco efímero se
  muestra. No se escribió en la cartera real de Supabase.

## 2026-09-15 — Abono inicial al registrar una factura manual

- Solicitud del dueño: al transcribir la cartera, poder registrar en el mismo
  paso el abono que ya tiene la factura, sin retirar el botón independiente
  «Registrar abono».
- Interfaz: el diálogo «Registrar factura» incluye un cuadro opcional de abono
  inicial en pesos colombianos. Al indicar un importe muestra fecha real del
  pago, referencia opcional, saldo resultante y la acción «Guardar factura y
  abono». Sin abono mantiene «Guardar factura». El importe no puede superar el
  total de esa factura; para pagos repartidos o con excedente se conserva el
  flujo independiente. Al cerrar o guardar se limpian también los campos del
  abono para que la siguiente factura no herede un pago.
- Persistencia: una sola transacción crea factura, abono, aplicación directa a
  esa factura y ambos registros de auditoría. Si falla cualquier paso, no
  queda ninguno de los movimientos guardado. Las funciones previas de crear
  facturas y registrar abonos continúan disponibles sin cambio de contrato.
- Archivos: `src/views/manual.py`, `src/database.py`,
  `tests/test_invoice_form.py` y `tests/test_initial_payment.py`.
- Impacto contable: no se modifica la fórmula del total, la base de impuestos,
  el redondeo ni FIFO. El nuevo pago aplicado reduce el saldo de la factura
  por su importe; un abono inicial por el total la deja pagada.
- Validación: 146 pruebas correctas con Python 3.12 y Streamlit 1.60; las de
  interfaz y datos usan bases SQLite temporales e incluyen abono parcial y
  total, descuento,
  fecha histórica, límite por total y reversión completa ante errores o un
  fallo simulado antes de confirmar la transacción. No se escribió en la
  cartera real de Supabase.

## 2026-09-15 — Vista previa de abono sin movimiento ficticio

- Problema: con el importe de abono en cero, la vista previa FIFO mostraba una
  aplicación ficticia de $ 1. Aunque la operación no se guardaba, el resultado
  inducía a error antes de escribir el monto real.
- Cambio: la vista previa permanece vacía hasta que se digite un monto mayor a
  cero. La distribución FIFO, las validaciones y el cálculo de saldos no se
  modifican.
- Archivo: `src/views/manual.py`.
- Impacto contable: ninguno. No se alteran facturas, abonos existentes ni
  fórmulas.
- Validación: batería completa de pruebas: 132 correctas.


## 2026-09-15 — Diálogos persistentes para registrar facturas y abonos

- Problema: al editar un campo dentro de los diálogos de registro, Streamlit
  volvía a ejecutar la página y cerraba el diálogo; no era posible completar
  una factura o un abono con varios datos.
- Cambio: se conserva en la sesión el estado de apertura de cada diálogo. Se
  cierra solo después de guardar correctamente el movimiento; la selección
  desde el detalle de cliente usa el mismo mecanismo. Al guardar o descartar
  una factura se limpian sus controles, para que la siguiente no herede un
  cliente, importe, fecha o impuesto del borrador anterior.
- Archivos: `src/app_shell.py` y `src/views/manual.py`.
- Impacto contable: ninguno. No cambia los valores, las fórmulas ni la
  aplicación FIFO; solo permite completar el formulario antes de guardarlo.
- Validación: prueba manual del flujo de apertura y edición de campos en la
  publicación conectada a Supabase.

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

## 2026-09-09 — Porcentajes reactivos y autocompletado de razón social

- Solicitud: digitar el porcentaje del subtotal para IVA, ICA y retefuente, y
  recibir sugerencias de clientes mientras se escribe la razón social.
- Cambio: el registro usa controles reactivos dentro de su ventana. Las tres
  casillas de porcentaje aparecen desde el inicio, con tasa cero y hasta cuatro
  decimales; al confirmar una casilla se recalculan los importes y el total antes
  de guardar. Se mantienen las opciones de importe fijo y no aplica.
- Cliente: selector buscable con coincidencias mientras se escribe y entrada de
  nuevas razones sociales mediante Enter. Las sugerencias incluyen clientes de
  las tres empresas y clientes que ya pagaron; cada razón social aparece una vez.
- Edición: reutiliza los mismos controles; conserva los importes originales
  hasta que el usuario elija una tasa o un valor diferente. La regla aplicada
  se guarda en la auditoría, tanto al crear como al editar.
- Impacto contable: se conserva el redondeo a peso entero y la fórmula
  subtotal + IVA − retefuente − ICA. No se asignan tasas tributarias por defecto.
- Validación: 14 pruebas automáticas correctas sobre bases temporales, incluyendo
  actualización del subtotal, porcentajes decimales, importes guardados,
  edición, sugerencias sin duplicados y reglas de abonos/FIFO.
- Dependencia: Streamlit 1.58 o superior para el selector con búsqueda flexible
  y aceptación de nuevas opciones.
- Comprobación en localhost: al escribir «Trans» aparece «Transportes Andinos
  SAS»; también se puede confirmar una razón social nueva y conservarla al
  recalcular. Con subtotal 1.000.000, IVA 19 %, retefuente 2,5 % e ICA 0,414 %,
  la ventana muestra 190.000, 25.000 y 4.140, y total 1.160.860. La prueba del
  navegador se cerró sin guardar facturas en la cartera del usuario.

## 2026-09-09 — Opciones de captura claras y movimiento suave

- Solicitud: hacer explícita la opción de porcentaje, reducir las tasas a dos
  decimales y agregar animaciones discretas a la interfaz.
- Cambio: IVA, retefuente e ICA muestran permanentemente las opciones
  «Porcentaje (%)», «Valor en pesos ($)» y «No aplica». El texto bajo la casilla
  relaciona el porcentaje del subtotal con su resultado en COP.
- Precisión: las tasas digitadas se redondean a dos decimales antes de calcular,
  para que el importe corresponda exactamente con la tasa visible. Por ejemplo,
  0,414 % se muestra y calcula como 0,41 %. Los importes de facturas existentes
  se conservan al abrirlas para edición.
- Animaciones: aparición breve de ventanas y paneles, respuesta al pulsar
  botones y transición de foco y tarjetas. Se respeta la preferencia de reducir
  movimiento del dispositivo.
- Validación: 14 pruebas correctas, incluidas persistencia con la precisión
  nueva y conservación de importes al editar. Localhost revisado visualmente
  con los tres modos y campos de dos decimales en la ventana de registro.

## 2026-09-09 — Subtotal con puntos de miles

- Solicitud: permitir el separador de miles con punto al digitar el subtotal.
- Cambio: el subtotal de registro y edición acepta 1.500.000, 1500000 y
  $ 1.500.000. Al confirmar el campo con Enter o al salir, se muestran los
  puntos automáticamente. El dato se convierte a pesos enteros antes de los
  cálculos y la persistencia.
- Validación: una agrupación incorrecta como 1.5 no se interpreta como 15;
  se muestra un mensaje y se impide guardar hasta corregirla.
- Pruebas: 17 pruebas correctas, incluyendo normalización, registro, edición,
  cálculo de impuestos y rechazo de formatos ambiguos. En localhost se verificó
  que 1500000 se convierte en 1.500.000 y que 2.500.000 con IVA 19 % produce
  475.000 de IVA y 2.975.000 de total, sin guardar datos de prueba en la cartera.

## 2026-09-09 — Estado compacto y edición desde la fila

- Solicitud: mantener las filas neutras, concentrar el color en la columna
  Estado y abrir la edición con doble clic sobre la factura.
- Presentación: Estado permanece fijo a la derecha, con etiqueta y palabra:
  Pagada en amarillo, Abonada en naranja, Vencida en rojo suave y Pendiente o
  Anulada en gris. Los importes se alinean a la derecha.
- Interacción: doble clic sobre cualquier celda de una factura, o Enter con
  una celda enfocada, abre directamente su ventana de edición. Se retira el
  botón Editar factura de la cabecera y no se pide buscar la factura de nuevo.
- Identificación: se usa el ID de la factura, independiente de la posición
  tras ordenar o filtrar y de los números que coincidan entre empresas. Cada
  gesto se consume una sola vez; al reabrir se recuperan los valores guardados
  en lugar de un borrador cerrado sin guardar.
- Impacto contable: ninguno sobre fórmulas ni estados; se reutilizan el
  formulario, las validaciones y la auditoría existentes.
- Validación: 19 pruebas correctas en bases temporales. Se verificaron el
  guardado exclusivo de la factura indicada y la prevención de reaperturas
  automáticas. En localhost se comprobaron etiquetas sobre filas neutras,
  doble clic, reapertura tras ordenar y edición con Enter, sin guardar ni
  anular registros de la cartera del usuario. Servidor local saludable.
- Trabajo realizado en la rama main existente, sin crear ramas ni worktrees.

## 2026-09-10 — Vista de cliente con desglose por empresa

- Solicitud: al buscar un cliente específico, ver el total de sus facturas en
  todas las empresas y, dentro de ese apartado, la separación por empresa,
  porque cada abono se registra en una sola empresa y aplica solo a sus
  facturas.
- Cambio 1: el filtro de clientes ahora busca por razón social. Antes cada
  cliente aparecía repetido por empresa («Cliente · FEBA», «Cliente · LUA»);
  ahora una sola selección trae su cartera completa en las tres empresas.
  Las selecciones guardadas con el formato anterior se descartan sin error.
- Cambio 2: en la pestaña «Clientes y saldo pendiente» se agregó «Detalle del
  cliente»: un buscador de razón social, el total combinado (facturado,
  abonado y saldo de todas las empresas) y un bloque por empresa con sus
  facturas y su saldo propio.
- Cambio 3: cada bloque de empresa con saldo tiene el botón «＋ Abono aquí»,
  que abre el diálogo de abono con la empresa y el cliente ya preseleccionados,
  para que el pago quede registrado en la empresa correcta sin pasos de más.
- Archivos: `src/views/manual.py` (filtro por razón social, detalle por
  empresa, preselección del diálogo de abono) y `tests/test_customer_view.py`
  (nuevo).
- Impacto contable: ninguno. Solo agrupación y visualización; el registro de
  abonos sigue pasando por `registrar_abono` sin cambios de fórmula ni de
  validaciones.
- Validación: 24 pruebas automáticas correctas (5 nuevas de esta vista), más
  una prueba end-to-end con base temporal: cliente sembrado en dos empresas
  mostró $ 25.513.000 combinados, bloques FEBA y LUA separados, y el botón
  del bloque LUA abrió el diálogo con LUAC y el cliente preseleccionados.
  En localhost, con datos reales, se revisó el detalle de Transportes Andinos
  SAS y la preselección del abono; se cerró el diálogo sin aplicar pagos.

## 2026-09-10 — Estado de cuenta por cliente igual al Excel

- Solicitud: replicar dentro de la aplicación la forma del Excel de cartera
  por cliente (una sección por empresa, columnas de la hoja, saldo de cada
  empresa al pie y el SALDO EN CARTERA total resaltado), y cargar datos de
  ejemplo para poder verlo.
- Cambio: el «Detalle del cliente» ahora es un estado de cuenta: título
  «Cliente · Empresa» por sección, columnas Factura, Fecha, Detalle del
  servicio (texto completo), Placas, Sub valor factura, Impuestos, Retención,
  ICA, Abono y Saldo pendiente; los conceptos en cero quedan en blanco como
  las celdas vacías del Excel. Cada sección cierra con su saldo en rojo a la
  derecha y el conjunto termina con la banda amarilla «SALDO EN CARTERA»,
  acompañada de facturado y abonado totales. Se conserva el botón
  «＋ Abono aquí» por empresa con el diálogo preseleccionado.
- Datos: se registraron las facturas reales de TMP Izajes y Transportes S.A.S
  de la hoja (FEBA2050; MSU647 con su abono de $ 4.500.000; MSU648; LUA1728;
  LUA1739) usando crear_factura y registrar_abono, con vencimiento a 30 días.
  FEBA2057 no se cargó: en la hoja está sin valores y la aplicación exige
  total mayor que cero por diseño.
- Archivos: `src/views/manual.py` (_statement_table y detalle),
  `src/ui/styles.py` (cierres del estado de cuenta) y
  `tests/test_customer_view.py`.
- Impacto contable: ninguno. Presentación y carga de datos por las funciones
  oficiales; las cifras cargadas cuadran peso a peso con la hoja:
  810.000 + 2.050.000 + 2.754.000 = 5.614.000.
- Validación: 26 pruebas automáticas correctas y pyflakes sin advertencias en
  todo el proyecto. Prueba end-to-end con base temporal: registrar una
  factura, editar su subtotal y aplicar un abono se reflejan de inmediato en
  el estado de cuenta (810.000 → 910.000 → 510.000). Revisión visual en
  localhost con los datos reales de TMP Izajes; fue necesario reiniciar el
  servidor para tomar el código nuevo (la caché de módulos de Streamlit no
  recarga sola los submódulos editados).

## 2026-09-10 — Editar número de factura y fechas

- Solicitud: además de las placas y el detalle, poder corregir el número de la
  factura seleccionada y sus fechas, porque en la digitación a veces se
  equivocan y la fecha es importante.
- Cambio en base de datos: actualizar_campos_factura ahora también acepta
  numero, fecha y vencimiento. Cuando no llegan, conserva los guardados; el
  prefijo no se toca (viene de la empresa). Protecciones: número obligatorio,
  vencimiento no puede quedar antes de la emisión, y un número repetido en la
  misma empresa se rechaza con el mensaje «ya existe» sin alterar nada.
- Cambio en interfaz: la ventana «Editar factura» muestra Número de factura,
  Fecha de emisión y Vencimiento junto al detalle, las placas, el subtotal y
  los impuestos. Los campos comienzan con los valores guardados.
- Archivos: `src/database.py`, `src/views/manual.py`,
  `tests/test_database.py`.
- Impacto contable: ninguno en fórmulas. Corregir el vencimiento puede cambiar
  el estado derivado (VENCIDA/PENDIENTE), que es exactamente la regla vigente
  aplicada al dato corregido. La auditoría guarda antes y después completos.
- Validación: 30 pruebas automáticas correctas (4 nuevas: corrección de
  número y fechas, conservación cuando no se envían, duplicado rechazado,
  vencimiento invertido rechazado) y pyflakes limpio. Prueba end-to-end del
  formulario con base temporal: FEBA2075→FEBA2057 con fechas corregidas
  quedó guardado, y el intento de duplicado mostró el error sin dañar datos.
  Revisión visual en localhost con doble clic sobre MSU647; se cerró sin
  guardar.

## 2026-09-11 — Cartera Siigo independiente, leída factura por factura

- Solicitud: que la cartera Siigo sea completamente independiente de la
  manual, que se vea igual (mismo cuadro general y mismo estado de cuenta por
  cliente y por empresa), que nadie digite nada, y que la información se
  obtenga consultando cada factura individualmente en el API, con supervisión.
- Por qué la consulta individual no era opcional: se comprobó que el listado
  masivo de Siigo no entrega ítems ni retenciones. Con solo el listado, la
  misma factura sale con estado DATO_INCOMPLETO, sin saldo, sin vencimiento y
  con 0 días de mora, cuando en realidad llevaba 153 días vencida. Subtotal,
  IVA, retefuente, ICA y el detalle del servicio quedan vacíos. El detalle por
  factura (`GET /v1/invoices/{id}`, que no se usaba en ninguna parte del
  proyecto) es la única fuente de esos datos.
- Velocidad: el cliente de Siigo es seguro para hilos y pide el token una sola
  vez. Medido contra un transporte simulado con 120 ms de latencia, 60
  facturas tardan 7,34 s una por una y 1,08 s con seis consultas simultáneas.
  La lectura usa seis por empresa.
- Módulos nuevos: `src/siigo_lectura.py` (motor de lectura y reporte de
  supervisión), `src/siigo_vista.py` (funciones puras de presentación),
  `src/siigo_muestra.py` (muestra autónoma en formato Siigo),
  `src/ui/grid.py` (grilla compartida por las dos carteras) y
  `src/views/conciliacion.py` (la conciliación, mudada a su propio archivo).
  `src/views/siigo.py` se reescribió completo.
- Decisiones del dueño aplicadas: la columna «Abonos» queda vacía —Siigo no
  informa el abono de cada factura y derivarlo de total − saldo sería inventar
  una cifra—; no hay columna «Placas», porque Siigo no la guarda en un campo
  propio y la placa viene dentro del texto de la descripción, que sí se
  muestra; y se consultan todas las facturas del período.
- Supervisión: marca de hora y origen de cada lectura, errores por empresa y
  por factura, conteo de facturas sin detalle, y una tabla con facturas del
  período, detalles leídos, fallidos, consultas al API y segundos por empresa.
- Regla de honestidad: un dato que Siigo no entregó se muestra con raya, nunca
  como «$ 0». Un cero afirma que no hay IVA; una raya dice que no se sabe.
  Los totales cuentan aparte las facturas sin dato en vez de sumarlas como
  cero. Las anuladas y las monedas distintas de COP no entran en los totales.
- Tres fallas reales corregidas de paso: (1) la pantalla Siigo se caía al
  abrirla sin `secrets.toml` —el caso de hoy— porque `st.secrets` no falla al
  tocarlo sino al recorrerlo, fuera del try; (2) la «muestra visual» se
  fabricaba copiando facturas y clientes REALES de la cartera manual y los
  rotulaba como lectura de Siigo, lo que además hacía que la conciliación
  saliera siempre cuadrada; (3) la empresa que mostraba la cartera Siigo la
  decidía el filtro de la cartera manual, y el botón «＋ Registrar abono»
  aparecía sobre la cartera Siigo pudiendo escribir en la cartera manual.
- Impacto contable: ninguno en la cartera manual; sus cálculos, su grilla y su
  comportamiento quedan idénticos. La cartera Siigo no escribe nada: el cliente
  del API solo permite GET, salvo la autenticación.
- Validación: 66 pruebas automáticas (36 nuevas) y pyflakes limpio en todo el
  proyecto. Ninguna prueba abre un socket: el API se simula con el transporte
  inyectable de `src/siigo.py`. Se blindó el «se ve igual» con una prueba que
  compara las columnas de la cartera Siigo contra las de la manual, y la
  independencia con pruebas de comportamiento: la vista se pinta igual con
  toda lectura de la base manual rota, y no deja ninguna clave de sesión del
  manual. Revisión visual en localhost con la muestra: cuadro general, estado
  de cuenta por empresa con su total en rojo, banda amarilla SALDO EN CARTERA
  y conciliación cruzando ambas carteras.
- Pendiente para la primera lectura real: con credenciales configuradas, el
  panel de supervisión mostrará cuántas facturas tiene un mes por empresa y
  cuánto tarda; con esa cifra se decide si hace falta un tope por consulta.

## 2026-09-11 — Almacenamiento listo para Supabase (sin migrar datos de prueba)

- Solicitud: dejar el programa listo para guardar la información en Supabase,
  siempre completa y en orden. Los datos actuales son de prueba y no se
  migran: en la nube se arranca limpio.
- Cambio: `src/database.py` ahora tiene dos motores con la misma API. Sin
  configuración funciona igual que siempre (SQLite local). Cuando existe la
  llave `SUPABASE_DB_URL` en los secretos, todas las tablas (facturas,
  clientes, abonos, aplicaciones FIFO, revisiones y auditoría) viven en
  Postgres de Supabase, con las mismas reglas: transacciones en cada
  escritura, UNIQUE de consecutivo por empresa, guardas de abonos y rastro
  de auditoría. Regla fija: una ruta explícita siempre es SQLite, así ninguna
  prueba ni base temporal puede irse a la nube por accidente.
- Seguridad de la conexión: TLS verificado con la CA de Supabase que ya está
  en `certs/` (la lección del proyecto anterior). Un `sslmode` que venga en
  la URL se respeta.
- Rendimiento: la conexión con la nube se comparte y se reutiliza (abrir un
  canal TLS por consulta sería inaceptablemente lento), el esquema se
  verifica una sola vez por proceso, y `prepare_threshold=None` para
  compatibilidad con el pooler de Supabase.
- Interfaz: la barra lateral dice siempre dónde están los datos («Datos:
  SQLite local · novasalum.db» o «Datos: Supabase (nube)»), y si la nube no
  responde al arrancar, la app muestra el motivo y se detiene con un aviso
  claro en vez de un error técnico.
- Impacto contable: ninguno. Mismas fórmulas, mismas validaciones, mismo
  redondeo; solo cambia dónde se guarda.
- Validación: 77 pruebas en verde (11 nuevas del almacenamiento dual:
  selección de motor, traducción del dialecto, RETURNING, TLS, y el flujo
  completo factura+abono en local). pyflakes limpio. Arranque verificado con
  el letrero de almacenamiento visible.
- Pendiente (dueño): crear el proyecto en supabase.com y pegar la URL del
  Transaction pooler en `.streamlit/secrets.toml` como `SUPABASE_DB_URL`.
  Con la llave puesta se hace la primera prueba en vivo (crear una factura de
  prueba, abonarla, releerla y borrarla) antes de digitar las reales.

## 2026-09-11 — Supabase conectado y verificado en vivo

- Se creó el proyecto en Supabase (región us-west-2) y se configuró
  `SUPABASE_DB_URL` en `.streamlit/secrets.toml` con la URI del Transaction
  pooler (puerto 6543). El archivo está protegido por `.gitignore`.
- Las siete tablas quedaron creadas en la nube y las tres empresas sembradas.
- Prueba en vivo contra Supabase real, superada: guardar una factura con
  impuestos, releerla completa (montos, fechas, días de mora, estado), rechazo
  del consecutivo repetido, abono aplicado con recálculo de saldo y estado,
  rechazo de un abono que supera el saldo, rastro de auditoría, y lectura del
  listado, el resumen y los clientes con saldo. Datos de prueba eliminados y
  contadores reiniciados: la primera factura real será la número 1.
- Dos defectos reales encontrados por esa prueba y corregidos:
  1. `GROUP BY` incompatible. SQLite acepta seleccionar columnas que no están
     agrupadas; Postgres no. Las consultas del listado de facturas y del
     listado de abonos agrupaban solo por la factura o el abono, y al leer
     desde Supabase fallaban con `GroupingError`. Ahora agrupan también por la
     llave primaria del cliente.
  2. Precedencia del motor. Streamlit exporta por su cuenta los valores de
     `secrets.toml` al entorno del proceso, así que al existir la llave de
     Supabase, las pruebas que apuntaban a una base temporal mediante
     `NOVASALUM_DB` terminaron **escribiendo en la base de producción**. Se
     corrigió: señalar un archivo local —por parámetro `ruta` o por
     `NOVASALUM_DB`— siempre tiene prioridad sobre la nube. Queda cubierto por
     una prueba propia.
- Impacto contable: ninguno. Las fórmulas, el motor FIFO y el redondeo no se
  tocaron; los dos arreglos son de dialecto de base de datos y de selección de
  destino.
- Validación: 78 pruebas en verde (una nueva por la precedencia), pyflakes
  limpio, y la aplicación completa verificada arrancando contra la nube con el
  letrero «Datos: Supabase (nube)» visible en la barra lateral.

## 2026-09-12 — Control de acceso con usuario y contraseña

- Solicitud del dueño: un ingreso con usuario y contraseña, con límite de
  intentos y un reporte que avise si alguien está probando repetidamente.
  Se le había recomendado usar la lista de correos de Streamlit Cloud en vez
  de construirlo; el dueño confirmó su decisión y se construyó.
- Cómo se protegen las contraseñas: no se guardan. Se guarda el resultado de
  `scrypt` (que viene en Python, sin dependencias nuevas), con sal aleatoria
  por contraseña y los parámetros escritos dentro de cada hash para poder
  endurecerlos después sin invalidar las existentes. Medido: ~30 ms y 16 MB
  por intento, lo que hace impráctico probar contraseñas en masa.
- Defensas concretas: comparación en tiempo constante (`hmac.compare_digest`);
  hash de relleno cuando el usuario no existe, para que la respuesta tarde lo
  mismo y no se pueda averiguar qué cuentas son reales; el mensaje de error
  nunca distingue entre usuario inexistente y contraseña mala; rechazo de
  contraseñas cortas, solo numéricas o de diccionario.
- Bloqueo: 5 intentos fallidos bloquean la cuenta 15 minutos. Estando
  bloqueada, ni la contraseña correcta entra. Un ingreso correcto reinicia el
  contador y el bloqueo expira solo.
- Reporte: pantalla «Seguridad» con ingresos correctos y fallidos de las
  últimas 24 horas, fallidos de la última hora, desglose por usuario, cuentas
  bloqueadas con botón para desbloquear (solo admin), el detalle de cada
  intento con su motivo, y las cuentas existentes. La alerta se enciende sola
  cuando hay una cuenta bloqueada o cuando se superan 10 fallos en una hora.
- La primera cuenta se crea desde la terminal con `python crear_usuario.py`,
  no desde la web: si la aplicación permitiera crearla por internet,
  cualquiera que llegara a la dirección antes que el dueño podría quedarse
  con ella. Después, un admin puede crear más cuentas desde la pantalla de
  Seguridad.
- Defecto grave encontrado y corregido durante la construcción: el error de
  autenticación se lanzaba **dentro** de la transacción, de modo que el
  `rollback` deshacía el conteo de intentos y el registro del intento. En la
  práctica el contador siempre decía «te quedan 4» y **el bloqueo nunca se
  habría activado**. Ahora el resultado se decide dentro de la transacción y
  el error se lanza después de confirmar. Queda cubierto por una prueba de
  regresión propia.
- Impacto contable: ninguno. No se tocó ninguna fórmula, ni el motor FIFO, ni
  el redondeo.
- Validación: 110 pruebas en verde (32 nuevas), pyflakes limpio. Las pruebas
  cubren cada forma concreta de entrar sin permiso: clave incorrecta, usuario
  inexistente, cuenta desactivada, cuenta bloqueada, hash corrupto, y que sin
  ingresar no se alcance a ver ni una cifra de la cartera. Verificado además
  sobre la aplicación real y contra Supabase.

## 2026-09-12 — Activación privada de la primera cuenta

- Problema reportado: la pantalla de ingreso mostraba un error y un comando de
  terminal, sin permitir continuar. Se confirmó mediante lectura que la base
  Supabase configurada tenía cero cuentas.
- Solución: `crear_usuario.py --web` prepara un enlace privado temporal y un
  servidor conectado a la misma base, escuchando exclusivamente en
  `127.0.0.1`. La pantalla «Crea tu acceso» permite que el dueño elija usuario,
  nombre y contraseña sin enviarla al chat ni usar una clave predeterminada.
- El servidor guarda solo el hash de la invitación en su entorno; vence en
  30 minutos. El enlace se retira de la dirección al abrirlo. Sin invitación
  válida no se ofrece registro público ni se muestran datos de cartera.
- La creación comprueba dentro de una transacción que aún no haya cuentas.
  SQLite serializa mediante BEGIN IMMEDIATE y Postgres bloquea la tabla durante
  la comprobación e inserción. Dos solicitudes simultáneas no crean dos
  administradores iniciales. Con cualquier cuenta existente se cierra esta vía.
- Después de crear la cuenta se limpian la invitación y los campos de clave y
  se vuelve al ingreso normal. Se conservan scrypt, el bloqueo por intentos y
  la vigilancia de accesos. No se modifican datos ni cálculos de las carteras.
- Validación: 117 pruebas correctas sobre bases temporales, incluidas siete
  nuevas de activación, concurrencia, expiración, contraseñas distintas y
  regreso al ingreso. Pyflakes y revisión de diferencias sin errores.
- Se dejó el servidor local activo y la pantalla privada abierta. La cuenta
  real queda pendiente de que el dueño escriba sus credenciales y pulse
  «Crear mi cuenta»; no se crearon cuentas de prueba en Supabase.
- Todo el trabajo permanece en main, sin ramas ni worktrees adicionales.

## 2026-09-12 — Usuario y contraseña administrados en Secrets

- Corrección del dueño: quiere conservar el usuario y la contraseña dentro de
  Streamlit para poder consultarlos o cambiarlos si sus jefes los olvidan.
- Se sustituye la activación anterior por una única sección `[acceso]` en los
  Secrets, con `usuario` y `contrasena`. La pantalla solo pide esos dos datos y
  ofrece Entrar. Se retiraron el servidor de activación, sus invitaciones y
  los formularios de crear cuentas o cambiar contraseñas desde la aplicación.
- Secrets es la autoridad del ingreso: cuentas o claves anteriores en la base
  no habilitan la web. El cambio de credenciales invalida la sesión en la
  siguiente ejecución completa. Sin configuración válida el acceso permanece
  cerrado; no existe una contraseña predeterminada.
- Se conservan el bloqueo de cinco intentos durante quince minutos y el
  reporte de accesos. La base guarda solo metadatos e intentos para la cuenta
  configurada; su contraseña y su hash no se copian allí. El verificador se
  calcula en memoria y no se muestra en la interfaz.
- Se documentó el bloque en `.streamlit/secrets.toml.ejemplo` y se preparó el
  bloque local vacío para que el dueño elija ambos valores. Las credenciales
  existentes de Siigo y Supabase se conservaron; el archivo real sigue excluido
  de Git. No se crearon cuentas reales ni se eligieron claves por el dueño.
- Validación: 118 pruebas correctas en bases temporales, pyflakes limpio y
  pantalla local verificada con solo Usuario, Contraseña y Entrar. Se prueban
  primer ingreso desde Secrets, rechazo de claves antiguas, bloqueo y cambio
  de configuración. Todo permanece en main.
- Publicación autorizada por el dueño: se prepara esta actualización en main
  para el despliegue conectado a GitHub. La contraseña real se configura en
  los Secrets de Streamlit Cloud; el archivo local no se publica. Se corrigió
  también el mensaje de la herramienta heredada para que no prometa acceso web.

## 2026-09-12 — Protección de las tablas de Supabase

- El panel de Supabase mostró nueve alertas críticas: las nueve tablas de
  NOVASALUM estaban en `public`, sin RLS, y los roles `anon` y `authenticated`
  tenían permiso de lectura. La contraseña de la interfaz no protege la Data
  API de Supabase, así que era una exposición independiente del ingreso web.
- Se añadió RLS a las nueve tablas y se retiran los permisos de tablas y
  secuencias a ambos roles de la API. NOVASALUM sigue usando su conexión
  privada directa a Postgres; se verificó que ese rol omite RLS.
- La protección se ejecuta en la misma transacción que la creación del esquema
  y queda repetible en cada arranque del servidor. No se cambian facturas,
  abonos ni fórmulas contables.
- Se ensayó la migración en una transacción revertida y después se aplicó al
  proyecto de Supabase: 9/9 tablas con RLS, 0 con lectura para los roles de la
  Data API, 0/8 secuencias con uso público y lectura privada de la aplicación
  correcta. Validación local: 119 pruebas correctas y pyflakes limpio.

## 2026-09-14 — Columna de descuento en el registro de facturas

- Solicitud del dueño: agregar al registro de facturas la columna de
  DESCUENTO que ya usa su hoja de Excel y la aplicación no tenía. Al pedirla
  él mismo queda autorizado el cambio de fórmula que se le había señalado.
- Fórmula nueva del total: subtotal + IVA − retefuente − ICA − **descuento**.
  El descuento es documental y NO cambia la base de los impuestos: las
  retenciones se siguen calculando sobre el subtotal bruto, exactamente como
  en la hoja de Finanzas (verificado contra el caso real TAV906: subtotal
  3.800.000, retefuente 38.000 = 1% del bruto, descuento 1.400).
- Dónde aparece: campo «Descuento (COP)» en el registro y en la edición (con
  el mismo capturador de puntos de miles del subtotal), columna «Descuento»
  en el cuadro general y en el estado de cuenta de las dos carteras —en la
  Siigo se llena con el descuento documental que ya entregaba el API
  (descuento_siigo) y que hasta hoy no se mostraba. La celda queda vacía
  cuando el descuento es cero, como en el Excel.
- Protecciones: el descuento no puede ser negativo, no puede superar el
  subtotal, el total sigue sin poder quedar en cero o negativo, y sigue sin
  poder quedar por debajo de los abonos ya aplicados. Editar sin enviar el
  campo conserva el descuento guardado.
- Migración: las bases existentes reciben la columna sola al arrancar
  (SQLite y Postgres), con 0 en todas las facturas anteriores: ningún total
  histórico cambia. Ejecutada y verificada en el Supabase de producción.
- Impacto contable: el autorizado. Las facturas ya guardadas no cambian
  (descuento 0); solo las nuevas o editadas con descuento usan la fórmula.
- Validación: 131 pruebas en verde (12 nuevas: fórmula, guardas, migración
  de base vieja, captura por formulario con el caso TAV906, edición, y las
  columnas espejo de las dos carteras). pyflakes limpio.
