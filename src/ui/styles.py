"""Estilos globales de la interfaz Streamlit."""

import streamlit as st


def apply_global_styles() -> None:
    """Inyecta la hoja de estilos global de NOVASALUM.

    El contenido se conserva separado del punto de arranque para que las
    vistas y los componentes no dependan de ``app.py``.
    """

    st.markdown(
        """
        <style>
            :root {
                --ink: #172033;
                --muted: #65738a;
                --canvas: #f8fafc;
                --line: #e5eaf1;
                --blue: #2563eb;
                --blue-dark: #1e3a8a;
                --green: #16a34a;
                --amber: #d97706;
                --red: #dc2626;
                --violet: #7c3aed;
                --body-font-size: .875rem;
            }
            .stApp, [data-testid="stAppViewContainer"] {
                background: var(--canvas);
                color: var(--ink);
            }
            [data-testid="stHeader"] {
                background: rgba(248, 250, 252, .92);
            }
            [data-testid="stSidebar"] {
                background: #ffffff;
                border-right: 1px solid var(--line);
            }
            [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
                color: var(--muted);
            }
            .block-container {
                max-width: 1540px;
                padding-top: 2rem;
                padding-bottom: 3rem;
            }
            h1, h2, h3 {
                color: var(--ink) !important;
                letter-spacing: -0.025em;
            }
            .brand {
                display: flex;
                align-items: center;
                gap: .7rem;
                font-weight: 800;
                letter-spacing: -.03em;
                color: var(--ink);
                font-size: 1.2rem;
            }
            .brand-mark {
                display: inline-grid;
                width: 30px;
                height: 30px;
                place-items: center;
                border-radius: 9px;
                color: white;
                background: linear-gradient(135deg, #1e3a8a, #2563eb);
                box-shadow: 0 6px 14px rgba(37, 99, 235, .22);
            }
            .eyebrow {
                color: var(--muted);
                font-size: .78rem;
                font-weight: 700;
                letter-spacing: .09em;
                text-transform: uppercase;
                margin-bottom: .35rem;
            }
            .page-subtitle {
                color: var(--muted);
                margin-top: -.35rem;
                margin-bottom: 1.15rem;
                font-size: .95rem;
            }
            .kpi-card {
                min-height: 122px;
                padding: 1.05rem 1.15rem;
                border: 1px solid var(--line);
                border-radius: 16px;
                background: #fff;
                box-shadow: 0 6px 18px rgba(15, 23, 42, .045);
            }
            .kpi-label {
                color: var(--muted);
                font-size: .8rem;
                font-weight: 700;
                letter-spacing: .025em;
                text-transform: uppercase;
            }
            .kpi-value {
                margin-top: .5rem;
                color: var(--ink);
                font-size: 1.52rem;
                font-weight: 800;
                line-height: 1.15;
                letter-spacing: -.035em;
            }
            .kpi-detail {
                margin-top: .45rem;
                color: var(--muted);
                font-size: .82rem;
            }
            .kpi-card.saldo {
                border-color: rgba(37, 99, 235, .28);
                background: linear-gradient(135deg, #eff6ff, #ffffff 72%);
            }
            .kpi-card.saldo .kpi-value { color: var(--blue); }
            .surface {
                padding: 1.15rem;
                border: 1px solid var(--line);
                border-radius: 16px;
                background: #fff;
                box-shadow: 0 5px 16px rgba(15, 23, 42, .035);
            }
            .surface-title {
                color: var(--ink);
                font-weight: 800;
                font-size: 1rem;
                letter-spacing: -.015em;
            }
            .surface-subtitle {
                margin-top: .18rem;
                color: var(--muted);
                font-size: .83rem;
            }
            .badge {
                display: inline-flex;
                align-items: center;
                width: fit-content;
                padding: .27rem .55rem;
                border-radius: 999px;
                font-size: .75rem;
                font-weight: 800;
                white-space: nowrap;
            }
            .badge-verde { background: #dcfce7; color: #166534; }
            .badge-amarillo { background: #fef3c7; color: #92400e; }
            .badge-azul { background: #dbeafe; color: #1d4ed8; }
            .badge-rojo { background: #fee2e2; color: #b91c1c; }
            .badge-gris { background: #e2e8f0; color: #475569; }
            .plate {
                display: inline-block;
                margin: 0 .28rem .28rem 0;
                padding: .28rem .48rem;
                color: #334155;
                background: #f1f5f9;
                border: 1px solid #e2e8f0;
                border-radius: 7px;
                font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                font-size: .78rem;
                font-weight: 700;
            }
            .split-card {
                min-height: 305px;
                padding: 1rem;
                background: #fff;
                border: 1px solid var(--line);
                border-radius: 14px;
            }
            .split-card.manual { border-top: 4px solid var(--blue); }
            .split-card.siigo { border-top: 4px solid var(--violet); }
            .split-title {
                margin: 0 0 .85rem;
                font-size: .92rem;
                font-weight: 800;
            }
            .split-row {
                display: flex;
                justify-content: space-between;
                gap: 1rem;
                padding: .52rem 0;
                border-bottom: 1px solid #f0f3f7;
                font-size: .86rem;
            }
            .split-row span { color: var(--muted); }
            .split-row strong { color: var(--ink); text-align: right; }
            .empty-state {
                padding: 2.2rem 1.2rem;
                border: 1px dashed #cbd5e1;
                border-radius: 16px;
                text-align: center;
                background: rgba(255,255,255,.55);
                color: var(--muted);
            }
            .activity {
                padding: .6rem 0;
                border-bottom: 1px solid #eef2f6;
                font-size: .82rem;
            }
            .activity:last-child { border-bottom: 0; }
            [data-testid="stDataFrame"] {
                border: 1px solid var(--line);
                border-radius: 12px;
                overflow: hidden;
            }
            [data-testid="stDataEditor"] {
                border: 1px solid var(--line);
                border-radius: 12px;
                overflow: hidden;
                background: #fff;
            }
            [data-testid="stDataFrame"] {
                background: #fff;
            }
            [data-testid="stTextInput"] input,
            [data-testid="stTextArea"] textarea,
            [data-testid="stNumberInput"] input,
            [data-testid="stDateInput"] input {
                color: var(--ink) !important;
                background: #fff !important;
                border: 1px solid #cbd5e1 !important;
                border-radius: 9px !important;
            }
            [data-testid="stTextInput"] input:focus,
            [data-testid="stTextArea"] textarea:focus,
            [data-testid="stNumberInput"] input:focus,
            [data-testid="stDateInput"] input:focus {
                border-color: var(--blue) !important;
                box-shadow: 0 0 0 3px rgba(37, 99, 235, .12) !important;
            }
            [data-baseweb="select"] > div {
                color: var(--ink) !important;
                background: #fff !important;
                border-color: #cbd5e1 !important;
                border-radius: 9px !important;
            }
            [data-testid="stButton"] > button {
                color: var(--ink) !important;
                background: #fff !important;
                border: 1px solid #cbd5e1 !important;
                border-radius: 9px;
                font-size: var(--body-font-size) !important;
                font-weight: 700;
                line-height: 1.25rem !important;
                box-shadow: 0 1px 2px rgba(15, 23, 42, .05);
            }
            [data-testid="stButton"] > button[kind="primary"] {
                color: var(--blue) !important;
                border-color: var(--blue) !important;
                background: #fff !important;
            }
            [data-testid="stButton"] > button:hover {
                color: var(--blue-dark) !important;
                background: #eff6ff !important;
                border-color: var(--blue) !important;
            }
            [data-testid="stSegmentedControl"] button {
                color: var(--ink) !important;
                background: #fff !important;
                border: 1px solid #cbd5e1 !important;
                border-radius: 9px !important;
                font-size: var(--body-font-size) !important;
                font-weight: 700 !important;
                line-height: 1.25rem !important;
            }
            [data-testid="stSegmentedControl"] button[aria-pressed="true"] {
                color: var(--blue-dark) !important;
                background: #eff6ff !important;
                border-color: var(--blue) !important;
            }
            /* Movimiento breve: entrada de paneles y respuesta de controles. */
            @keyframes novasalum-reveal {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            .kpi-card, .surface, .split-card {
                animation: novasalum-reveal 240ms ease-out;
                transition: border-color 180ms ease, box-shadow 180ms ease,
                            transform 180ms ease;
            }
            [role="dialog"], [role="tabpanel"] {
                animation: novasalum-reveal 200ms ease-out;
            }
            [data-baseweb="popover"] {
                animation: novasalum-reveal 140ms ease-out;
            }
            [data-testid="stButton"] > button,
            [data-testid="stSegmentedControl"] button,
            [data-testid="stTabs"] button[role="tab"] {
                transition: background-color 160ms ease, border-color 160ms ease,
                            color 160ms ease, box-shadow 160ms ease,
                            transform 120ms ease;
            }
            [data-testid="stButton"] > button:active:not(:disabled) {
                transform: scale(.985);
            }
            [data-testid="stTextInput"] input,
            [data-testid="stTextArea"] textarea,
            [data-testid="stNumberInput"] input,
            [data-testid="stDateInput"] input,
            [data-baseweb="select"] > div {
                transition: border-color 160ms ease, box-shadow 160ms ease;
            }
            [data-testid="stRadio"] label {
                border-radius: 7px;
                transition: background-color 160ms ease, color 160ms ease;
            }
            @media (hover: hover) and (pointer: fine) {
                .kpi-card:hover {
                    transform: translateY(-2px);
                    border-color: #b9ccee;
                    box-shadow: 0 10px 24px rgba(37, 99, 235, .08);
                }
                [data-testid="stButton"] > button:hover:not(:disabled) {
                    box-shadow: 0 4px 12px rgba(37, 99, 235, .10);
                }
                [data-testid="stRadio"] label:hover {
                    background-color: #eff6ff;
                }
            }
            @media (prefers-reduced-motion: reduce) {
                .stApp *, .stApp *::before, .stApp *::after,
                [role="dialog"], [role="dialog"] *, [data-baseweb="popover"] {
                    animation: none !important;
                    transition: none !important;
                }
                .kpi-card:hover,
                [data-testid="stButton"] > button:active:not(:disabled) {
                    transform: none !important;
                }
            }
            @media (max-width: 760px) {
                .block-container { padding: 1rem .8rem 2rem; }
                .kpi-value { font-size: 1.25rem; }
                .kpi-card { min-height: 104px; padding: .85rem; }
            }
            /* Estado de cuenta por cliente: réplica del cierre del Excel */
            .statement-company-total {
                text-align: right;
                color: #b91c1c;
                font-weight: 700;
                font-size: .95rem;
                margin-top: .4rem;
            }
            .statement-total-row {
                display: flex;
                justify-content: flex-end;
                align-items: center;
                gap: 1rem;
                margin-top: .6rem;
                flex-wrap: wrap;
            }
            .statement-total-context {
                color: #64748b;
                font-size: .85rem;
            }
            .statement-total-badge {
                background: #fde047;
                color: #713f12;
                font-weight: 800;
                padding: .45rem .95rem;
                border-radius: 8px;
                letter-spacing: .02em;
                white-space: nowrap;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
