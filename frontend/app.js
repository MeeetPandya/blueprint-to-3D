const app = document.getElementById("app");
const healthPill = document.getElementById("health-pill");

let activeObjAnimation = null;

function cancelActiveObjAnimation() {
  if (activeObjAnimation !== null) {
    cancelAnimationFrame(activeObjAnimation);
    activeObjAnimation = null;
  }
}

function setActiveLink(pathname) {
  document.querySelectorAll("a[data-link]").forEach((a) => {
    const href = a.getAttribute("href");
    a.classList.toggle("active", href === pathname);
  });
}

function navigate(path) {
  if (window.location.pathname !== path) {
    history.pushState({}, "", path);
  }
  render();
}

async function getJson(url) {
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

async function postConvert(file, config) {
  const qs = new URLSearchParams(config);
  const res = await fetch(`/api/convert?${qs.toString()}`, {
    method: "POST",
    headers: {
      "Content-Type": file.type || "application/octet-stream",
    },
    body: file,
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || "Conversion failed");
  }
  return data;
}

function homeView() {
  return `
    <section class="card">
      <h2>Convert Blueprint Images to OBJ</h2>
      <p>Upload PNG/PGM blueprints, generate wall meshes, and preview both blueprint and 3D output in-browser.</p>
      <button id="start-convert">Start Conversion</button>
    </section>
  `;
}

function convertView() {
  return `
    <section class="card">
      <h2>New Conversion</h2>
      <form id="convert-form">
        <div class="grid">
          <label>Blueprint file
            <input id="blueprint-file" name="file" type="file" accept=".png,.pgm,.pnm,image/png" required />
          </label>
          <label>Wall height (m)
            <input name="wall_height" type="number" step="0.1" value="3.0" required />
          </label>
          <label>Scale (m per pixel)
            <input name="scale" type="number" step="0.001" value="0.02" required />
          </label>
          <label>Min area
            <input name="min_area" type="number" value="200" required />
          </label>
          <label>Threshold
            <input name="threshold" type="number" value="180" required />
          </label>
          <label>Cleanup iterations
            <input name="cleanup_iterations" type="number" value="1" required />
          </label>
        </div>
        <p id="convert-status"></p>
        <button type="submit">Convert</button>
      </form>
    </section>

    <section class="viewer-layout">
      <article class="card">
        <h3>Blueprint Viewer (PNG/PGM)</h3>
        <canvas id="blueprint-preview" class="viewer-canvas" width="640" height="360"></canvas>
        <p id="blueprint-meta" class="viewer-meta">Select a blueprint file to preview.</p>
      </article>
      <article class="card">
        <h3>OBJ Viewer</h3>
        <canvas id="obj-preview" class="viewer-canvas" width="640" height="360"></canvas>
        <p id="obj-meta" class="viewer-meta">Convert a blueprint or pick a model in Models tab to preview.</p>
      </article>
    </section>
  `;
}

function modelsView() {
  return `
    <section class="card">
      <h2>Generated Models</h2>
      <div id="models-list">Loading...</div>
    </section>

    <section class="card">
      <h3>OBJ Viewer</h3>
      <canvas id="models-obj-viewer" class="viewer-canvas" width="640" height="360"></canvas>
      <p id="models-obj-meta" class="viewer-meta">Click "View" on a model to preview it.</p>
    </section>
  `;
}

function drawPlaceholder(canvas, message) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || canvas.width;
  const height = canvas.clientHeight || canvas.height;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  ctx.fillStyle = "#f0f2f3";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#d9dfdd";
  ctx.strokeRect(0.5, 0.5, width - 1, height - 1);
  ctx.fillStyle = "#5e6977";
  ctx.font = "14px Segoe UI";
  ctx.fillText(message, 16, Math.floor(height / 2));
}

