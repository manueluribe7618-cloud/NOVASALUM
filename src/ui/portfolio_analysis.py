"""Orden y análisis visual de una cartera ya leída, sin acceso a persistencia."""

from __future__ import annotations

import datetime as dt
import html
import math
import re
import unicodedata
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    from streamlit_echarts import st_echarts
except ImportError:  # Plotly queda de respaldo si el componente no está instalado.
    st_echarts = None

from src.formato import hoy_colombia, parse_cop
from src.ui.components import EMPRESAS, format_currency


AGE_RANGES = (
    "0 a 30 días", "31 a 60 días", "61 a 90 días", "91 a 180 días",
    "181 a 365 días", "Más de 365 días",
)
NO_DATE = "Sin fecha"
SORT_OPTIONS = {
    "Fecha: más antiguas primero": ("fecha", False),
    "Fecha: más recientes primero": ("fecha", True),
    "Saldo: de menor a mayor": ("saldo", False),
    "Saldo: de mayor a menor": ("saldo", True),
    "Cliente: A a Z": ("cliente", False),
    "Cliente: Z a A": ("cliente", True),
    "Días en cartera: de menor a mayor": ("dias", False),
    "Días en cartera: de mayor a menor": ("dias", True),
    "Factura: de menor a mayor": ("factura", False),
    "Factura: de mayor a menor": ("factura", True),
}
CUSTOMER_SORT_OPTIONS = (
    "Saldo: de menor a mayor", "Saldo: de mayor a menor", "Cliente: A a Z", "Cliente: Z a A",
)


def _date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def days_in_portfolio(value: Any, *, today: dt.date | None = None) -> int | None:
    issued = _date(value)
    return max(0, ((today or hoy_colombia()) - issued).days) if issued else None


def age_range(value: Any, *, today: dt.date | None = None) -> str:
    days = days_in_portfolio(value, today=today)
    if days is None:
        return NO_DATE
    for limit, label in zip((30, 60, 90, 180, 365), AGE_RANGES):
        if days <= limit:
            return label
    return AGE_RANGES[-1]


def filter_age(rows: list[dict], selected: tuple[str, ...], *, today=None) -> list[dict]:
    if not selected:
        return rows
    return [row for row in rows if age_range(row.get("fecha"), today=today) in selected]


def text_order(value: Any) -> tuple:
    """Orden natural, sin distinguir tildes/mayúsculas; ñ queda entre n y o."""
    text = str(value or "").strip().casefold().replace("ñ", "n~")
    text = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
    return tuple((1, int(part)) if part.isdigit() else (0, part)
                 for part in re.split(r"(\d+)", text))


def _number(value: Any) -> int | float | None:
    if value is None:
        return None
    try:
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def sort_invoices(rows: list[dict], order: str, *, balance_field="saldo_cop", today=None) -> list[dict]:
    field, descending = SORT_OPTIONS[order]

    def value(row):
        if field == "saldo":
            return _number(row.get(balance_field))
        if field == "fecha":
            return _date(row.get("fecha"))
        if field == "dias":
            return days_in_portfolio(row.get("fecha"), today=today)
        return text_order(row.get(field)) if row.get(field) else None

    # Los empates son estables y los datos desconocidos quedan al final en ambos sentidos.
    ordered = sorted(rows, key=lambda row: (text_order(row.get("factura")), str(row.get("id", ""))))
    known = [row for row in ordered if value(row) is not None]
    missing = [row for row in ordered if value(row) is None]
    return sorted(known, key=value, reverse=descending) + missing


def sort_customer_table(table: pd.DataFrame, order: str) -> pd.DataFrame:
    if table.empty:
        return table
    field, descending = SORT_OPTIONS[order]
    rows = table.to_dict("records")
    key = (lambda row: text_order(row["Cliente"])) if field == "cliente" else (
        lambda row: row["_saldo"] if "_saldo" in row else parse_cop(row["Saldo pendiente"])
    )
    rows = sorted(rows, key=lambda row: text_order(row["Cliente"]))
    return pd.DataFrame(sorted(rows, key=key, reverse=descending), columns=table.columns)


def aging_summary(rows: list[dict], *, balance_field="saldo_cop", today=None) -> pd.DataFrame:
    """Agrupa solo saldos positivos de las filas recibidas, sin recalcular facturas."""
    grouped = {}
    for row in rows:
        balance = _number(row.get(balance_field))
        if balance is None or balance <= 0 or row.get("anulada"):
            continue
        company = str(row.get("empresa_codigo") or "Sin empresa")
        label = age_range(row.get("fecha"), today=today)
        bucket = grouped.setdefault((company, label), {"Empresa": company, "Rango": label, "Saldo": 0, "Facturas": 0})
        bucket["Saldo"] += balance
        bucket["Facturas"] += 1
    return pd.DataFrame(grouped.values(), columns=["Empresa", "Rango", "Saldo", "Facturas"])


