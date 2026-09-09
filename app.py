"""Punto de entrada de la aplicación NOVASALUM."""

from __future__ import annotations

import streamlit as st


st.set_page_config(
    page_title="NOVASALUM · Cartera",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from src.ui import main


main()
