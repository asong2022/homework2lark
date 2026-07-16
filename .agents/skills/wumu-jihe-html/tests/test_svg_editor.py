import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
GENERATOR = ROOT / "scripts" / "generate_svg_editor.py"
TEMPLATE = ROOT / "assets" / "svg-editor-template.html"
SKILL = ROOT / "SKILL.md"
RULES = ROOT / "references" / "geometry-rules.md"


def load_generator():
    spec = importlib.util.spec_from_file_location("svg_editor_generator", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def data():
    return {
        "elements": [
            {
                "tag": "polygon",
                "kind": "三角形",
                "group": "triangle-1",
                "attrs": {"points": "200,160 600,160 400,480", "fill": "none"},
            },
            {
                "tag": "text",
                "kind": "标签",
                "group": "triangle-1",
                "attrs": {"x": 180, "y": 145, "fill": "#000000", "font-size": 24},
                "text": "A",
            },
            {"tag": "circle", "kind": "点", "attrs": {"cx": 200, "cy": 160, "r": 5}},
            {"tag": "ellipse", "kind": "阴影", "attrs": {"cx": 400, "cy": 320, "rx": 60, "ry": 40}},
        ]
    }


class SvgEditorTests(unittest.TestCase):
    def test_generates_editor_from_elements_only(self):
        generator = load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            source_path, output_path = Path(tmp) / "d.json", Path(tmp) / "d.html"
            source_path.write_text(json.dumps(data(), ensure_ascii=False), encoding="utf-8")
            generator.generate(source_path, output_path)
            source = output_path.read_text(encoding="utf-8")
        self.assertIn('data-kind="三角形"', source)
        self.assertIn('data-group="triangle-1"', source)
        self.assertIn(">A</text>", source)
        self.assertNotIn("<!-- SVG_OBJECTS -->", source)
        self.assertIn('data-kind="点"', source)
        self.assertIn('fill="#000000"', source)
        self.assertIn('data-kind="阴影"', source)
        self.assertIn('fill="#d9d9d9"', source)
        self.assertIn('opacity="0.42"', source)

    def test_rejects_legacy_or_invalid_data(self):
        generator = load_generator()
        with tempfile.TemporaryDirectory() as tmp:
            source_path, output_path = Path(tmp) / "d.json", Path(tmp) / "d.html"
            source_path.write_text(json.dumps({"points": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "elements"):
                generator.generate(source_path, output_path)

    def test_generates_semantic_cylinder_and_cone(self):
        generator = load_generator()
        source = generator.render_svg(
            {
                "elements": [
                    {
                        "tag": "solid",
                        "kind": "圆柱",
                        "group": "cyl-1",
                        "attrs": {"cx": 240, "cy1": 100, "cy2": 420, "rx": 80, "ry": 22},
                    },
                    {
                        "tag": "solid",
                        "kind": "cone",
                        "attrs": {"cx": 600, "cy1": 90, "cy2": 430, "rx": 100},
                    },
                ]
            }
        )
        self.assertIn('<g class="object cylinder"', source)
        self.assertIn('data-kind="圆柱"', source)
        self.assertIn('data-group="cyl-1"', source)
        self.assertIn('data-rx="80" data-ry="22"', source)
        self.assertIn('class="shape-back"', source)
        self.assertIn('stroke-dasharray="6 6"', source)
        self.assertIn('<g class="object cone"', source)
        self.assertNotIn("<class=", source)
        self.assertIn('data-kind="圆锥"', source)
        self.assertIn('data-rx="100" data-ry="30"', source)
        self.assertEqual(source.count('class="shape-bg"'), 2)

    def test_generates_semantic_cube_and_cuboid(self):
        generator = load_generator()
        source = generator.render_svg(
            {
                "elements": [
                    {
                        "tag": "solid",
                        "kind": "cube",
                        "group": "cube-1",
                        "attrs": {"cx": 240, "cy": 260, "w": 120, "ox": 42, "oy": -42},
                    },
                    {
                        "tag": "solid",
                        "kind": "长方体",
                        "attrs": {"cx": 620, "cy": 320, "w": 220, "h": 140, "ox": -70, "oy": -45},
                    },
                ]
            }
        )
        self.assertIn('<g class="object cube"', source)
        self.assertIn('data-kind="正方体"', source)
        self.assertIn('data-group="cube-1"', source)
        self.assertIn('data-w="120" data-h="120"', source)
        self.assertIn('<g class="object cuboid"', source)
        self.assertIn('data-kind="长方体"', source)
        self.assertIn('data-w="220" data-h="140"', source)
        self.assertEqual(source.count('class="shape-back"'), 2)

    def test_rejects_invalid_solid(self):
        generator = load_generator()
        with self.assertRaisesRegex(ValueError, "solid kind"):
            generator.render_svg({"elements": [{"tag": "solid", "kind": "球", "attrs": {}}]})
        with self.assertRaisesRegex(ValueError, "rx"):
            generator.render_svg(
                {
                    "elements": [
                        {
                            "tag": "solid",
                            "kind": "圆柱",
                            "attrs": {"cx": 1, "cy1": 2, "cy2": 3, "rx": 2},
                        }
                    ]
                }
            )
        with self.assertRaisesRegex(ValueError, "h"):
            generator.render_svg(
                {
                    "elements": [
                        {"tag": "solid", "kind": "长方体", "attrs": {"cx": 1, "cy": 2, "w": 20}}
                    ]
                }
            )

    def test_template_owns_editor_features(self):
        source = TEMPLATE.read_text(encoding="utf-8")
        for text in ["五木几何", "基础工具", "尺规与图形"]:
            self.assertIn(text, source)
        self.assertIn('id="floating"', source)
        self.assertIn('id="previewLayer"', source)
        self.assertIn('id="handleLayer"', source)
        self.assertIn("function previewAt(p)", source)
        self.assertIn("function showHandles(el)", source)
        self.assertIn("function adjustHandle(p)", source)
        self.assertIn("function setRotationCenter(el, cx, cy)", source)
        self.assertIn('data-role="rotation-center"', source)
        self.assertIn('data-role="rotation-mask"', source)
        self.assertIn("user-select:none", source)
        self.assertIn("width:max-content", source)
        self.assertIn("max-width:calc(100vw - 24px)", source)
        self.assertGreaterEqual(
            source.count('<button class="float-btn"')
            + source.count('<button class="float-btn danger"'),
            6,
        )
        self.assertGreaterEqual(source.count('<svg viewBox="0 0 24 24">'), 5)
        for control in [
            'id="rotateBtn"',
            'id="fsBtn"',
            'id="exportBtn"',
            'id="bringFront"',
            'id="sendBack"',
        ]:
            self.assertIn(control, source)
        for feature in [
            "function applyViewport()",
            "function getSnapPoint",
            "function openInlineEdit",
            "tool === 'pen'",
            "tool === 'eraser'",
        ]:
            self.assertIn(feature, source)
        for feature in [
            'data-tool="cylinder"',
            'data-tool="cone"',
            'data-tool="cube"',
            'data-tool="cuboid"',
            'data-kind="圆柱"',
            'data-kind="圆锥"',
        ]:
            self.assertIn(feature, source)
        self.assertIn(
            "['圆柱', '圆锥', '正方体', '长方体'].includes(selected.dataset.kind)", source
        )
        self.assertIn("移动鼠标识别封闭区域", source)
        self.assertIn("已识别封闭区域，点击确认阴影", source)
        self.assertIn("el.setAttribute('fill', 'url(#hatch-pattern)')", source)
        self.assertIn("shadePulse", source)
        self.assertIn("function groupMembers(el)", source)
        self.assertIn('id="toggleLabels"', source)
        self.assertIn('id="togglePoints"', source)
        self.assertIn('id="redo"', source)
        self.assertIn('id="clearAll"', source)
        self.assertIn("font-size:16px", source)
        self.assertIn("e.key === 'Escape'", source)
        self.assertIn("e.metaKey || e.ctrlKey", source)
        self.assertIn('<aside class="toolbox"', source)
        self.assertIn(".topbar{", source)
        self.assertNotIn('id="clear"', source)
        self.assertNotIn('id="export"', source)
        self.assertGreaterEqual(source.count('<svg class="icon"'), 15)
        for value in ["txyjh.com", "/api/share", "window.name", "location.replace", "上传"]:
            self.assertNotIn(value, source)

    def test_skill_is_minimal(self):
        source = SKILL.read_text(encoding="utf-8")
        self.assertIn("## 核心原则", source)
        self.assertIn("## 工作流", source)
        self.assertIn("不要预读或解析模板源码", source)
        self.assertIn("设置相同 `group`", source)
        self.assertIn('`tag: "solid"`', source)
        self.assertIn("正方体、长方体", source)
        self.assertIn("若本地预览可用", source)
        self.assertIn("至少截图核对一次", source)
        self.assertIn("不超过 10 个汉字", source)
        self.assertIn("<摘要>-YYMMDD-HHMMSS.html", source)
        self.assertIn("等腰梯形内的两半圆-260713-191533.html", source)
        for heading in ["默认交付契约", "图形选择", "常见错误", "示例"]:
            self.assertNotIn(heading, source)
        for legacy in ["canvas", "viewport", "customShapes", "inkPaths", "indepAuxLines", "txyjh"]:
            self.assertNotIn(legacy, source)

    def test_solid_bottom_visibility_rule(self):
        source = RULES.read_text(encoding="utf-8")
        self.assertIn("椭圆底面必须闭合表达", source)
        self.assertIn("后半弧用虚线、前半弧用实线", source)
        self.assertIn("填充层先画，底面轮廓后画", source)
        self.assertIn('"tag":"solid"', source)
        self.assertIn("图片中底弧断裂或缺失时按结构补全", source)


if __name__ == "__main__":
    unittest.main()