def compact_money(amount: float) -> str:
    if amount >= 1_000_000:
        return "$ " + f"{amount / 1_000_000:,.1f}".replace(",", "_").replace(".", ",").replace("_", ".") + " M"
    return format_currency(amount)


def _chart_style(figure: go.Figure) -> go.Figure:
    figure.update_layout(
        height=310, margin=dict(l=12, r=14, t=30, b=30),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Arial, sans-serif", color="#64748b", size=12),
        separators=",.", hoverlabel=dict(bgcolor="#ffffff", font_size=13, bordercolor="#e2e8f0"),
        showlegend=False, dragmode=False,
    )
    return figure


def portfolio_figures(summary: pd.DataFrame) -> tuple[go.Figure, go.Figure]:
    """Distribución y antigüedad interactivas, con el saldo exacto en el detalle."""
    companies = summary.groupby("Empresa", sort=False)[["Saldo", "Facturas"]].sum().sort_values("Saldo", ascending=False)
    colors = {code: data["color"] for code, data in EMPRESAS.items()}
    total = companies["Saldo"].sum()
    company_chart = go.Figure(go.Pie(
        labels=companies.index.tolist(), values=companies["Saldo"].tolist(), hole=0.76,
        sort=False, direction="clockwise", rotation=0,
        marker=dict(colors=[colors.get(code, "#64748b") for code in companies.index], line=dict(color="#ffffff", width=5)),
        textinfo="none",
        customdata=[[format_currency(row.Saldo), int(row.Facturas), f"{row.Saldo / total:.1%}".replace(".", ",")]
                    for row in companies.itertuples()],
        hovertemplate="<b>%{label}</b><br>%{customdata[0]}<br>%{customdata[2]} del saldo"
                      "<br>%{customdata[1]} facturas<extra></extra>",
    ))
    _chart_style(company_chart)
    company_chart.update_layout(
        annotations=[dict(text="SALDO PENDIENTE", x=0.5, y=0.58, showarrow=False, font=dict(size=10, color="#64748b")),
                     dict(text=f"<b>{format_currency(total)}</b>", x=0.5, y=0.45, showarrow=False, font=dict(size=19, color="#0f172a"))],
        margin=dict(l=12, r=12, t=10, b=10),
    )
    labels = [*AGE_RANGES, *([NO_DATE] if NO_DATE in set(summary["Rango"]) else [])]
    group = summary.groupby("Rango")[["Saldo", "Facturas"]].sum().reindex(labels, fill_value=0)
    breakdown = []
    for label in labels:
        parts = summary[summary["Rango"] == label]
        breakdown.append("<br>".join(f"{row.Empresa}: {format_currency(row.Saldo)}" for row in parts.itertuples()))
    age_chart = go.Figure(go.Bar(
        x=labels, y=group["Saldo"].tolist(), width=0.54,
        marker=dict(color=list(AGE_COLORS[:len(labels)]), cornerradius=7),
        text=[compact_money(v) if v else "" for v in group["Saldo"]], textposition="outside", cliponaxis=False,
        textfont=dict(size=12, color="#334155"),
        customdata=[[format_currency(row.Saldo), int(row.Facturas), detail]
                    for row, detail in zip(group.itertuples(), breakdown)],
        hovertemplate="<b>%{x}</b><br>%{customdata[0]}<br>%{customdata[1]} facturas"
                      "<br><br>%{customdata[2]}<extra></extra>",
    ))
    _chart_style(age_chart)
    maximum = float(group["Saldo"].max())
    age_chart.update_xaxes(tickmode="array", tickvals=labels, ticktext=[s.replace(" días", "<br>días") for s in labels],
                          categoryorder="array", categoryarray=labels, fixedrange=True, showgrid=False, tickfont=dict(size=11))
    ticks = [maximum * i / 3 for i in range(4)]
    age_chart.update_yaxes(range=[0, maximum * 1.25], tickmode="array", tickvals=ticks,
                          ticktext=[compact_money(v) for v in ticks], fixedrange=True,
                          gridcolor="#eef2f7", zeroline=False, automargin=True)
    return company_chart, age_chart


