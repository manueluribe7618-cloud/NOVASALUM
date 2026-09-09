# NOVASALUM — arranque del proyecto

> **Actualización de alcance — 9 de septiembre de 2026.** Este documento
> conserva el contexto de la separación original. La decisión de no revivir la
> cartera manual quedó reemplazada por la especificación funcional actual:
> NOVASALUM incluye cartera manual, abonos FIFO, espejo de Siigo y
> conciliación. El detalle vigente de uso y arranque está en
> [README.md](README.md).

## Estado actual de la primera versión

- app.py contiene la interfaz Streamlit: cartera manual, abonos FIFO, espejo
  de Siigo y conciliación lado a lado.
- src/database.py contiene la cartera manual local: facturas, abonos,
  aplicaciones, revisiones y auditoría. No escribe en Siigo.
- tests/test_database.py cubre la aplicación FIFO y las protecciones de
  saldos.
- README.md es la guía vigente para ejecutar la aplicación y configurar
  credenciales.

Documento de traspaso. Léelo completo antes de escribir código: te ahorra
releer los 2.802 archivos que ya están aquí.

---

## Alcance vigente — 9 de septiembre de 2026

Esta aclaración sustituye cualquier interpretación anterior que trate la
cartera manual de NOVASALUM como código descartado.

NOVASALUM tendrá dos carteras separadas:

- **Cartera manual:** la persona de Finanzas digita sus facturas, abonos y
  ajustes. Es el módulo prioritario en esta etapa.
- **Cartera Siigo:** consulta facturas, clientes y recibos directamente desde
  la API de Siigo. Se mantiene independiente de la cartera manual.

Más adelante se podrá comparar una cartera contra la otra, sin mezclar sus
fuentes de datos ni permitir que esa comparación modifique documentos de
Siigo. La frase histórica “No la revivas aquí” se refiere exclusivamente a la
cartera heredada de Excel del proyecto original, no a la cartera manual nueva
de NOVASALUM.

Todo cambio del proyecto debe registrarse en `BITACORA.md`. Esta bitácora
técnica es distinta del historial operativo de facturas y abonos.

---

## Qué es esto y por qué existe

La empresa (NOVASA Logistic SAS, LUAC Cargo SAS y MSU Máquinas y Serv —
transporte de carga en Colombia, unos 15 tractocamiones) tenía toda su
operación en una sola aplicación: `D:\Optimizar Novasa` (liquidación de viajes,
nómina, mantenimiento, cartera).

La dirección decidió sacar **la cartera** a un programa aparte, por dos razones:
les resulta más fácil de manejar, y contiene información sensible que prefieren
administrar separada del resto.

**NOVASALUM es ese programa.**

En la aplicación original había DOS carteras:

- Una **cartera manual** que se alimentaba de un Excel. Aquella versión fue
  descartada; no se copia su código ni sus datos. La cartera manual actual se
  construye de nuevo con persistencia, abonos FIFO y auditoría.
- La **cartera de Siigo**, que lee del API de Siigo (el software contable), se
  conserva como espejo contable de solo lectura.

Un punto que vale la pena tener claro, y que el dueño puede usar con sus jefes:
las facturas, clientes y recibos **de Siigo se leen en vivo del API de Siigo**.
La cartera manual es una fuente operativa independiente; ninguna acción de
NOVASALUM modifica documentos contables en Siigo.

---

## Qué ya está aquí

### `src/siigo.py` — 890 líneas. Cliente del API. **Ya funciona.**

No hay que programar la conexión: está construida. Solo usa la librería
estándar de Python (nada de `requests`).

- `ClienteSiigo` con `listar_facturas(date_start, date_end, ...)`,
  `listar_recibos_caja(...)` y `listar_clientes(...)`.
- `CredencialesSiigo` y `ConfiguracionSiigo`, con una credencial **por
  empresa**. Se cargan con `ConfiguracionSiigo.desde_entorno(...)` o
  `desde_mapeo_secretos(...)` — esta última acepta `st.secrets` o cualquier
  diccionario equivalente.
