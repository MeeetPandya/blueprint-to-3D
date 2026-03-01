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


def connected_components(binary: list[list[int]], min_area: int) -> list[tuple[int, int, int, int]]:
    height = len(binary)
    width = len(binary[0]) if height else 0
    visited = [[False] * width for _ in range(height)]
    boxes = []

    for y in range(height):
        for x in range(width):
            if visited[y][x] or binary[y][x] == 0:
                continue

            q = deque([(x, y)])
            visited[y][x] = True
            area = 0
            min_x = max_x = x
            min_y = max_y = y

            while q:
                cx, cy = q.popleft()
                area += 1
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)

                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < width and 0 <= ny < height and not visited[ny][nx] and binary[ny][nx] == 1:
                        visited[ny][nx] = True
                        q.append((nx, ny))

            if area >= min_area:
                boxes.append((min_x, min_y, max_x, max_y))

    return boxes


def boxes_to_obj(boxes: list[tuple[int, int, int, int]], output_path: Path, config: BlueprintTo3DConfig) -> None:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []

    for min_x, min_y, max_x, max_y in boxes:
        rect = [
            (min_x * config.meters_per_pixel, min_y * config.meters_per_pixel),
            (max_x * config.meters_per_pixel, min_y * config.meters_per_pixel),
            (max_x * config.meters_per_pixel, max_y * config.meters_per_pixel),
            (min_x * config.meters_per_pixel, max_y * config.meters_per_pixel),
        ]

        for i in range(4):
            x1, y1 = rect[i]
            x2, y2 = rect[(i + 1) % 4]
            base = len(vertices) + 1
            vertices.extend(
                [
                    (x1, y1, 0.0),
                    (x2, y2, 0.0),
                    (x2, y2, config.wall_height_m),
                    (x1, y1, config.wall_height_m),
                ]
            )
            faces.extend([(base, base + 1, base + 2), (base, base + 2, base + 3)])

    if not vertices:
        raise ValueError("No wall-like regions detected. Try lowering threshold/min area.")

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
    boxes = connected_components(binary, config.min_component_area_px)
    boxes_to_obj(boxes, output_path, config)