function parsePgm(bytes) {
  let i = 0;
  const data = bytes;

  function isWhitespace(v) {
    return v === 9 || v === 10 || v === 13 || v === 32;
  }

  function readToken() {
    while (i < data.length) {
      if (data[i] === 35) {
        while (i < data.length && data[i] !== 10) {
          i += 1;
        }
      } else if (isWhitespace(data[i])) {
        i += 1;
      } else {
        break;
      }
    }

    const start = i;
    while (i < data.length && !isWhitespace(data[i])) {
      i += 1;
    }
    if (start === i) {
      return null;
    }
    return new TextDecoder().decode(data.slice(start, i));
  }

  const magic = readToken();
  const width = Number(readToken());
  const height = Number(readToken());
  const maxval = Number(readToken());

  if (!(magic === "P2" || magic === "P5")) {
    throw new Error("Unsupported PGM format. Use P2 or P5.");
  }
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new Error("Invalid PGM dimensions.");
  }
  if (!Number.isFinite(maxval) || maxval <= 0) {
    throw new Error("Invalid PGM max value.");
  }

  while (i < data.length && isWhitespace(data[i])) {
    i += 1;
  }

  const pixels = new Uint8ClampedArray(width * height);
  if (magic === "P5") {
    const expected = width * height;
    const raw = data.slice(i, i + expected);
    if (raw.length < expected) {
      throw new Error("PGM pixel data is incomplete.");
    }
    for (let idx = 0; idx < expected; idx += 1) {
      pixels[idx] = Math.round((raw[idx] / maxval) * 255);
    }
  } else {
    const text = new TextDecoder().decode(data.slice(i));
    const values = text.split(/\s+/).filter(Boolean);
    if (values.length < width * height) {
      throw new Error("PGM pixel data is incomplete.");
    }
    for (let idx = 0; idx < width * height; idx += 1) {
      const value = Number(values[idx]);
      pixels[idx] = Math.round((value / maxval) * 255);
    }
  }

  return { width, height, pixels };
}

function drawPgmOnCanvas(canvas, pgm) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  canvas.width = pgm.width;
  canvas.height = pgm.height;

  const imageData = ctx.createImageData(pgm.width, pgm.height);
  for (let idx = 0; idx < pgm.pixels.length; idx += 1) {
    const g = pgm.pixels[idx];
    const base = idx * 4;
    imageData.data[base] = g;
    imageData.data[base + 1] = g;
    imageData.data[base + 2] = g;
    imageData.data[base + 3] = 255;
  }
  ctx.putImageData(imageData, 0, 0);
}

async function previewBlueprintFile(file, canvas, meta) {
  if (!file) {
    drawPlaceholder(canvas, "No file selected.");
    meta.textContent = "Select a blueprint file to preview.";
    return;
  }

  const lower = file.name.toLowerCase();
  const isPng = file.type === "image/png" || lower.endsWith(".png");
  const isPgm = lower.endsWith(".pgm") || lower.endsWith(".pnm") || file.type.includes("portable-graymap");

  try {
    if (isPng) {
      const blobUrl = URL.createObjectURL(file);
      const image = new Image();
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = () => reject(new Error("Failed to load PNG preview."));
        image.src = blobUrl;
      });

      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const ctx = canvas.getContext("2d");
      if (ctx) {
        ctx.drawImage(image, 0, 0);
      }
      URL.revokeObjectURL(blobUrl);
      meta.textContent = `${file.name} | ${image.naturalWidth}x${image.naturalHeight}`;
      return;
    }

    if (isPgm) {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const pgm = parsePgm(bytes);
      drawPgmOnCanvas(canvas, pgm);
      meta.textContent = `${file.name} | ${pgm.width}x${pgm.height} (PGM)`;
      return;
    }

    throw new Error("Unsupported preview format. Use PNG or PGM.");
  } catch (err) {
    drawPlaceholder(canvas, "Preview unavailable.");
    meta.textContent = err.message;
    meta.classList.add("error");
  }
}