- Apunta a `https://api.siigo.com`, bloquea redirecciones y maneja reintentos.

### `src/cartera_siigo.py` — 890 líneas. Toda la lógica. **Ya funciona.**

Solo depende de Python y pandas. Es la capa que traduce lo que devuelve Siigo
en una cartera usable:

- `facturas_a_dataframe(...)` y `recibos_a_dataframe(...)` — convierten la
  respuesta del API en tabla.
- `estado_contable(factura)` — el estado contable de cada factura.
- La antigüedad por días de mora (el dueño cobra por antigüedad, no por plazo
  formal).
- Desglose de impuestos: IVA, retefuente, ICA.
- `enriquecer_facturas_clientes(...)`, `conciliar_cartera(...)`,
  `construir_operacion_local(...)`.
- `hash_fuente_siigo(...)` y `hash_revision_fila(...)` para detectar cambios.

**Los dos archivos son independientes entre sí** y ninguno importa Streamlit ni
nada del proyecto anterior. Se copiaron tal cual, sin modificar una coma.

### `src/formato.py` — `fmt_cop`

Diez líneas copiadas del proyecto anterior. Pesos con punto de miles y **sin
centavos**. Es un requisito explícito del dueño, no una preferencia estética.

### `referencia/pantalla_anterior.py` — 1.022 líneas. **Solo para mirar.**

Es la pantalla Streamlit que usaba esta misma lógica en el proyecto original.
**No corre aquí** (importa `src.database` y módulos que no existen en este
proyecto). Está para que veas cómo se conectaba todo antes de escribir la
pantalla nueva.

---

## Qué falta

### 1. Consolidar la cartera manual. Es la prioridad actual.

La interfaz ya existe: `app.py` es el punto de entrada mínimo y toda la
pantalla vive en `src/ui.py` (cartera, registro/edición con 3 modos de
impuestos, clientes y recaudo, abonos FIFO, Siigo y conciliación). Antes de
ampliar sus funcionalidades hay que revisar cada flujo con Finanzas y definir
una persistencia apta para despliegue.

### 2. Las credenciales de Siigo, para la segunda cartera.

Copia `.streamlit/secrets.toml.ejemplo` a `.streamlit/secrets.toml` y pon las
reales: usuario y access key de cada una de las tres empresas.

**Sin esto se puede construir todo, pero no probar contra datos reales.**
`secrets.toml` ya está en `.gitignore`: nunca debe subirse a GitHub.

### 3. Dónde guardar las anotaciones de revisión y los datos persistentes.

La pantalla anterior guardaba anotaciones por factura en una tabla
`siigo_revisiones` (empresa + id de factura + notas). En el proyecto original
esa tabla tenía **0 filas**: nunca se usó.

**Este proyecto tiene su PROPIO Supabase.** Decisión del dueño: base de datos
aparte, credenciales aparte, acceso aparte. No comparte nada con la aplicación
de liquidación. Eso es justamente lo que buscaban los jefes al separar la
cartera, así que no lo mezcles "para reutilizar" nada.

Si las anotaciones hacen falta:
- Crea un proyecto NUEVO en Supabase, solo para NOVASALUM.
- **No uses un archivo SQLite local si vas a desplegar en Streamlit Cloud**: el
  disco es efímero y los datos se pierden al reiniciar.
- Diseña el esquema mínimo aquí; no copies `database.py` del proyecto viejo,
  que arrastra 30 tablas que no tienen nada que ver con esto.

### ⚠️ Al conectar con Supabase vas a chocar con esto

Ya pasó en el proyecto anterior y **tumbó la aplicación en producción**. Que no
te tome por sorpresa:

