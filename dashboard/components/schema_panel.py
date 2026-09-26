"""Schema browser panel — shows the in-scope tables/columns before users ask."""
import streamlit as st

from common.config import SCHEMA_PATH


def render_schema_panel() -> None:
    st.subheader("Schema in scope", divider="gray")
    st.caption("Only these tables/columns are answerable — anything else is refused.")
    st.code(SCHEMA_PATH.read_text(), language="sql")
