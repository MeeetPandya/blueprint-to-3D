from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
import struct
import zlib


@dataclass
class BlueprintTo3DConfig:
    wall_height_m: float = 3.0
    meters_per_pixel: float = 0.02
    min_component_area_px: int = 200
    binarization_threshold: int = 180
    min_wall_span_px: int = 20
    min_wall_thickness_px: int = 2
    min_component_density: float = 0.08
    cleanup_iterations: int = 1


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _read_png_grayscale(path: Path) -> list[list[int]]:
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Not a valid PNG file")

    pos = 8
    width = height = bit_depth = color_type = None
    idat = bytearray()

    while pos < len(raw):
        length = struct.unpack(">I", raw[pos : pos + 4])[0]
        chunk_type = raw[pos + 4 : pos + 8]
        chunk_data = raw[pos + 8 : pos + 8 + length]
        pos += 12 + length

        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, flt, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if compression != 0 or flt != 0 or interlace != 0:
                raise ValueError("Unsupported PNG compression/filter/interlace settings")
            if bit_depth != 8:
                raise ValueError("Only 8-bit PNGs are supported")
        elif chunk_type == b"IDAT":
            idat.extend(chunk_data)
        elif chunk_type == b"IEND":
            break

    if width is None or height is None or color_type is None:
        raise ValueError("Invalid PNG: missing IHDR")

    channels_by_color_type = {0: 1, 2: 3, 4: 2, 6: 4}
    if color_type not in channels_by_color_type:
        raise ValueError("Unsupported PNG color type")
    bpp = channels_by_color_type[color_type]

    decompressed = zlib.decompress(bytes(idat))
    stride = width * bpp
    expected = (stride + 1) * height
    if len(decompressed) != expected:
        raise ValueError("Corrupt PNG data")

    rows: list[list[int]] = []
    prev = [0] * stride
    offset = 0

    for _ in range(height):
        filter_type = decompressed[offset]
        offset += 1
        scanline = list(decompressed[offset : offset + stride])
        offset += stride

        recon = [0] * stride
        for i in range(stride):
            left = recon[i - bpp] if i >= bpp else 0
            up = prev[i]
            up_left = prev[i - bpp] if i >= bpp else 0

            if filter_type == 0:
                recon[i] = scanline[i]
            elif filter_type == 1:
                recon[i] = (scanline[i] + left) & 0xFF
            elif filter_type == 2:
                recon[i] = (scanline[i] + up) & 0xFF
            elif filter_type == 3:
                recon[i] = (scanline[i] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                recon[i] = (scanline[i] + _paeth(left, up, up_left)) & 0xFF
            else:
                raise ValueError("Unsupported PNG filter type")

        prev = recon

        row = []
        for x in range(width):
            idx = x * bpp
            if color_type == 0:
                gray = recon[idx]
            else:
                r = recon[idx]
                g = recon[idx + 1]
                b = recon[idx + 2]
                gray = int(0.299 * r + 0.587 * g + 0.114 * b)
            row.append(gray)
        rows.append(row)

    return rows


def _read_pgm(path: Path) -> list[list[int]]:
    data = path.read_bytes()
    tokens = []
    i = 0
    while i < len(data):
        c = data[i : i + 1]
        if c == b"#":
            while i < len(data) and data[i : i + 1] != b"\n":
                i += 1
        elif c.isspace():
            i += 1
        else:
            j = i
            while j < len(data) and not data[j : j + 1].isspace():
                j += 1
            tokens.append(data[i:j])
            i = j
        if len(tokens) >= 4:
            break

    magic = tokens[0].decode()
    width, height, maxval = int(tokens[1]), int(tokens[2]), int(tokens[3])
    if maxval <= 0:
        raise ValueError("Invalid PGM maxval")

    header_end = data.find(tokens[3]) + len(tokens[3])
    while header_end < len(data) and data[header_end : header_end + 1].isspace():
        header_end += 1

    if magic == "P2":
        rest = data[header_end:].decode(errors="ignore").split()
        values = [int(v) for v in rest[: width * height]]
    elif magic == "P5":
        rest = data[header_end : header_end + width * height]
        values = list(rest)
    else:
        raise ValueError("Unsupported PGM format")

    if len(values) < width * height:
        raise ValueError("PGM data is incomplete")

    if maxval != 255:
        values = [int((v / maxval) * 255) for v in values]

    rows = [values[r * width : (r + 1) * width] for r in range(height)]
    return rows


def read_grayscale_image(path: Path) -> list[list[int]]:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return _read_png_grayscale(path)
    if suffix in {".pgm", ".pnm"}:
        return _read_pgm(path)
    raise ValueError("Unsupported format. Use PNG or PGM image files.")


def binarize(grayscale: list[list[int]], threshold: int) -> list[list[int]]:
    return [[1 if px < threshold else 0 for px in row] for row in grayscale]


def _erode(binary: list[list[int]]) -> list[list[int]]:
    height = len(binary)
    width = len(binary[0]) if height else 0
    out = [[0] * width for _ in range(height)]
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            keep = 1
            for ny in (y - 1, y, y + 1):
                for nx in (x - 1, x, x + 1):
                    if binary[ny][nx] == 0:
                        keep = 0
                        break
                if keep == 0:
                    break
            out[y][x] = keep
    return out


def _dilate(binary: list[list[int]]) -> list[list[int]]:
    height = len(binary)
    width = len(binary[0]) if height else 0
    out = [[0] * width for _ in range(height)]
    for y in range(height):
        for x in range(width):
            if binary[y][x] == 1:
                for ny in range(max(0, y - 1), min(height, y + 2)):
                    for nx in range(max(0, x - 1), min(width, x + 2)):
                        out[ny][nx] = 1
    return out


def cleanup_binary(binary: list[list[int]], iterations: int) -> list[list[int]]:
    cleaned = binary
    for _ in range(max(0, iterations)):
        cleaned = _dilate(_erode(cleaned))
    return cleaned


def connected_components(
    binary: list[list[int]],
) -> list[dict[str, int | list[tuple[int, int]]]]:
    height = len(binary)
    width = len(binary[0]) if height else 0
    visited = [[False] * width for _ in range(height)]
    components = []

    for y in range(height):
        for x in range(width):
            if visited[y][x] or binary[y][x] == 0:
                continue

            q = deque([(x, y)])
            visited[y][x] = True
            area = 0
            min_x = max_x = x
            min_y = max_y = y
            pixels: list[tuple[int, int]] = []

            while q:
                cx, cy = q.popleft()
                area += 1
                pixels.append((cx, cy))
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)

                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and not visited[ny][nx] and binary[ny][nx] == 1:
                        visited[ny][nx] = True
                        q.append((nx, ny))

            components.append(
                {
                    "area": area,
                    "min_x": min_x,
                    "min_y": min_y,
                    "max_x": max_x,
                    "max_y": max_y,
                    "pixels": pixels,
                }
            )

    return components


