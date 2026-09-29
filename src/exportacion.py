"""Excel de consulta: resumen y un estado de cuenta por cliente.

La función recibe una fotografía de datos; no consulta ni escribe ninguna base.
XlsxWriter funciona en el servidor Python de Streamlit sin depender de Excel.
"""

from __future__ import annotations

from collections import defaultdict
import datetime as dt
from io import BytesIO
import math
import re
from typing import Any

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

from src.siigo_vista import clave_cliente, es_vigente, nombre_cliente


EMPRESAS = ("NOVASA", "LUAC", "MSU")
COLUMNAS = (
    "Empresa", "Factura", "Fecha", "Detalle del servicio", "Placas", "Subtotal",
    "IVA", "Retefuente", "ICA", "Descuento", "Total factura", "Abonos",
    "Saldo pendiente", "Días en cartera", "Rango de días", "Moneda", "Estado",
)
MONEDA = '"$ "#,##0;[Red]("$ "#,##0);"$ "0'


def _numero(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _fecha(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _hoja(nombre: str, usados: set[str]) -> str:
    limpio = re.sub(r"[\[\]:*?/\\\x00-\x1f]", " ", nombre).strip(" '") or "Cliente"
    candidato = limpio[:31]
    numero = 2
    while candidato.casefold() in usados:
        sufijo = f" ({numero})"
        candidato = limpio[:31 - len(sufijo)] + sufijo
        numero += 1
    usados.add(candidato.casefold())
    return candidato


def _normalizar(fila: dict, origen: str) -> dict:
    manual = origen == "manual"
    completa = manual or fila.get("lectura_completa", True)
    claves = ("subtotal_cop", "iva_cop", "retefuente_cop", "ica_cop", "descuento_cop") if manual else (
        "subtotal_siigo", "iva_siigo", "retefuente_siigo", "reteica_siigo", "descuento_siigo")
    valores = [_numero(fila.get(k)) if completa else None for k in claves]
    total = _numero(fila.get("total_cop" if manual else "total_siigo"))
    abonos = _numero(fila.get("abonos_cop")) if manual else None
    saldo = _numero(fila.get("saldo_cop" if manual else "saldo_siigo"))
    anulada = bool(fila.get("anulada")) if manual else not es_vigente(fila)
    estado = "Anulada" if anulada else ("Pagada" if saldo == 0 else "Pendiente")
    if manual and not anulada and saldo and abonos:
        estado = "Abonada"
    return dict(empresa=str(fila.get("empresa_codigo") or "Sin empresa"), factura=str(fila.get("factura") or ""),
                fecha=_fecha(fila.get("fecha")), detalle=str(fila.get("descripcion" if manual else "descripcion_siigo") or ""),
                placas=str(fila.get("placas") or "") if manual else "", valores=valores,
                total=total, abonos=abonos, saldo=saldo, estado=estado,
                moneda="COP" if manual else str(fila.get("moneda") or "COP").upper(),
                anulada=anulada)


def crear_excel(filas: list[dict], *, origen: str, fecha_corte: dt.date,
                alcance: str = "Toda la cartera", fuente: str = "") -> bytes:
    """Exporta importes numéricos y fórmulas con resultados iniciales comprobables.

    En manual los totales y saldos siguen la fórmula de la aplicación. En Siigo
    se conservan los totales oficiales: un abono ausente no se deduce ni inventa.
    """
    if origen not in {"manual", "siigo"}:
        raise ValueError("Origen de cartera no válido")
    manual = origen == "manual"
    grupos: dict[str, list[dict]] = defaultdict(list)
    for fila in filas:
        clave = str(fila.get("cliente") or "Sin cliente").strip().casefold() if manual else clave_cliente(fila)
        grupos[clave].append(fila)
    salida = BytesIO()
    libro = xlsxwriter.Workbook(salida, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    libro.set_properties({"title": f"NOVASALUM - Cartera {origen}", "author": "NOVASALUM", "company": "NOVASALUM"})
    libro.set_calc_mode("auto")
    base = {"font_name": "Arial", "font_size": 10, "valign": "vcenter", "font_color": "#334155"}
    formatos = {
        "texto": libro.add_format(base),
        "detalle": libro.add_format({**base, "text_wrap": True, "valign": "top"}),
        "titulo": libro.add_format({**base, "font_size": 16, "bold": True, "font_color": "#172554"}),
        "nota": libro.add_format({**base, "font_color": "#64748B", "text_wrap": True}),
        "cabecera": libro.add_format({**base, "bg_color": "#1E3A8A", "font_color": "white", "bold": True,
                                      "text_wrap": True, "align": "center", "right": 1, "right_color": "white"}),
        "dinero": libro.add_format({**base, "num_format": MONEDA}),
        "formula": libro.add_format({**base, "num_format": MONEDA, "font_color": "#0F172A", "bg_color": "#EFF6FF"}),
        "total": libro.add_format({**base, "num_format": MONEDA, "bold": True, "bg_color": "#E2E8F0", "top": 1,
                                   "top_color": "#CBD5E1"}),
        "fecha": libro.add_format({**base, "num_format": "dd/mm/yyyy"}),
        "entero": libro.add_format({**base, "num_format": "0"}),
        "enlace": libro.add_format({**base, "font_color": "#2563EB", "underline": True, "text_wrap": True}),
        "pagada": libro.add_format({"bg_color": "#FEF9C3", "font_color": "#854D0E"}),
        "pendiente": libro.add_format({"bg_color": "#FFEDD5", "font_color": "#9A3412"}),
    }
    resumen = libro.add_worksheet("Resumen")
    resumen.hide_gridlines(2)
    resumen.set_tab_color("#1E3A8A")
    resumen.set_column("A:A", 50)
    resumen.set_column("B:B", 13)
    resumen.set_column("C:H", 21)
    resumen.set_column("I:I", 18)
    resumen.merge_range("A1:I1", f"NOVASALUM | Cartera {origen}", formatos["titulo"])
    resumen.set_row(0, 30)
    resumen.merge_range("A2:I2", f"{alcance}. {fuente}".strip(), formatos["nota"])
    resumen.write("A3", "Fecha de corte", formatos["texto"])
    resumen.write_datetime("B3", fecha_corte, formatos["fecha"])
    nota = ("Valores en COP. Total = subtotal + IVA - retefuente - ICA - descuento. Saldo = total - abonos. "
            "Las fórmulas se actualizan en Excel; esta descarga no modifica la aplicación." if manual else
            "Totales informados por Siigo, solo COP y facturas vigentes. Los campos vacíos son datos no informados, "
            "incluidos los abonos. Las otras monedas y anuladas permanecen identificadas en el detalle.")
    resumen.merge_range("A4:I4", nota, formatos["nota"])
    resumen.set_row(3, 32)
    usados = {"resumen", "history"}
    registros = []
    for grupo in sorted(grupos.values(), key=lambda g: nombre_cliente(g).casefold()):
        nombre = nombre_cliente(grupo)
        nombre_hoja = _hoja(nombre, usados)
        hoja = libro.add_worksheet(nombre_hoja)
        hoja.hide_gridlines(2)
        hoja.set_tab_color("#CBD5E1")
        hoja.set_column("A:B", 15)
        hoja.set_column("C:C", 14)
        hoja.set_column("D:D", 68)
        hoja.set_column("E:E", 18)
        hoja.set_column("F:M", 20)
        hoja.set_column("N:N", 14)
        hoja.set_column("O:O", 22)
        hoja.set_column("P:Q", 14)
        hoja.merge_range("A1:Q1", "NOVASALUM | Estado de cuenta", formatos["titulo"])
        hoja.merge_range("A2:Q2", nombre, formatos["titulo"])
        hoja.set_row(0, 28)
        hoja.set_row(1, 28)
        hoja.write("A3", "Fecha de corte", formatos["texto"])
        serial = (fecha_corte - dt.date(1899, 12, 30)).days
        hoja.write_formula("C3", "='Resumen'!$B$3", formatos["fecha"], serial)
        hoja.merge_range("A4:Q4", nota, formatos["nota"])
        hoja.set_row(3, 32)
        hoja.write_url("A5", "internal:'Resumen'!A1", formatos["enlace"], "Ir al resumen")
        hoja.write_row(6, 0, COLUMNAS, formatos["cabecera"])
        hoja.set_row(6, 32)
        datos = [_normalizar(f, origen) for f in grupo]
        datos.sort(key=lambda f: (f["empresa"], f["fecha"] or dt.date.max, f["factura"]))
        for indice, fila in enumerate(datos, 7):
            n = indice + 1
            for col, key in [(0, "empresa"), (1, "factura"), (3, "detalle"), (4, "placas"), (15, "moneda")]:
                hoja.write_string(indice, col, fila[key], formatos["detalle"] if col in (3, 4) else formatos["texto"])
            if fila["fecha"]:
                hoja.write_datetime(indice, 2, fila["fecha"], formatos["fecha"])
            for col, valor in enumerate([*fila["valores"], fila["total"], fila["abonos"], fila["saldo"]], 5):
                hoja.write(indice, col, valor, formatos["dinero"])
            if manual:
                hoja.write_formula(indice, 10, f"=F{n}+G{n}-H{n}-I{n}-J{n}", formatos["formula"], fila["total"])
                hoja.write_formula(indice, 12, f"=K{n}-L{n}", formatos["formula"], fila["saldo"])
            dias = max(0, (fecha_corte - fila["fecha"]).days) if fila["fecha"] else ""
            hoja.write_formula(indice, 13, f'=IF(C{n}="","",MAX(0,\'Resumen\'!$B$3-C{n}))', formatos["entero"], dias)
            rango = "Sin fecha" if dias == "" else next((s for limite, s in ((30, "0 a 30 días"), (60, "31 a 60 días"),
                    (90, "61 a 90 días"), (180, "91 a 180 días"), (365, "181 a 365 días")) if dias <= limite), "Más de 365 días")
            formula_rango = f'=IF(N{n}="","Sin fecha",IF(N{n}<=30,"0 a 30 días",IF(N{n}<=60,"31 a 60 días",IF(N{n}<=90,"61 a 90 días",IF(N{n}<=180,"91 a 180 días",IF(N{n}<=365,"181 a 365 días","Más de 365 días"))))))'
            hoja.write_formula(indice, 14, formula_rango, formatos["texto"], rango)
            if manual and not fila["anulada"]:
                hoja.write_formula(indice, 16, f'=IF(M{n}=0,"Pagada",IF(L{n}>0,"Abonada","Pendiente"))', formatos["texto"], fila["estado"])
            else:
                hoja.write_string(indice, 16, fila["estado"], formatos["texto"])
            lineas = sum(max(1, math.ceil(len(linea) / 62)) for linea in fila["detalle"].splitlines())
            hoja.set_row(indice, min(409, max(30, lineas * 14 + 6)))
        ultimo = 7 + len(datos)
        hoja.autofilter(6, 0, ultimo - 1, 16)
        hoja.freeze_panes(7, 3)
        hoja.repeat_rows(0, 6)
        hoja.set_landscape()
        hoja.set_paper(8)  # A3: detalle completo sin convertirlo en letra diminuta.
        hoja.fit_to_pages(1, 0)
        hoja.set_margins(0.25, 0.25, 0.4, 0.4)
        hoja.set_footer("&LNovasalum&R&P de &N")
        hoja.conditional_format(7, 16, ultimo - 1, 16, {"type": "text", "criteria": "containing", "value": "Pagada", "format": formatos["pagada"]})
        hoja.conditional_format(7, 16, ultimo - 1, 16, {"type": "text", "criteria": "containing", "value": "Abonada", "format": formatos["pendiente"]})
        resumenes = {}
        for posicion, (empresa, moneda) in enumerate(sorted({(d["empresa"], d["moneda"]) for d in datos})):
            r = ultimo + 2 + posicion
            hoja.write(r, 0, empresa, formatos["total"])
            hoja.write(r, 1, "TOTAL", formatos["total"])
            hoja.write(r, 15, moneda, formatos["total"])
            incluidos = [d for d in datos if d["empresa"] == empresa and d["moneda"] == moneda and not d["anulada"]]
            for col, clave in [(10, "total"), (11, "abonos"), (12, "saldo")]:
                letra = xl_col_to_name(col)
                cache = sum(d[clave] for d in incluidos if d[clave] is not None)
                criterio = f'$A$8:$A${ultimo},A{r+1},$P$8:$P${ultimo},P{r+1},$Q$8:$Q${ultimo},"<>Anulada"'
                suma = f'SUMIFS({letra}$8:{letra}${ultimo},{criterio})'
                # Nunca mostrar cero cuando no se recibió ningún importe.
                existe = any(d[clave] is not None for d in incluidos)
                formula = f'=IF(COUNTIFS({criterio},{letra}$8:{letra}${ultimo},"<>" )=0,"",{suma})'
                hoja.write_formula(r, col, formula, formatos["total"], cache if existe else "")
            if moneda == "COP":
                resumenes[empresa] = r + 1
        hoja.print_area(0, 0, ultimo + 2 + len({(d["empresa"], d["moneda"]) for d in datos}), 16)
        registros.append((nombre, nombre_hoja, datos, resumenes, ultimo))

    # Un enlace por cliente permite pasar del resumen a su estado de cuenta.
    resumen.write_row(12, 0, ["Cliente", "Facturas COP", "Total facturado", "Abonos", "Saldo pendiente",
                            *EMPRESAS, "Saldos sin dato"], formatos["cabecera"])
    resumen.set_row(12, 32)
    for indice, (nombre, hoja, datos, refs, ultimo) in enumerate(registros, 13):
        escapada = hoja.replace("'", "''")
        resumen.write_url(indice, 0, f"internal:'{escapada}'!A1", formatos["enlace"], nombre)
        resumen.set_row(indice, max(30, math.ceil(len(nombre) / 45) * 14 + 6))
        validas = [d for d in datos if d["moneda"] == "COP" and not d["anulada"]]
        criterio = f"'{escapada}'!$P$8:$P${ultimo},\"COP\",'{escapada}'!$Q$8:$Q${ultimo},\"<>Anulada\""
        resumen.write_formula(indice, 1, f"=COUNTIFS({criterio})", formatos["entero"], len(validas))
        for col, letra, clave in [(2, "K", "total"), (3, "L", "abonos"), (4, "M", "saldo")]:
            referencias = ",".join(f"'{escapada}'!{letra}{r}" for r in refs.values())
            cache = sum(d[clave] for d in validas if d[clave] is not None)
            formula = f'=IF(COUNT({referencias})=0,"",SUM({referencias}))' if referencias else '=""'
            resumen.write_formula(indice, col, formula, formatos["dinero"], cache if any(d[clave] is not None for d in validas) else "")
        for col, empresa in enumerate(EMPRESAS, 5):
            if empresa in refs:
                ref = f"'{escapada}'!M{refs[empresa]}"
                importe = [d["saldo"] for d in validas if d["empresa"] == empresa and d["saldo"] is not None]
                resumen.write_formula(indice, col, f'=IF({ref}="","",{ref})', formatos["dinero"], sum(importe) if importe else "")
            else:
                resumen.write_blank(indice, col, None, formatos["dinero"])
        resumen.write_formula(indice, 8, f'=COUNTIFS({criterio},\'{escapada}\'!$M$8:$M${ultimo},"=")', formatos["entero"], sum(d["saldo"] is None for d in validas))
    fin = 13 + len(registros)
    resumen.write(fin, 0, "TOTAL CARTERA COP", formatos["total"])
    for col in range(1, 9):
        letra = xl_col_to_name(col)
        valores = []
        for _, _, datos, _, _ in registros:
            for d in datos:
                if d["moneda"] != "COP" or d["anulada"]:
                    continue
                if col == 1:
                    valores.append(1)
                elif col == 8:
                    valores.append(int(d["saldo"] is None))
                elif col in (2, 3, 4):
                    valores.append(d[{2: "total", 3: "abonos", 4: "saldo"}[col]])
                else:
                    if d["empresa"] == EMPRESAS[col - 5]:
                        valores.append(d["saldo"])
        conocidos = [v for v in valores if v is not None]
        formula = f'=IF(COUNT({letra}14:{letra}{fin})=0,"",SUM({letra}14:{letra}{fin}))' if valores else "=0"
        resumen.write_formula(fin, col, formula, formatos["total"], sum(conocidos) if conocidos else (0 if not valores else ""))
    resumen.write_row(5, 0, ["Empresa", "", "Saldo pendiente (COP)"], formatos["cabecera"])
    for indice, empresa in enumerate(EMPRESAS, 6):
        resumen.write(indice, 0, empresa, formatos["texto"])
        letra = xl_col_to_name(5 + EMPRESAS.index(empresa))
        importes = [d["saldo"] for _, _, datos, _, _ in registros for d in datos if d["empresa"] == empresa and d["moneda"] == "COP" and not d["anulada"]]
        conocidos = [v for v in importes if v is not None]
        valor = sum(conocidos) if conocidos or not importes else ""
        resumen.write_formula(indice, 2, f'=IF({letra}{fin+1}="","",{letra}{fin+1})', formatos["dinero"], valor)
    resumen.write("A10", "TOTAL PENDIENTE", formatos["total"])
    todos_saldos = [d["saldo"] for _, _, datos, _, _ in registros for d in datos if d["moneda"] == "COP" and not d["anulada"] and d["saldo"] is not None]
    resumen.write_formula("C10", f"=E{fin+1}", formatos["total"], sum(todos_saldos) if todos_saldos else (0 if not registros else ""))
    resumen.merge_range("E7:I9", "Selecciona el nombre de un cliente para abrir su hoja. En cada hoja encontrarás el detalle completo y los totales por empresa. Cambia la fecha de corte para recalcular los días en cartera.", formatos["nota"])
    if registros:
        resumen.autofilter(12, 0, fin - 1, 8)
    resumen.freeze_panes(13, 1)
    resumen.set_landscape()
    resumen.fit_to_pages(1, 0)
    resumen.repeat_rows(12)
    resumen.print_area(0, 0, fin, 8)
    libro.close()
    return salida.getvalue()
