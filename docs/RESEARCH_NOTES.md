# Research notes: reverse-engineering Earth-observation GitHub projects

**Research snapshot:** 11 November 2026. Star counts below are repository metadata snapshots collected during this audit. Counts change over time. The ranking is a focused remote-sensing / satellite-imagery search, not a claim about GitHub-wide popularity.

The purpose is to extract product and engineering patterns, not copy source code. Repository popularity is a discovery signal, not proof of scientific validity or direct suitability for SAR change analysis.

## Three highest-ranked repositories in the focused search

### 1. satellite-image-deep-learning/techniques — 10,303 stars

Repository: <https://github.com/satellite-image-deep-learning/techniques>

A curated map of deep-learning techniques and projects for satellite and aerial imagery, including classification, segmentation, object detection, change detection, SAR, explainable AI and foundation models. Its strength is a task taxonomy linked to papers and implementations. It is a research index, not an integrated processing application, and does not enforce co-registration, measurement comparability or provenance.

**SARtrace response:** keep the workflow task-specific; declare units and assumptions, validate input pairs, and measure baselines before adding learned models.

### 2. OSGeo/gdal — 6,152 stars

Repository: <https://github.com/OSGeo/gdal>

GDAL is foundational raster/vector geospatial infrastructure. Its key lesson is to treat raster metadata, CRS, affine transforms, nodata and data types as first-class contracts. File interoperability alone does not establish radiometric or geometric comparability between acquisitions.

**SARtrace response:** preserve strict grid/CRS validation, avoid silent resampling and export GeoTIFF/GeoJSON with metadata.

### 3. obss/sahi — 5,598 stars

Repository: <https://github.com/obss/sahi>

SAHI is a model-agnostic framework for sliced/tiled inference and object detection on large images, with evaluation and error-analysis utilities. The useful ideas are tiling, preserving coordinate offsets and exposing false positives and misses. It is not a SAR backscatter analysis framework; tiling does not solve speckle, registration or calibration.

**SARtrace response:** add windowed raster processing and region-level error inspection while preserving geospatial offsets.

## Valuable next-tier references

| Repository | Stars at audit | Relevant strength | SARtrace lesson |
|---|---:|---|---|
| <https://github.com/torchgeo/torchgeo> | 4,241 | Geospatial datasets, samplers, transforms and pretrained models | Explicit dataset contracts and spatial sampling |
| <https://github.com/opengeos/segment-geospatial> | 4,205 | Prompt-based segmentation and vector outputs | Optional analyst-guided refinement after signal screening |
| <https://github.com/gee-community/geemap> | 4,071 | Interactive mapping, layer inspection and time series | Before/after swipe, map layers and pixel inspector |
| <https://github.com/opengeos/geoai> | 3,466 | Integrated data prep, inference and QGIS | Future unified workflow and QGIS integration |
| <https://github.com/sentinel-hub/eo-learn> | 1,258 | Modular Earth-observation workflows | Composable processing stages |

## Specialist SAR boundary references

### pyroSAR — 616 stars

Repository: <https://github.com/johntruckenbrodt/pyroSAR>

A Python framework for scalable SAR organisation and preprocessing, including metadata handling and access to SNAP/GAMMA utilities. Raw SAR preparation is a substantial separate stage. SARtrace should orchestrate or document a proper preprocessing chain rather than claim to replace a SAR processor.

### MintPy

Repository: <https://github.com/insarlab/MintPy>

InSAR time-series analysis and displacement estimation from interferometric products. Interferometric displacement is different from two-date backscatter change; SARtrace does not claim InSAR or ground-motion capabilities.

## Feature extraction: what should become SARtrace

| Capability | Inspiration | Current status | Next implementation |
|---|---|---|---|
| Remote-sensing task clarity | techniques | Partial | Focused SAR workflow and declared measurement |
| Raster/vector interoperability | GDAL | Partial | Metadata, CRS/unit and export round-trip tests |
| Large-scene tiling | SAHI | Missing | Windowed GeoTIFF reads, tiled analysis and offset-safe merge |
| Dataset contracts | TorchGeo | Partial | Acquisition groups, spatial metadata and label alignment |
| Prompt-guided refinement | SamGeo | Missing | Optional analyst refinement after signal screening |
| Interactive layer exploration | geemap | Partial | Map viewer, layer toggles, swipe and pixel inspector |
| Modular EO processing | eo-learn | Partial | Separate download, preprocess, align, analyse, review and export stages |
| Raw SAR preprocessing | pyroSAR | Missing | SNAP/pyroSAR adapter and lineage metadata |
| InSAR displacement | MintPy | Out of scope | Separate module only if explicitly developed |

## Intended differentiation

SARtrace should not become a clone of a broad GIS toolkit or a generic segmentation demo. Its intended differentiation is:

1. **Evidence-first SAR change screening:** explain input measurements, signed changes and thresholds.
2. **Input comparability gates:** avoid silent warping; require compatible grids, polarisation, units, orbit/geometry and preprocessing lineage.
3. **Analyst-centred spatial review:** before/after, signed delta, mask, map and pixel inspector.
4. **Scalable processing:** windowed/tiled analysis preserving original coordinates.
5. **Honest evaluation:** fixed baselines, event-grouped holdout, leave-one-event-out diagnostics, per-chip failures and reference-label caveats.
6. **Reproducible output:** manifests, hashes, calibration records, software versions and machine-readable exports.
7. **Careful claims:** a signal change is not automatically a flood, ship, building, vehicle or damage event.

No source code from the referenced projects is copied into this repository. Their public descriptions, README features and published design patterns informed this synthesis.