def extract_wall_mask(binary: list[list[int]], config: BlueprintTo3DConfig) -> list[list[int]]:
    cleaned = cleanup_binary(binary, config.cleanup_iterations)
    components = connected_components(cleaned)
    height = len(cleaned)
    width = len(cleaned[0]) if height else 0
    wall_mask = [[0] * width for _ in range(height)]

    for component in components:
        area = int(component["area"])
        min_x = int(component["min_x"])
        min_y = int(component["min_y"])
        max_x = int(component["max_x"])
        max_y = int(component["max_y"])
        bbox_w = max_x - min_x + 1
        bbox_h = max_y - min_y + 1
        long_span = max(bbox_w, bbox_h)
        short_span = min(bbox_w, bbox_h)
        bbox_area = bbox_w * bbox_h
        density = area / bbox_area if bbox_area else 0.0

        keep = (
            area >= config.min_component_area_px
            and long_span >= config.min_wall_span_px
            and short_span >= config.min_wall_thickness_px
            and density >= config.min_component_density
        )

        if keep:
            pixels = component["pixels"]
            if isinstance(pixels, list):
                for x, y in pixels:
                    wall_mask[y][x] = 1

    return wall_mask


def wall_mask_to_obj(wall_mask: list[list[int]], output_path: Path, config: BlueprintTo3DConfig) -> None:
    height = len(wall_mask)
    width = len(wall_mask[0]) if height else 0
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    vertex_index: dict[tuple[float, float, float], int] = {}

    def get_vertex_idx(v: tuple[float, float, float]) -> int:
        idx = vertex_index.get(v)
        if idx is not None:
            return idx
        idx = len(vertices) + 1
        vertex_index[v] = idx
        vertices.append(v)
        return idx

    def add_quad(
        v1: tuple[float, float, float],
        v2: tuple[float, float, float],
        v3: tuple[float, float, float],
        v4: tuple[float, float, float],
    ) -> None:
        i1 = get_vertex_idx(v1)
        i2 = get_vertex_idx(v2)
        i3 = get_vertex_idx(v3)
        i4 = get_vertex_idx(v4)
        faces.append((i1, i2, i3))
        faces.append((i1, i3, i4))

    for y in range(height):
        for x in range(width):
            if wall_mask[y][x] == 0:
                continue

            x0 = x * config.meters_per_pixel
            x1 = (x + 1) * config.meters_per_pixel
            y0 = y * config.meters_per_pixel
            y1 = (y + 1) * config.meters_per_pixel
            z0 = 0.0
            z1 = config.wall_height_m

            add_quad((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))

            if y == 0 or wall_mask[y - 1][x] == 0:
                add_quad((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))
            if y == height - 1 or wall_mask[y + 1][x] == 0:
                add_quad((x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1))
            if x == 0 or wall_mask[y][x - 1] == 0:
                add_quad((x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1))
            if x == width - 1 or wall_mask[y][x + 1] == 0:
                add_quad((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1))

    if not vertices:
        raise ValueError("No wall-like regions detected. Try lowering threshold/min area or span filters.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        f.write("# Generated by blueprint-to-3D backend prototype\n")
        for x, y, z in vertices:
            f.write(f"v {x:.5f} {y:.5f} {z:.5f}\n")
        for a, b, c in faces:
            f.write(f"f {a} {b} {c}\n")


def process_blueprint_to_obj(
    image_path: Path, output_path: Path, config: BlueprintTo3DConfig | None = None
) -> None:
    config = config or BlueprintTo3DConfig()
    grayscale = read_grayscale_image(image_path)
    binary = binarize(grayscale, config.binarization_threshold)
    wall_mask = extract_wall_mask(binary, config)
    wall_mask_to_obj(wall_mask, output_path, config)