Supabase usa una CA raíz propia y autofirmada ("Supabase Root 2021 CA") que no
está en `certifi` ni en el almacén del sistema. Sin anclarla, la conexión falla
con *"self-signed certificate in certificate chain"*. Y además su CA intermedia
(emitida en 2023) no declara la extensión `keyUsage`, que Python 3.13+ exige por
defecto, así que también falla con *"CA cert does not include key usage
extension"*.

El certificado ya está copiado en `certs/supabase-root-2021-ca.pem`. La receta
que funciona, sin relajar la seguridad más de lo necesario:

```python
import ssl, certifi
from pathlib import Path

_CA_SUPABASE = Path(__file__).resolve().parent.parent / "certs" / "supabase-root-2021-ca.pem"

def contexto_tls_supabase():
    contexto = ssl.create_default_context(cafile=certifi.where())
    contexto.load_verify_locations(cafile=str(_CA_SUPABASE))
    contexto.minimum_version = ssl.TLSVersion.TLSv1_2
    contexto.verify_mode = ssl.CERT_REQUIRED     # se mantiene estricto
    contexto.check_hostname = True               # se mantiene estricto
    contexto.verify_flags &= ~ssl.VERIFY_X509_STRICT   # lo único que se relaja
    return contexto
```

Se relaja **solo** `VERIFY_X509_STRICT`. La verificación del certificado y del
nombre del servidor siguen activas: esto transporta información financiera.

---

## Cómo trabaja este dueño (importante)

No es técnico. Es el dueño de la empresa. Estas no son preferencias sueltas:
son cosas que ya corrigió antes y que hay que respetar.

- **Dinero con punto de miles y SIN centavos.** Textual: "nada ,00, eso no
  está; que aproxime".
- **Las vistas se mandan como imagen** a clientes y socios. Lo importante debe
  verse de un vistazo, sin esconderlo detrás de pestañas ni ventanas emergentes.
- **Nada de ceremonias de confirmación** (frases que hay que escribir para
  confirmar). Las rechaza: la única persona con acceso es la que digita.
- **Preguntar antes de cambiar cualquier cálculo.** Si algo cambia cómo se
  paga, se liquida o se calcula una utilidad, se le avisa, se le pregunta, y
  **no se toca hasta que confirme**.
- **Trabajar por bloques**, no archivos enteros de golpe.
- **Que cargue rápido.** Lo dijo varias veces.
- Prefiere que se le diga la verdad sobre el esfuerzo y el riesgo, sin adornos.

---

## Despliegue

Recomendación dada y aceptada: **Streamlit Community Cloud**, con el
repositorio **privado** y acceso restringido por correo.

- Ya sabe operarlo (así despliega la otra aplicación).
- Gratis, y despliega solo desde GitHub.
- Contras conocidos y aceptados: se duerme por inactividad, y no guarda
  archivos (por eso las anotaciones irían a Supabase).

Si más adelante piden aislamiento real, mover esto a Render o Railway (~7
USD/mes) es agregar un archivo de configuración. No hay que reescribir nada.

---

## Próximos pasos sugeridos

1. Revisar la cartera manual con Finanzas usando los datos de demostración y
   acordar los primeros ajustes funcionales.
2. Definir una persistencia segura para la cartera manual antes de desplegarla
   en Streamlit Cloud; SQLite local no basta para producción.
3. Más adelante, configurar y probar Siigo con una consulta real de un mes por
   empresa, manteniéndola independiente de la cartera manual.
4. Definir entonces las reglas autorizadas para comparar ambas carteras.

---

## Lo que quedó pendiente en el proyecto viejo

Por si alguien pregunta: en `D:\Optimizar Novasa` todavía quedan, a propósito,
las 9 definiciones de tablas `cartera_manual_*` y sus funciones envoltorio en
`src/database.py`. Se dejaron porque tocar ese archivo es delicado y el dueño
prefirió no arriesgarlo. Son código huérfano: nadie las llama.

Las tablas de aquella cartera se borran aparte, con SQL, en el Supabase de
ESE proyecto. NOVASALUM no tiene nada que ver con esa base.