@st.cache_resource(max_entries=64, show_spinner=False)
def _cached_portfolio_figures(summary: pd.DataFrame) -> tuple[go.Figure, go.Figure]:
    """Las mismas cifras dan las mismas gráficas: se arman una sola vez.

    Armar las figuras de Plotly era cerca de un tercio del trabajo de cada
    clic. Se comparten entre sesiones porque ``st.plotly_chart`` solo las lee.
    """

    return portfolio_figures(summary)


AGE_SHORT = dict(zip(AGE_RANGES, ("0–30", "31–60", "61–90", "91–180", "181–365", "+365")))
AGE_COLORS = ("#c7d2fe", "#a5b4fc", "#818cf8", "#6366f1", "#4f46e5", "#3730a3", "#94a3b8")
_SHADOW = {"shadowBlur": 10, "shadowColor": "rgba(16,24,40,0.12)", "shadowOffsetY": 3}
_TOOLTIP = {
    "trigger": "item", "backgroundColor": "rgba(255,255,255,0.97)", "borderColor": "#E4E7EC",
    "borderWidth": 1, "padding": [10, 12], "textStyle": {"color": "#1D2939"},
    "extraCssText": "border-radius:12px;box-shadow:0 12px 30px rgba(16,24,40,.14);",
}
_TOOLBOX = {
    "show": True, "right": 6, "top": 0,
    "feature": {"saveAsImage": {"title": "Descargar imagen", "pixelRatio": 2, "backgroundColor": "#ffffff"}},
    "iconStyle": {"borderColor": "#667085"},
}


def _percent(part: float, total: float) -> str:
    return f"{part / total:.1%}".replace(".", ",") if total else "0,0%"


def company_chart_options(summary: pd.DataFrame) -> dict:
    """Dona por empresa con sombra; las mismas cifras de ``aging_summary``."""

    companies = summary.groupby("Empresa", sort=False)[["Saldo", "Facturas"]].sum().sort_values("Saldo", ascending=False)
    total = float(companies["Saldo"].sum())
    data = []
    for code, row in companies.iterrows():
        amount = float(row["Saldo"])
        name = html.escape(str(code))
        data.append({
            "name": str(code), "value": amount,
            "itemStyle": {"color": EMPRESAS.get(code, {}).get("color", "#64748b")},
            "tooltip": {"formatter": (
                f'<div style="font-weight:700;margin-bottom:4px">{name}</div>'
                f'<div style="font-size:16px;font-weight:700">{format_currency(amount)}</div>'
                f'<div style="color:#667085;margin-top:2px">{_percent(amount, total)} del saldo · '
                f'{int(row["Facturas"])} facturas</div>'
            )},
        })
    return {
        "backgroundColor": "transparent", "animationDuration": 800, "animationEasing": "cubicOut",
        "aria": {"enabled": True, "decal": {"show": False}},
        "title": {
            "text": compact_money(total), "subtext": "SALDO PENDIENTE", "left": "center", "top": "40%",
            "textStyle": {"color": "#0F172A", "fontSize": 17, "fontWeight": 700},
            "subtextStyle": {"color": "#64748B", "fontSize": 10, "fontWeight": 650, "lineHeight": 22},
        },
        "toolbox": _TOOLBOX, "tooltip": _TOOLTIP,
        "series": [{
            "name": "Saldo por empresa", "type": "pie", "data": data,
            "radius": ["66%", "86%"], "center": ["50%", "52%"], "label": {"show": False},
            "itemStyle": {"borderColor": "#FFFFFF", "borderWidth": 4, "borderRadius": 8, **_SHADOW},
            "emphasis": {"scale": True, "scaleSize": 7,
                         "itemStyle": {"shadowBlur": 18, "shadowColor": "rgba(16,24,40,0.18)"}},
        }],
    }


