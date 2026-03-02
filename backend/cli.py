from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import BlueprintTo3DConfig, process_blueprint_to_obj


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert a 2D blueprint image into a basic extruded 3D OBJ model."
    )
    parser.add_argument("input_image", type=Path, help="Path to blueprint image (.png or .pgm)")
    parser.add_argument("output_obj", type=Path, help="Path to output OBJ file")
    parser.add_argument("--wall-height", type=float, default=3.0, help="Wall height in meters")
    parser.add_argument("--scale", type=float, default=0.02, help="Meters per pixel")
    parser.add_argument(
        "--min-area",
        type=int,
        default=200,
        help="Minimum connected wall region area in pixels",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=180,
        help="Binarization threshold (0-255), lower means stricter dark-wall detection",
    )
    parser.add_argument(
        "--min-wall-span",
        type=int,
        default=20,
        help="Minimum long-side span (pixels) for wall-like components",
    )
    parser.add_argument(
        "--min-wall-thickness",
        type=int,
        default=2,
        help="Minimum short-side span (pixels) for wall-like components",
    )
    parser.add_argument(
        "--min-density",
        type=float,
        default=0.08,
        help="Minimum fill density (area/bbox) for wall-like components",
    )
    parser.add_argument(
        "--cleanup-iterations",
        type=int,
        default=1,
        help="Morphological cleanup iterations to remove thin text/noise",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    config = BlueprintTo3DConfig(
        wall_height_m=args.wall_height,
        meters_per_pixel=args.scale,
        min_component_area_px=args.min_area,
        binarization_threshold=args.threshold,
        min_wall_span_px=args.min_wall_span,
        min_wall_thickness_px=args.min_wall_thickness,
        min_component_density=args.min_density,
        cleanup_iterations=args.cleanup_iterations,
    )

    process_blueprint_to_obj(args.input_image, args.output_obj, config)
    print(f"Wrote OBJ model to: {args.output_obj}")


if __name__ == "__main__":
    main()
