from __future__ import annotations

import json

import numpy as np
import plotly.graph_objects as go
import streamlit as st
import folium
import streamlit.components.v1 as components
from rasterio.warp import transform_bounds
from rasterio.transform import array_bounds

from sartrace.core import RasterScene, analyse_pair
from sartrace.demo import synthetic_pair
from sartrace.io import build_bundle, geojson_bytes, geojson_dict, read_scene, report_dict

st.set_page_config(page_title="SARtrace · Radar Change Lab", page_icon="◈", layout="wide")
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');
      html, body, [class*="css"] { font-family: 'Manrope', sans-serif; }
      .stApp { background: radial-gradient(circle at 82% 0%, #102b36 0%, #09131c 32%, #071018 70%); color: #e8f1f5; }
      [data-testid="stSidebar"] { background: #0b1720; border-right: 1px solid #1c3642; }
      .eyebrow { color:#77d9c0; font-family:'DM Mono',monospace; font-size:11px; letter-spacing:2px; }
      .hero { border:1px solid #254552; background:linear-gradient(130deg,rgba(22,57,67,.75),rgba(9,22,32,.82)); border-radius:18px; padding:24px 26px; margin:8px 0 18px 0; }
      .hero h1 { font-size:42px; letter-spacing:-2px; line-height:1; margin:9px 0; color:#f3fafb; }
      .hero p { color:#a8c0c9; max-width:850px; font-size:14px; margin:7px 0 0 0; }
      .chip { display:inline-block; padding:5px 9px; margin:7px 6px 0 0; border-radius:999px; border:1px solid #2f5965; color:#bcece0; font:10px 'DM Mono',monospace; letter-spacing:1px; }
      .section-label { color:#85a7b2; font:11px 'DM Mono',monospace; letter-spacing:1.7px; text-transform:uppercase; margin:18px 0 7px 0; }
      .metric-card { background:#0d202a; border:1px solid #254552; border-radius:12px; padding:13px 15px; min-height:86px; }
      .metric-label { color:#86a8b4; font:10px 'DM Mono',monospace; letter-spacing:1px; text-transform:uppercase; }
      .metric-value { color:#f0f9fa; font-size:25px; font-weight:800; margin-top:6px; }
      .note { border-left:3px solid #e3a85f; background:rgba(64,48,25,.25); padding:10px 13px; color:#e8d7b9; font-size:12px; border-radius:0 8px 8px 0; }
      .stButton>button { background:#6be0c0; color:#062027; border:0; border-radius:9px; font-weight:800; min-height:44px; }
      .stButton>button:hover { background:#a0f0dc; color:#062027; border:0; }
      div[data-testid="stDownloadButton"] button { background:#142a35; color:#d7edf0; border:1px solid #37616b; border-radius:8px; }
      h2, h3 { color:#e7f4f6; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
      <div class="eyebrow">FIELD SYSTEM 01 / SYNTHETIC APERTURE RADAR</div>
      <h1>SARtrace<span style="color:#69dfc0">.</span></h1>
      <p>An evidence-first change screening lab for two-date Sentinel-1 backscatter. Inspect the signal, isolate candidate regions, and export a reproducible geospatial audit pack.</p>
      <span class="chip">NO API KEY</span><span class="chip">LOCAL PROCESSING</span><span class="chip">VV / VH BACKSCATTER</span><span class="chip">AUDITABLE OUTPUTS</span>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown('<div class="eyebrow">01 / INPUT CONFIGURATION</div>', unsafe_allow_html=True)
    mode = st.radio("Data source", ["Synthetic radar pair", "Upload GeoTIFF pair"], index=0)
    st.caption("Synthetic mode is for testing the workflow only. It is not real satellite imagery.")
    units = st.selectbox("Input backscatter units", ["dB", "Linear power"], index=0, disabled=(mode == "Synthetic radar pair"))
    polarisation = st.selectbox("Polarisation", ["VV", "VH", "Other / unknown"], index=0, disabled=(mode == "Synthetic radar pair"))
    st.markdown('<div class="section-label">Detection controls</div>', unsafe_allow_html=True)
    min_change = st.slider("Minimum absolute change (dB)", 0.5, 8.0, 1.5, 0.25)
    sigma_multiplier = st.slider("Robust-noise multiplier", 0.0, 6.0, 3.0, 0.25)
    min_region = st.slider("Minimum region size (pixels)", 1, 100, 8, 1)
    st.markdown('<div class="section-label">Workflow guardrails</div>', unsafe_allow_html=True)
    st.caption("SARtrace does not calibrate, terrain-correct, deburst or co-register raw SAR products. Inputs must already share the same grid and acquisition geometry should be comparable.")

before: RasterScene | None = None
after: RasterScene | None = None

if mode == "Synthetic radar pair":
    before, after = synthetic_pair()
    st.info("DEMO DATA · Deterministic synthetic radar scenes with two injected backscatter changes. Do not cite these as real Sentinel-1 observations.")
else:
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown('<div class="section-label">Before acquisition</div>', unsafe_allow_html=True)
        before_file = st.file_uploader("Before GeoTIFF", type=["tif", "tiff"], key="before_file")
        before_date = st.text_input("Before date (optional)", placeholder="YYYY-MM-DD", key="before_date")
    with col_b:
        st.markdown('<div class="section-label">After acquisition</div>', unsafe_allow_html=True)
        after_file = st.file_uploader("After GeoTIFF", type=["tif", "tiff"], key="after_file")
        after_date = st.text_input("After date (optional)", placeholder="YYYY-MM-DD", key="after_date")
    if before_file and after_file:
        try:
            before = read_scene(before_file.getvalue(), name=before_file.name, units=units, acquisition_date=before_date or None, polarisation=None if polarisation == "Other / unknown" else polarisation)
            after = read_scene(after_file.getvalue(), name=after_file.name, units=units, acquisition_date=after_date or None, polarisation=None if polarisation == "Other / unknown" else polarisation)
        except Exception as exc:
            st.error(str(exc))

active_input_key = None
if before is not None and after is not None:
    active_input_key = (mode, before.sha256 or before.name, after.sha256 or after.name)
active_params = (float(min_change), float(sigma_multiplier), int(min_region))

run = st.button("RUN SAR CHANGE ANALYSIS", type="primary", use_container_width=True, disabled=(before is None or after is None))

if run and before is not None and after is not None:
    try:
        with st.spinner("Validating radar grids and analysing backscatter differences…"):
            result = analyse_pair(
                before, after,
                min_change_db=float(min_change),
                sigma_multiplier=float(sigma_multiplier),
                min_region_pixels=int(min_region),
            )
        st.session_state["sartrace_run"] = {
            "before": before,
            "after": after,
            "result": result,
            "input_key": active_input_key,
            "params": active_params,
        }
    except Exception as exc:
        st.error(str(exc))

run_state = st.session_state.get("sartrace_run")
if run_state and (run_state.get("input_key") != active_input_key or run_state.get("params") != active_params):
    st.warning("The inputs or detection settings changed after this run. Run the analysis again to refresh the displayed results.")
    run_state = None
if run_state:
    before = run_state["before"]
    after = run_state["after"]
    result = run_state["result"]
    st.markdown('<div class="section-label">02 / SIGNAL SUMMARY</div>', unsafe_allow_html=True)
    summary = result.summary
    metrics = st.columns(4)
    items = [
        ("Valid pixels", f"{result.valid_fraction * 100:.1f}%"),
        ("Change threshold", f"{result.threshold_db:.2f} dB"),
        ("Candidate regions", str(len(result.regions))),
        ("Changed pixels", f"{summary['candidate_change_pixels']:,}"),
    ]
    for col, (label, value) in zip(metrics, items):
        col.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="section-label">03 / RADAR EVIDENCE</div>', unsafe_allow_html=True)
    p1, p2, p3, p4 = st.columns(4)
    before_clip = np.where(result.valid_mask, result.before_db, np.nan)
    after_clip = np.where(result.valid_mask, result.after_db, np.nan)
    max_abs = float(np.nanpercentile(np.abs(result.delta_db), 99)) if np.any(result.valid_mask) else 1.0
    def heatmap(values, title, colorscale, zmin=None, zmax=None, colorbar_title=""):
        fig = go.Figure(go.Heatmap(z=values, colorscale=colorscale, zmin=zmin, zmax=zmax, colorbar={"title": colorbar_title}, hoverongaps=False))
        fig.update_layout(title={"text":title,"font":{"size":13,"color":"#d8eef0"}}, height=300, margin=dict(l=4,r=4,t=38,b=4), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#091821", font_color="#b9d0d7")
        fig.update_xaxes(visible=False); fig.update_yaxes(visible=False, autorange="reversed", scaleanchor="x")
        return fig
    with p1:
        st.plotly_chart(heatmap(before_clip, "BEFORE · BACKSCATTER", "Gray", colorbar_title="dB"), use_container_width=True, config={"displayModeBar":False})
    with p2:
        st.plotly_chart(heatmap(after_clip, "AFTER · BACKSCATTER", "Gray", colorbar_title="dB"), use_container_width=True, config={"displayModeBar":False})
    with p3:
        st.plotly_chart(heatmap(result.delta_db, "SIGNED CHANGE · AFTER − BEFORE", "RdBu", -max_abs, max_abs, "dB"), use_container_width=True, config={"displayModeBar":False})
    with p4:
        evidence_max = float(np.nanpercentile(result.evidence_index, 99)) if np.any(result.valid_mask) else 1.0
        st.plotly_chart(heatmap(result.evidence_index, "RELATIVE EVIDENCE · NOT PROBABILITY", "Viridis", 0, evidence_max, "index"), use_container_width=True, config={"displayModeBar":False})

    c1, c2 = st.columns([1.15, 0.85])
    with c1:
        st.markdown('<div class="section-label">04 / CANDIDATE REGION MAP</div>', unsafe_allow_html=True)
        mask_display = np.where(result.change_mask == 255, np.nan, result.change_mask.astype(float))
        fig = go.Figure(go.Heatmap(
            z=mask_display,
            zmin=0, zmax=2,
            colorscale=[[0,"#101c25"],[0.33,"#101c25"],[0.34,"#e3a85f"],[0.66,"#e3a85f"],[0.67,"#64d7bd"],[1,"#64d7bd"]],
            colorbar={"tickvals":[0,1,2],"ticktext":["Stable","Decrease","Increase"],"title":"Class"},
            hoverongaps=False,
        ))
        fig.update_layout(height=330, margin=dict(l=4,r=4,t=15,b=4), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#091821", font_color="#b9d0d7")
        fig.update_xaxes(visible=False); fig.update_yaxes(visible=False, autorange="reversed", scaleanchor="x")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False})
        st.caption("Amber = decreased backscatter · Mint = increased backscatter · Dark = below threshold")
    if before.name.startswith("SIMULATED"):
        st.caption("Geographic map suppressed for synthetic demo data: its projected grid is only a test coordinate frame, not a real observation location.")
    elif before.crs is not None and before.transform is not None:
        st.markdown('<div class="section-label">GEOGRAPHIC CONTEXT · REGION POLYGONS</div>', unsafe_allow_html=True)
        try:
            native_bounds = array_bounds(before.values.shape[0], before.values.shape[1], before.transform)
            west, south, east, north = transform_bounds(before.crs, "EPSG:4326", *native_bounds, densify_pts=21)
            center = [(south + north) / 2, (west + east) / 2]
            fmap = folium.Map(location=center, zoom_start=12, tiles="CartoDB positron", control_scale=True)
            folium.Rectangle(bounds=[[south, west], [north, east]], color="#70a4b0", weight=1, fill=False, tooltip="Input raster extent").add_to(fmap)
            change_geojson = geojson_dict(result, before)
            if change_geojson["features"]:
                folium.GeoJson(
                    change_geojson,
                    name="SARtrace candidate regions",
                    style_function=lambda feature: {
                        "color": "#e3a85f" if feature["properties"]["direction"] == "decreased_backscatter" else "#55d7bb",
                        "weight": 2,
                        "fillOpacity": 0.18,
                    },
                    tooltip=folium.GeoJsonTooltip(fields=["region_id", "direction", "pixels", "mean_delta_db"], aliases=["Region", "Direction", "Pixels", "Mean change (dB)"]),
                ).add_to(fmap)
            folium.LayerControl(collapsed=True).add_to(fmap)
            components.html(fmap.get_root().render(), height=420, scrolling=False)
        except Exception as map_error:
            st.caption(f"Geographic map preview unavailable for this CRS: {map_error}")
    else:
        st.caption("A geographic map preview requires CRS and affine transform metadata.")
    with c2:
        st.markdown('<div class="section-label">05 / QUALITY & INTERPRETATION</div>', unsafe_allow_html=True)
        st.write(f"**Robust noise scale:** {result.robust_noise_db:.3f} dB")
        st.write(f"**Median absolute difference:** {result.median_abs_delta_db:.3f} dB")
        st.write(f"**Backscatter decrease:** {summary['decreased_backscatter_pixels']:,} pixels")
        st.write(f"**Backscatter increase:** {summary['increased_backscatter_pixels']:,} pixels")
        st.write(f"**Input grid:** {before.values.shape[1]} × {before.values.shape[0]} pixels")
        if summary.get("pixel_area_m2"):
            st.write(f"**Pixel area:** approximately {summary['pixel_area_m2']:.1f} m²")
        else:
            st.write("**Pixel area:** not estimated (projected metric CRS unavailable)")
        st.markdown('<div class="note">A backscatter change is a candidate signal change, not proof of flooding, construction, damage or another event. Validate with acquisition metadata, independent data and domain expertise.</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-label">06 / REGION LEDGER</div>', unsafe_allow_html=True)
    if result.regions:
        rows = []
        for region in result.regions:
            rows.append({
                "ID": region.region_id,
                "Direction": region.direction.replace("_", " "),
                "Pixels": region.pixels,
                "Mean Δ (dB)": round(region.mean_delta_db, 2),
                "Median Δ (dB)": round(region.median_delta_db, 2),
                "Max |Δ| (dB)": round(region.max_abs_delta_db, 2),
                "Area (m², approx.)": round(region.area_m2, 1) if region.area_m2 is not None else "n/a",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.success("No candidate regions passed the selected threshold and minimum-size filters.")

    st.markdown('<div class="section-label">07 / AUDIT EXPORTS</div>', unsafe_allow_html=True)
    try:
        bundle = build_bundle(before, after, result)
        report = json.dumps(report_dict(before, after, result), indent=2).encode("utf-8")
        vector = geojson_bytes(result, before)
        d1, d2, d3 = st.columns(3)
        with d1:
            st.download_button("Download analysis bundle (.zip)", bundle, "sartrace_analysis_bundle.zip", "application/zip", use_container_width=True)
        with d2:
            st.download_button("Download region polygons (.geojson)", vector, "sartrace_change_regions.geojson", "application/geo+json", use_container_width=True)
        with d3:
            st.download_button("Download audit report (.json)", report, "sartrace_analysis_report.json", "application/json", use_container_width=True)
    except Exception as exc:
        st.warning(f"Raster/vector bundle export unavailable for these inputs: {exc}")

    st.caption("SARtrace v0.3.0 · local analysis · 8-connected component filtering · robust MAD thresholding · output contains candidate changes, not event classifications")
else:
    st.markdown('<div class="section-label">HOW TO RUN THE LAB</div>', unsafe_allow_html=True)
    st.markdown("""
    1. Start with the synthetic radar pair to see the complete workflow.
    2. For real work, upload two single-band calibrated Sentinel-1 VV or VH GeoTIFFs.
    3. Confirm both scenes are co-registered on exactly the same grid and use the same polarisation and compatible acquisition geometry.
    4. Run the analysis, inspect the signed change evidence, and export the GeoTIFF/GeoJSON/report bundle.
    """)
    st.markdown('<div class="note">Real-data requirement: use calibrated, terrain-corrected and co-registered backscatter. SARtrace does not process raw SAFE archives or perform orbit correction, thermal-noise removal, radiometric calibration, terrain correction, debursting or InSAR displacement estimation.</div>', unsafe_allow_html=True)