def age_chart_options(summary: pd.DataFrame) -> dict:
    """Barras por días en cartera con sombra y el desglose por empresa al pasar el mouse."""

    labels = [*AGE_RANGES, *([NO_DATE] if NO_DATE in set(summary["Rango"]) else [])]
    group = summary.groupby("Rango")[["Saldo", "Facturas"]].sum().reindex(labels, fill_value=0)
    data = []
    for color, label in zip(AGE_COLORS, labels):
        amount = float(group.loc[label, "Saldo"])
        parts = summary[summary["Rango"] == label]
        detail = "".join(
            f'<div><span style="color:#667085">{html.escape(str(part.Empresa))}:</span> '
            f'<b>{format_currency(part.Saldo)}</b></div>' for part in parts.itertuples()
        )
        data.append({
            "value": amount,
            "itemStyle": {"color": color, "borderRadius": [9, 9, 0, 0], **_SHADOW},
            "label": {"show": bool(amount), "position": "top", "formatter": compact_money(amount),
                      "color": "#334155", "fontSize": 12, "fontWeight": 600},
            "tooltip": {"formatter": (
                f'<div style="font-weight:700;margin-bottom:4px">{html.escape(label)}</div>'
                f'<div style="font-size:16px;font-weight:700">{format_currency(amount)}</div>'
                f'<div style="color:#667085;margin:2px 0 6px">{int(group.loc[label, "Facturas"])} facturas</div>'
                f'{detail}'
            )},
        })
    return {
        "backgroundColor": "transparent", "animationDuration": 720, "animationEasing": "cubicOut",
        "aria": {"enabled": True, "decal": {"show": False}},
        "grid": {"left": 8, "right": 8, "top": 40, "bottom": 8, "containLabel": True},
        "toolbox": _TOOLBOX, "tooltip": _TOOLTIP,
        "xAxis": {
            "type": "category", "data": [AGE_SHORT.get(label, label) for label in labels],
            "name": "días", "nameLocation": "end", "nameTextStyle": {"color": "#98A2B3", "fontSize": 10},
            "axisLine": {"show": False}, "axisTick": {"show": False},
            "axisLabel": {"color": "#475467", "fontSize": 11, "interval": 0, "lineHeight": 14},
        },
        "yAxis": {
            "type": "value", "axisLabel": {"show": False},
            "splitLine": {"lineStyle": {"color": "rgba(16,24,40,0.07)", "type": "dashed"}},
        },
        "series": [{
            "name": "Saldo por días en cartera", "type": "bar", "data": data, "barMaxWidth": 46,
            "showBackground": True, "backgroundStyle": {"color": "rgba(16,24,40,0.035)", "borderRadius": 9},
            "emphasis": {"itemStyle": {"shadowBlur": 16, "shadowColor": "rgba(16,24,40,0.20)"}},
        }],
    }


def _show_echart(options: dict, *, key: str) -> bool:
    if st_echarts is None:
        return False
    try:
        st_echarts(options=options, height="310px", renderer="svg", key=key)
    except Exception:
        return False
    return True


def render_portfolio_charts(rows: list[dict], *, key: str, balance_field="saldo_cop") -> None:
    summary = aging_summary(rows, balance_field=balance_field)
    missing = sum(_number(row.get(balance_field)) is None for row in rows)
    if missing:
        st.caption(f"{missing} factura(s) sin saldo informado no se incluyen en las gráficas.")
    if summary.empty:
        st.info("No hay saldo pendiente para graficar con estos filtros.")
        return
    left, right = st.columns([1, 1.5])
    with left, st.container(border=True):
        st.markdown("##### Distribución por empresa")
        st.caption("Participación en el saldo pendiente")
        if not _show_echart(company_chart_options(summary), key=f"{key}_empresas"):
            st.plotly_chart(_cached_portfolio_figures(summary)[0], width="stretch", theme=None,
                            key=f"{key}_empresas", config={"displayModeBar": False, "scrollZoom": False})
        amounts = summary.groupby("Empresa")["Saldo"].sum().sort_values(ascending=False)
        for code, amount in amounts.items():
            color = EMPRESAS.get(code, {}).get("color", "#64748b")
            st.markdown(f'<div style="display:flex;justify-content:space-between;gap:12px;font-size:13px;margin:4px 0">'
                        f'<span style="border-left:4px solid {color};padding-left:9px">{html.escape(code)}'
                        f' <span style="color:#94a3b8">{_percent(amount, amounts.sum())}</span></span>'
                        f'<strong>{format_currency(amount)}</strong></div>', unsafe_allow_html=True)
    with right, st.container(border=True):
        st.markdown("##### Días en cartera")
        st.caption("Saldo por tiempo transcurrido desde la emisión")
        if not _show_echart(age_chart_options(summary), key=f"{key}_dias"):
            st.plotly_chart(_cached_portfolio_figures(summary)[1], width="stretch", theme=None,
                            key=f"{key}_dias", config={"displayModeBar": False, "scrollZoom": False})
        by_age = summary.groupby("Rango")["Saldo"].sum()
        largest = by_age.idxmax()
        percent = f"{by_age[largest] / by_age.sum():.1%}".replace(".", ",")
        st.markdown(f"**{percent}** del saldo está entre **{largest.lower()}**." if largest.startswith(tuple("0123456789"))
                    else f"**{percent}** del saldo corresponde a **{largest.lower()}**.")
        st.caption("Pasa el cursor para ver el valor completo y el desglose por empresa. M = millones de pesos.")
    st.caption("Las gráficas siguen los filtros seleccionados y solo incluyen facturas con saldo pendiente.")
