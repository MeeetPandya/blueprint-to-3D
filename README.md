# Blueprint-to-3D: Mobile Automated Architectural Pipeline

This repository now contains a practical project blueprint for building an application that converts a 2D floor plan image into a walkable 3D experience on mobile.

## 1) Core Workflow

1. **Image Pre-processing**
   - Denoise input
   - Normalize contrast/brightness
   - Correct perspective and shadows
   - Prepare a binary/edge-friendly representation

2. **Feature Extraction**
   - Detect structural lines/contours (walls)
   - Identify symbols (doors/windows/openings)
   - Infer room regions and adjacency

3. **3D Mesh Generation**
   - Convert 2D layout geometry into clean polygons
   - Extrude walls to target height
   - Add door/window voids where appropriate
   - Export lightweight runtime assets (`.glb`, `.obj`)

4. **Mobile Rendering**
   - Load generated model into real-time scene
   - Add first-person navigation controls
   - Optimize for low-poly + low draw-call performance

## 2) Recommended Technical Stack

### A. Vision Layer (Blueprint Parsing)

- **OpenCV** for classic CV operations:
  - edge detection
  - contour extraction
  - morphological transforms
- **YOLO/CNN (optional but valuable)** for symbol detection (doors/windows/furniture markers)

### B. Geometry Layer (2D → 3D)

- **Shapely** for robust 2D polygon operations and topology cleanup
- **Trimesh** (or Blender Python API) to generate/export final 3D assets

### C. Mobile Experience Layer

- **Unity/Unreal** for native, high-fidelity runtime
- **Three.js / React Three Fiber** for browser-based delivery with WebGL

## 3) Challenges and Mitigations

| Challenge | Mitigation |
| --- | --- |
| Missing or ambiguous scale | Require one user calibration measurement (e.g., known door width). |
| Visual noise (text, symbols, furniture) | Use thresholding + erosion/dilation + filtering heuristics. |
| Mobile performance constraints | Generate low-poly meshes, merge static geometry, minimize material count. |

## 4) Suggested Delivery Phases

1. **Phase 1: Offline conversion prototype**
   - Input: clean monochrome blueprint
   - Output: basic extruded `.obj`/`.glb`

2. **Phase 2: Walkthrough runtime**
   - Import generated model into Unity or Three.js
   - Implement movement + collision

3. **Phase 3: End-to-end mobile product**
   - Upload image from mobile UI
   - Run CV + mesh generation pipeline
   - Return and render model in-app

## 5) Optional AR Expansion

For higher product value, add placement/inspection in AR:

- **ARCore** (Android)
- **ARKit** (iOS)

This enables users to place the generated structure in physical space for review.

## 6) Terminal Backend Prototype (Implemented)

A basic backend pipeline is now included in `backend/`.

### Install dependencies

```bash
# No external packages needed for this prototype.
# (requirements.txt is intentionally empty of third-party deps)
```

### Run conversion

```bash
python -m backend.cli path/to/blueprint.png output/model.obj
```

Useful options:

- `--wall-height`: wall extrusion height in meters (default `3.0`)
- `--scale`: meters per pixel conversion factor (default `0.02`)
- `--min-area`: ignore tiny wall-like connected regions
- `--threshold`: grayscale threshold for wall detection

### What this prototype does

1. Loads grayscale blueprint image.
2. Converts image to grayscale and binarizes potential wall pixels.
3. Finds connected components and converts them to wall bounding boxes.
4. Extrudes each box edge vertically into a simple OBJ mesh.

This is intentionally minimal and terminal-driven so you can plug it into larger services later.
