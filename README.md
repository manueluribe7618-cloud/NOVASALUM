# NOVASALUM

Aplicación de cartera para NOVASA Logistic SAS, LUAC Cargo SAS y MSU Máquinas
y Servicios.

La pantalla reúne tres flujos:

1. **Cartera manual:** registro de facturas, impuestos, placas y abonos.
2. **Espejo Siigo:** lectura en vivo de facturas y recibos de caja mediante el
   API oficial. La aplicación no puede crear, editar ni anular documentos en
   Siigo.
3. **Conciliación:** comparación factura por factura entre la cartera manual y
   la lectura de Siigo.

## Ejecutar localmente

Instala las dependencias y ejecuta:

    streamlit run app.py

La cartera manual se guarda por defecto en novasalum.db en la raíz del
proyecto. El archivo está en .gitignore. Para conservar los datos en otra
ubicación, define la variable NOVASALUM_DB con la ruta del archivo SQLite antes
de iniciar Streamlit.

La interfaz no inserta datos de prueba automáticamente. Si la cartera está
vacía, ofrece un botón para cargar una muestra visual que permite probar los
abonos FIFO y la conciliación.

## Conectar Siigo

Copia .streamlit/secrets.toml.ejemplo como .streamlit/secrets.toml y completa
las credenciales reales:

    SIIGO_PARTNER_ID = "NovaLogistics"
    SIIGO_NOVASA_USERNAME = "usuario@empresa.com"
    SIIGO_NOVASA_ACCESS_KEY = "..."

Repite las dos últimas claves para LUAC y MSU. El archivo de secretos no se
sube al repositorio.

## Reglas operativas

- Los valores se almacenan como pesos enteros y se muestran sin centavos.
- Un abono FIFO cubre las facturas pendientes de más antigua a más reciente.
- El usuario puede desactivar FIFO y repartir el abono manualmente.
- Una aplicación nunca puede superar el saldo real de una factura.
- Una factura abonada no puede reducirse por debajo de los pagos que ya tiene.
- Las anulaciones conservan el rastro en auditoría y no borran registros.
- Una revisión de conciliación queda registrada localmente y nunca modifica
  datos en Siigo.

## Validación

Las reglas de dinero se comprueban con:

    python -m unittest discover -s tests -v

El módulo actual usa SQLite para que pueda funcionar sin cuentas externas. Para
publicarlo en Streamlit Community Cloud, la siguiente etapa debe conectar esta
capa de persistencia al proyecto de Supabase exclusivo de NOVASALUM, ya que el
disco de Streamlit Cloud no es persistente.