function parseObjText(objText) {
  const vertices = [];
  const edgeSet = new Set();

  const lines = objText.split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }
    if (trimmed.startsWith("v ")) {
      const parts = trimmed.split(/\s+/);
      const x = Number(parts[1]);
      const y = Number(parts[2]);
      const z = Number(parts[3]);
      if (Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z)) {
        vertices.push([x, y, z]);
      }
      continue;
    }
    if (trimmed.startsWith("f ")) {
      const parts = trimmed.split(/\s+/).slice(1);
      const face = parts
        .map((part) => Number(part.split("/")[0]))
        .filter((value) => Number.isInteger(value) && value > 0)
        .map((value) => value - 1);

      for (let i = 0; i < face.length; i += 1) {
        const a = face[i];
        const b = face[(i + 1) % face.length];
        if (a === b) continue;
        const key = a < b ? `${a}-${b}` : `${b}-${a}`;
        edgeSet.add(key);
      }
    }
  }

  const edges = [];
  for (const key of edgeSet.values()) {
    const [a, b] = key.split("-").map(Number);
    if (vertices[a] && vertices[b]) {
      edges.push([a, b]);
    }
  }

  if (!vertices.length || !edges.length) {
    throw new Error("OBJ has no renderable geometry.");
  }

  return { vertices, edges };
}

function normalizeVertices(vertices) {
  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let maxZ = -Infinity;

  for (const [x, y, z] of vertices) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    minZ = Math.min(minZ, z);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
    maxZ = Math.max(maxZ, z);
  }

  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const cz = (minZ + maxZ) / 2;
  const size = Math.max(maxX - minX, maxY - minY, maxZ - minZ) || 1;

  return vertices.map(([x, y, z]) => [
    (x - cx) / size,
    (y - cy) / size,
    (z - cz) / size,
  ]);
}

function startObjViewer(canvas, objText, meta, label) {
  cancelActiveObjAnimation();

  let parsed;
  try {
    parsed = parseObjText(objText);
  } catch (err) {
    drawPlaceholder(canvas, "OBJ preview unavailable.");
    meta.textContent = err.message;
    meta.classList.add("error");
    return;
  }

  meta.classList.remove("error");
  meta.textContent = `${label} | ${parsed.vertices.length} vertices, ${parsed.edges.length} edges`;

  const vertices = normalizeVertices(parsed.vertices);
  const edges = parsed.edges;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  function draw(timeMs) {
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || canvas.width;
    const height = canvas.clientHeight || canvas.height;
    canvas.width = Math.max(1, Math.floor(width * dpr));
    canvas.height = Math.max(1, Math.floor(height * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    ctx.fillStyle = "#fbfcfd";
    ctx.fillRect(0, 0, width, height);

    const t = timeMs / 1000;
    const ay = t * 0.6;
    const ax = 0.45;

    const cosY = Math.cos(ay);
    const sinY = Math.sin(ay);
    const cosX = Math.cos(ax);
    const sinX = Math.sin(ax);

    const projected = vertices.map(([x, y, z]) => {
      const rx = x * cosY - z * sinY;
      const rz = x * sinY + z * cosY;
      const ry = y * cosX - rz * sinX;
      const rz2 = y * sinX + rz * cosX;

      const camera = 2.4;
      const perspective = camera / (camera + rz2 + 1.5);
      const scale = Math.min(width, height) * 0.42;

      return {
        x: width / 2 + rx * perspective * scale,
        y: height / 2 - ry * perspective * scale,
      };
    });

    ctx.strokeStyle = "#0f766e";
    ctx.lineWidth = 1;
    ctx.beginPath();

    for (const [a, b] of edges) {
      const p1 = projected[a];
      const p2 = projected[b];
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
    }

    ctx.stroke();
    activeObjAnimation = requestAnimationFrame(draw);
  }

  activeObjAnimation = requestAnimationFrame(draw);
}

async function loadObjFromUrl(url, canvas, meta, label) {
  try {
    const res = await fetch(url);
    const text = await res.text();
    if (!res.ok) {
      throw new Error("Failed to load OBJ.");
    }
    startObjViewer(canvas, text, meta, label);
  } catch (err) {
    drawPlaceholder(canvas, "OBJ preview unavailable.");
    meta.textContent = err.message;
    meta.classList.add("error");
  }
}

async function renderModels() {
  const container = document.getElementById("models-list");
  const viewer = document.getElementById("models-obj-viewer");
  const meta = document.getElementById("models-obj-meta");

  if (viewer && meta) {
    drawPlaceholder(viewer, "No model selected.");
  }

  try {
    const data = await getJson("/api/models");
    if (!data.models.length) {
      container.innerHTML = "<p>No models generated yet.</p>";
      return;
    }

    container.innerHTML = `<div class="list">${data.models
      .map(
        (m) => `
          <article class="list-item">
            <strong>${m.name}</strong><br />
            <small>${m.size_bytes} bytes | ${m.modified_utc}</small><br />
            <div class="row-actions">
              <a href="${m.download_url}">Download</a>
              <button type="button" class="view-obj-btn" data-url="${m.download_url}" data-name="${m.name}">View</button>
            </div>
          </article>`
      )
      .join("")}</div>`;

    container.querySelectorAll(".view-obj-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (!viewer || !meta) return;
        const url = btn.getAttribute("data-url");
        const name = btn.getAttribute("data-name") || "OBJ";
        if (!url) return;
        loadObjFromUrl(url, viewer, meta, name);
      });
    });
  } catch (err) {
    container.innerHTML = `<p class="error">${err.message}</p>`;
  }
}

