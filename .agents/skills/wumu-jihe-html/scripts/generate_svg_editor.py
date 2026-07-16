#!/usr/bin/env python3
# ruff: noqa: E501
"""把几何语义 JSON 生成为单文件 SVG 几何编辑器。"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "assets" / "svg-editor-template.html"
INSERT_MARKER = "<!-- SVG_OBJECTS -->"
ALLOWED_TAGS = {"circle", "ellipse", "line", "path", "polygon", "polyline", "rect", "text", "solid"}
ALLOWED_ATTRS = {
    "cx",
    "cy",
    "r",
    "rx",
    "ry",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "width",
    "height",
    "d",
    "points",
    "transform",
    "stroke",
    "fill",
    "stroke-width",
    "stroke-dasharray",
    "opacity",
    "fill-rule",
    "font-size",
}


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def number(attrs: dict, name: str, index: int, *, minimum: float | None = None) -> float:
    try:
        value = float(attrs[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"elements[{index}] 的 {name} 必须是数值") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"elements[{index}] 的 {name} 不能小于 {minimum:g}")
    return value


def fmt(value: float) -> str:
    return f"{value:g}"


def cuboid_paths(
    cx: float, cy: float, width: float, height: float, ox: float, oy: float
) -> dict[str, str]:
    """Return the editable cuboid faces and hidden edges used by the editor."""
    fx, fy = cx - width / 2, cy - height / 2
    bx, by = fx + ox, fy + oy
    face_side = (
        f"M {fmt(fx + width)} {fmt(fy)} L {fmt(bx + width)} {fmt(by)} "
        f"L {fmt(bx + width)} {fmt(by + height)} L {fmt(fx + width)} {fmt(fy + height)} Z"
        if ox >= 0
        else f"M {fmt(fx)} {fmt(fy)} L {fmt(bx)} {fmt(by)} "
        f"L {fmt(bx)} {fmt(by + height)} L {fmt(fx)} {fmt(fy + height)} Z"
    )
    face_top = (
        f"M {fmt(fx)} {fmt(fy)} L {fmt(bx)} {fmt(by)} "
        f"L {fmt(bx + width)} {fmt(by)} L {fmt(fx + width)} {fmt(fy)} Z"
        if oy <= 0
        else f"M {fmt(fx)} {fmt(fy + height)} L {fmt(bx)} {fmt(by + height)} "
        f"L {fmt(bx + width)} {fmt(by + height)} L {fmt(fx + width)} {fmt(fy + height)} Z"
    )
    front = f"M {fmt(fx)} {fmt(fy)} L {fmt(fx + width)} {fmt(fy)} L {fmt(fx + width)} {fmt(fy + height)} L {fmt(fx)} {fmt(fy + height)} Z"
    edges = {
        "tl": f"M {fmt(fx)} {fmt(fy)} L {fmt(bx)} {fmt(by)}",
        "tr": f"M {fmt(fx + width)} {fmt(fy)} L {fmt(bx + width)} {fmt(by)}",
        "br": f"M {fmt(fx + width)} {fmt(fy + height)} L {fmt(bx + width)} {fmt(by + height)}",
        "bl": f"M {fmt(fx)} {fmt(fy + height)} L {fmt(bx)} {fmt(by + height)}",
        "bt": f"M {fmt(bx)} {fmt(by)} L {fmt(bx + width)} {fmt(by)}",
        "brr": f"M {fmt(bx + width)} {fmt(by)} L {fmt(bx + width)} {fmt(by + height)}",
        "bb": f"M {fmt(bx + width)} {fmt(by + height)} L {fmt(bx)} {fmt(by + height)}",
        "bll": f"M {fmt(bx)} {fmt(by + height)} L {fmt(bx)} {fmt(by)}",
    }
    if ox >= 0 and oy <= 0:
        hidden = {"bl", "bll", "bb"}
    elif ox < 0 and oy <= 0:
        hidden = {"br", "brr", "bb"}
    elif ox >= 0:
        hidden = {"tl", "bll", "bt"}
    else:
        hidden = {"tr", "brr", "bt"}
    hidden_edges = [edge for name, edge in edges.items() if name in hidden]
    visible_edges = [edge for name, edge in edges.items() if name not in hidden]
    return {
        "back": " ".join(hidden_edges),
        "right": face_side,
        "top": face_top,
        "front": front,
        "shape_front": " ".join([front, *visible_edges]),
    }


def render_cuboid(item: dict, index: int, chinese_kind: str) -> str:
    attrs = dict(item.get("attrs") or {})
    cx = number(attrs, "cx", index)
    cy = number(attrs, "cy", index)
    width = number(attrs, "w", index, minimum=10)
    height = width if chinese_kind == "正方体" else number(attrs, "h", index, minimum=10)
    ox = float(attrs.get("ox", width * 0.35))
    oy = float(attrs.get("oy", -height * 0.35))
    stroke = esc(attrs.get("stroke", "#000000"))
    stroke_width = esc(attrs.get("stroke-width", 2))
    transform = f' transform="{esc(attrs["transform"])}"' if attrs.get("transform") else ""
    group = f' data-group="{esc(item["group"])}"' if item.get("group") else ""
    css_class = "cube" if chinese_kind == "正方体" else "cuboid"
    paths = cuboid_paths(cx, cy, width, height, ox, oy)
    return (
        f'<g class="object {css_class}" data-kind="{chinese_kind}" data-id="object-{index}"{group}'
        f' data-cx="{fmt(cx)}" data-cy="{fmt(cy)}" data-w="{fmt(width)}" data-h="{fmt(height)}"'
        f' data-ox="{fmt(ox)}" data-oy="{fmt(oy)}" stroke="{stroke}" fill="none"{transform}>\n'
        f'  <path class="shape-back" d="{paths["back"]}" fill="none" stroke-width="{stroke_width}" stroke-dasharray="6 6"/>\n'
        f'  <path class="face-right" d="{paths["right"]}" fill="none" stroke="none"/>\n'
        f'  <path class="face-front" d="{paths["front"]}" fill="none" stroke="none"/>\n'
        f'  <path class="face-top" d="{paths["top"]}" fill="none" stroke="none"/>\n'
        f'  <path class="shape-front" d="{paths["shape_front"]}" fill="none" stroke-width="{stroke_width}"/>\n'
        "</g>"
    )


def render_solid(item: dict, index: int) -> str:
    kind = str(item.get("kind") or "")
    kind_names = {
        "圆柱": "圆柱",
        "cylinder": "圆柱",
        "圆锥": "圆锥",
        "cone": "圆锥",
        "正方体": "正方体",
        "cube": "正方体",
        "长方体": "长方体",
        "cuboid": "长方体",
    }
    if kind not in kind_names:
        raise ValueError(f"elements[{index}] 的 solid kind 仅支持圆柱、圆锥、正方体或长方体")
    chinese_kind = kind_names[kind]
    if chinese_kind in {"正方体", "长方体"}:
        return render_cuboid(item, index, chinese_kind)
    css_class = "cylinder" if chinese_kind == "圆柱" else "cone"
    attrs = dict(item.get("attrs") or {})
    cx = number(attrs, "cx", index)
    cy1 = number(attrs, "cy1", index)
    cy2 = number(attrs, "cy2", index)
    rx = number(attrs, "rx", index, minimum=4)
    ry = float(attrs.get("ry", max(4, rx * 0.3)))
    if ry < 4:
        raise ValueError(f"elements[{index}] 的 ry 不能小于 4")
    if cy1 > cy2:
        cy1, cy2 = cy2, cy1

    stroke = esc(attrs.get("stroke", "#000000"))
    fill = esc(attrs.get("fill", "none"))
    opacity = esc(attrs.get("opacity", 0.42))
    stroke_width = esc(attrs.get("stroke-width", 2))
    transform = f' transform="{esc(attrs["transform"])}"' if attrs.get("transform") else ""
    group = f' data-group="{esc(item["group"])}"' if item.get("group") else ""
    common = (
        f'class="object {css_class}" data-kind="{chinese_kind}" data-id="object-{index}"{group}'
        f' data-cx="{fmt(cx)}" data-cy1="{fmt(cy1)}" data-cy2="{fmt(cy2)}"'
        f' data-rx="{fmt(rx)}" data-ry="{fmt(ry)}" stroke="{stroke}"{transform}'
    )
    left, right = cx - rx, cx + rx

    if chinese_kind == "圆柱":
        background = f"M {fmt(left)} {fmt(cy1)} A {fmt(rx)} {fmt(ry)} 0 0 1 {fmt(right)} {fmt(cy1)} L {fmt(right)} {fmt(cy2)} A {fmt(rx)} {fmt(ry)} 0 0 1 {fmt(left)} {fmt(cy2)} Z"
        front = f"M {fmt(left)} {fmt(cy1)} L {fmt(left)} {fmt(cy2)} A {fmt(rx)} {fmt(ry)} 0 0 0 {fmt(right)} {fmt(cy2)} L {fmt(right)} {fmt(cy1)}"
        top = f'<ellipse class="shape-front" cx="{fmt(cx)}" cy="{fmt(cy1)}" rx="{fmt(rx)}" ry="{fmt(ry)}" fill="none" stroke-width="{stroke_width}"/>'
    else:
        background = f"M {fmt(cx)} {fmt(cy1)} L {fmt(right)} {fmt(cy2)} A {fmt(rx)} {fmt(ry)} 0 0 1 {fmt(left)} {fmt(cy2)} Z"
        front = f"M {fmt(cx)} {fmt(cy1)} L {fmt(left)} {fmt(cy2)} A {fmt(rx)} {fmt(ry)} 0 0 0 {fmt(right)} {fmt(cy2)} Z"
        top = ""

    back = f"M {fmt(left)} {fmt(cy2)} A {fmt(rx)} {fmt(ry)} 0 0 1 {fmt(right)} {fmt(cy2)}"
    return (
        f"<g {common}>\n"
        f'  <path class="shape-bg" d="{background}" fill="{fill}" opacity="{opacity}" stroke="none"/>\n'
        f'  <path class="shape-back" d="{back}" fill="none" stroke-width="{stroke_width}" stroke-dasharray="6 6"/>\n'
        + (f"  {top}\n" if top else "")
        + f'  <path class="shape-front" d="{front}" fill="none" stroke-width="{stroke_width}"/>\n'
        f"</g>"
    )


def render_svg(data: dict) -> str:
    elements = data.get("elements")
    if not isinstance(elements, list):
        raise ValueError("数据必须包含 elements 数组")
    output: list[str] = []
    for index, item in enumerate(elements):
        if not isinstance(item, dict) or item.get("tag") not in ALLOWED_TAGS:
            raise ValueError(f"elements[{index}] 的 tag 无效")
        tag = item["tag"]
        if tag == "solid":
            output.append(render_solid(item, index))
            continue
        attrs = dict(item.get("attrs") or {})
        kind = str(item.get("kind") or tag)
        if tag == "text":
            attrs.setdefault("fill", "#000000")
            attrs.setdefault("stroke", "none")
        else:
            attrs.setdefault("stroke", "#000000")
            attrs.setdefault("fill", "none")
            attrs.setdefault("stroke-width", 3)
        if kind in {"点", "point"}:
            attrs["stroke"] = "#000000"
            attrs["fill"] = "#000000"
        if kind in {"阴影", "shade"}:
            attrs.setdefault("opacity", 0.42)
            if attrs.get("fill") in {None, "none", "transparent"}:
                attrs["fill"] = "#d9d9d9"
        attrs_text = " ".join(
            f'{key}="{esc(value)}"' for key, value in attrs.items() if key in ALLOWED_ATTRS
        )
        kind = esc(kind)
        group = f' data-group="{esc(item["group"])}"' if item.get("group") else ""
        content = esc(item.get("text", "")) if tag == "text" else ""
        output.append(
            f'<{tag} class="object" data-kind="{kind}" data-id="object-{index}"{group} {attrs_text}>{content}</{tag}>'
        )
    return "\n".join(output)


def generate(data_path: Path, output_path: Path) -> None:
    data = json.loads(data_path.read_text(encoding="utf-8"))
    source = TEMPLATE.read_text(encoding="utf-8")
    if source.count(INSERT_MARKER) != 1:
        raise RuntimeError("模板缺少唯一 SVG 插入位置")
    source = source.replace(INSERT_MARKER, render_svg(data))
    output_path.write_text(source, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    generate(args.data, args.output)
    print(f"已生成: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
