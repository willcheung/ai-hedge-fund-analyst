import io
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.check_design_system import check_tree, main


class DesignSystemCheckTests(unittest.TestCase):
    def fixture(self, files: dict[str, str]) -> Path:
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for name, contents in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        return root

    def test_raw_colors_fail_in_modular_css(self):
        root = self.fixture({
            "src/feature.css": "\n".join((
                ".a { color: #fff; }",
                ".b { color: rgb(1 2 3); }",
                ".c { color: rgba(1, 2, 3, .5); }",
                ".d { color: hsl(10 20% 30%); }",
                ".e { color: hsla(10, 20%, 30%, .5); }",
            )),
        })

        findings = check_tree(root)

        self.assertEqual(len(findings), 5)
        self.assertEqual({finding.path for finding in findings}, {"src/feature.css"})
        self.assertEqual([finding.line for finding in findings], [1, 2, 3, 4, 5])

    def test_raw_color_like_text_outside_css_declaration_values_passes(self):
        root = self.fixture({
            "src/feature.css": "\n".join((
                "/* #fff rgb(1 2 3) */",
                ".copy::before { content: \"#fff rgba(1, 2, 3, .5)\"; }",
                "#feed { color: var(--markets-primary); }",
                ".icon { mask-image: url(#fff); }",
            )),
        })

        self.assertEqual(check_tree(root), [])

    def test_css_custom_properties_pass(self):
        root = self.fixture({
            "src/feature.css": (
                ".card { color: var(--markets-primary); "
                "background: var(--markets-surface); "
                "border-color: var(--markets-border); }"
            ),
        })

        self.assertEqual(check_tree(root), [])

    def test_palette_owner_theme_css_is_exempt(self):
        root = self.fixture({
            "src/theme.css": ":root { --markets-primary: #2457c5; --shadow: rgb(0 0 0 / 20%); }",
        })

        self.assertEqual(check_tree(root), [])

    def test_legacy_styles_css_is_grandfathered(self):
        root = self.fixture({
            "src/styles.css": ".legacy { color: #fff; background: rgba(0, 0, 0, .5); }",
        })

        self.assertEqual(check_tree(root), [])

    def test_literal_inline_visual_styles_fail(self):
        root = self.fixture({
            "src/Feature.tsx": "\n".join((
                "export const Light = () => <span style={{ color: '#fff' }} />",
                "export const Alert = () => <span style={{ background: 'red' }} />",
                "export const Surface = () => <span style={{ backgroundColor: '#fff' }} />",
                "export const Border = () => <span style={{ borderColor: condition ? '#fff' : '#000' }} />",
                "export const Outline = () => <span style={{ outlineColor: '#abc' }} />",
            )),
        })

        findings = check_tree(root)

        self.assertEqual(len(findings), 5)
        self.assertEqual([finding.line for finding in findings], [1, 2, 3, 4, 5])
        self.assertTrue(all(finding.rule == "literal-inline-visual-style" for finding in findings))

    def test_quoted_inline_visual_style_keys_fail(self):
        properties = ("color", "background", "backgroundColor", "borderColor", "outlineColor")
        lines = [
            f"export const Single{index} = () => <span style={{{{ '{prop}': '#fff' }}}} />"
            for index, prop in enumerate(properties)
        ] + [
            f'export const Double{index} = () => <span style={{{{ "{prop}": "#fff" }}}} />'
            for index, prop in enumerate(properties)
        ]
        root = self.fixture({"src/Feature.tsx": "\n".join(lines)})

        findings = check_tree(root)

        self.assertEqual(len(findings), 10)
        self.assertEqual([finding.line for finding in findings], list(range(1, 11)))
        self.assertTrue(all(finding.rule == "literal-inline-visual-style" for finding in findings))

    def test_computed_quoted_inline_visual_style_keys_fail(self):
        root = self.fixture({
            "src/Feature.tsx": "\n".join((
                "export const Light = () => <span style={{ ['color']: '#fff' }} />",
                "",
                'export const Surface = () => <span style={{ ["backgroundColor"]: "red" }} />',
            )),
        })

        findings = check_tree(root)

        self.assertEqual([finding.line for finding in findings], [1, 3])
        self.assertTrue(all(finding.rule == "literal-inline-visual-style" for finding in findings))

    def test_parenthesized_and_conditional_named_color_values_fail(self):
        root = self.fixture({
            "src/Feature.tsx": "\n".join((
                "export const Parenthesized = () => <span style={{ color: ('red') }} />",
                "",
                "export const Conditional = ({ ok }) => <span style={{ background: ok ? 'red' : 'blue' }} />",
            )),
        })

        findings = check_tree(root)

        self.assertEqual([finding.line for finding in findings], [1, 3])
        self.assertTrue(all(finding.rule == "literal-inline-visual-style" for finding in findings))

    def test_conditional_dynamic_color_helper_calls_pass(self):
        root = self.fixture({
            "src/Feature.tsx": (
                "export const Feature = ({ ok }) => <span style={{ "
                "color: ok ? categoryColor('ai') : categoryColor('macro') "
                "}} />"
            ),
        })

        self.assertEqual(check_tree(root), [])

    def test_conditional_and_logical_named_color_operands_fail(self):
        root = self.fixture({
            "src/Feature.tsx": "\n".join((
                "export const Conditional = ({ ok }) => <i style={{ color: ok ? 'red' : 'blue' }} />",
                "export const Or = ({ override }) => <i style={{ color: override || 'red' }} />",
                "export const And = ({ enabled }) => <i style={{ color: enabled && 'red' }} />",
                "export const Nullish = ({ override }) => <i style={{ color: override ?? 'red' }} />",
            )),
        })

        findings = check_tree(root)

        self.assertEqual([finding.line for finding in findings], [1, 2, 3, 4])
        self.assertTrue(all(finding.rule == "literal-inline-visual-style" for finding in findings))

    def test_style_like_text_outside_executable_jsx_passes(self):
        root = self.fixture({
            "src/Feature.tsx": "\n".join((
                "// <span style={{ color: '#fff' }} />",
                "/* <span style={{ background: 'red' }} /> */",
                "const quoted = \"<span style={{ borderColor: '#fff' }} />\"",
                "const template = `<span style={{ outlineColor: 'red' }} />`",
                "export const Feature = () => <span>safe</span>",
            )),
        })

        self.assertEqual(check_tree(root), [])

    def test_dynamic_geometry_and_data_derived_colors_pass(self):
        root = self.fixture({
            "src/Feature.tsx": "\n".join((
                "export const Bar = () => <span style={{ height }} />",
                "export const Node = () => <span style={{ left: 16, top: positions[id].y }} />",
                "export const Category = () => <i style={{ background: categoryColor(category) }} />",
                "const chart = { backgroundColor: '#fff', borderColor: palette.border }",
            )),
        })

        self.assertEqual(check_tree(root), [])

    def test_cli_diagnostics_include_only_location_and_rule(self):
        root = self.fixture({
            "src/Feature.tsx": "\n\nexport const Feature = () => <span style={{ outlineColor: '#abc' }} />\n",
        })
        output = io.StringIO()

        with redirect_stdout(output):
            status = main(root)

        diagnostic = output.getvalue()
        self.assertEqual(status, 1)
        self.assertIn("src/Feature.tsx:3", diagnostic)
        self.assertIn("literal-inline-visual-style", diagnostic)
        self.assertNotIn("#abc", diagnostic)
        self.assertNotIn("export const", diagnostic)


if __name__ == "__main__":
    unittest.main()