function bindConvertForm() {
  const form = document.getElementById("convert-form");
  const fileInput = document.getElementById("blueprint-file");
  const blueprintCanvas = document.getElementById("blueprint-preview");
  const blueprintMeta = document.getElementById("blueprint-meta");
  const objCanvas = document.getElementById("obj-preview");
  const objMeta = document.getElementById("obj-meta");

  if (!form || !fileInput || !blueprintCanvas || !blueprintMeta || !objCanvas || !objMeta) {
    return;
  }

  drawPlaceholder(blueprintCanvas, "Select PNG or PGM file.");
  drawPlaceholder(objCanvas, "Run conversion to preview OBJ.");

  fileInput.addEventListener("change", async () => {
    blueprintMeta.classList.remove("error");
    await previewBlueprintFile(fileInput.files?.[0], blueprintCanvas, blueprintMeta);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const status = document.getElementById("convert-status");
    status.textContent = "Converting...";
    status.className = "";

    const formData = new FormData(form);
    const file = formData.get("file");
    if (!(file instanceof File)) {
      status.textContent = "Please select a file.";
      status.className = "error";
      return;
    }

    const config = {
      wall_height: formData.get("wall_height"),
      scale: formData.get("scale"),
      min_area: formData.get("min_area"),
      threshold: formData.get("threshold"),
      cleanup_iterations: formData.get("cleanup_iterations"),
    };

    try {
      const result = await postConvert(file, config);
      status.innerHTML = `Done. <a href="${result.download_url}">Download ${result.model}</a>`;
      await loadObjFromUrl(result.download_url, objCanvas, objMeta, result.model);
    } catch (err) {
      status.className = "error";
      status.textContent = err.message;
    }
  });
}

async function updateHealth() {
  try {
    await getJson("/api/health");
    healthPill.textContent = "API online";
  } catch {
    healthPill.textContent = "API offline";
    healthPill.classList.add("error");
  }
}

function render() {
  cancelActiveObjAnimation();

  const path = window.location.pathname;
  setActiveLink(path);

  if (path === "/convert") {
    app.innerHTML = convertView();
    bindConvertForm();
    return;
  }

  if (path === "/models") {
    app.innerHTML = modelsView();
    renderModels();
    return;
  }

  app.innerHTML = homeView();
  const startBtn = document.getElementById("start-convert");
  if (startBtn) {
    startBtn.addEventListener("click", () => navigate("/convert"));
  }
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("a[data-link]");
  if (!target) return;
  event.preventDefault();
  navigate(target.getAttribute("href"));
});

window.addEventListener("popstate", render);

updateHealth();
render();
