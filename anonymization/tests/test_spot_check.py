"""Manual spot-check affordance: generates a side-by-side HTML report."""

import os
import re

import pytest

from pipeline import anonymize_text

REPORT_OUTPUT = os.path.join(os.path.dirname(__file__), "spot_check_report.html")


def _generate_html_report(pairs: list[tuple[str, str, str]]) -> str:
    """Generate an HTML report with before/after pairs."""
    rows = ""
    for filename, original, anonymized in pairs:
        # Highlight placeholders in anonymized text
        highlighted = re.sub(
            r"(\[\w+_\d+\])",
            r'<span style="background:#ffd700;padding:2px 4px;border-radius:3px">\1</span>',
            anonymized,
        )
        rows += f"""
        <tr>
            <td colspan="2" style="background:#f0f0f0;font-weight:bold;padding:8px">{filename}</td>
        </tr>
        <tr>
            <td style="padding:12px;white-space:pre-wrap;border-right:1px solid #ddd;width:50%">{original}</td>
            <td style="padding:12px;white-space:pre-wrap;width:50%">{highlighted}</td>
        </tr>
        """

    return f"""<!DOCTYPE html>
<html>
<head><title>Anonymization Spot Check</title></head>
<body style="font-family:monospace;margin:20px">
<h1>Anonymization Spot-Check Report</h1>
<table style="width:100%;border-collapse:collapse;border:1px solid #ddd">
<tr><th style="padding:8px;border:1px solid #ddd">Original</th><th style="padding:8px;border:1px solid #ddd">Anonymized</th></tr>
{rows}
</table>
<h2>Reviewer Checklist</h2>
<ul>
<li>☐ No person names visible in anonymized column</li>
<li>☐ No phone numbers visible in anonymized column</li>
<li>☐ No email addresses visible in anonymized column</li>
<li>☐ No account/order numbers visible in anonymized column</li>
<li>☐ No brand names visible in anonymized column</li>
<li>☐ Conversational meaning is preserved</li>
<li>☐ Turn structure (Cliente/Agente) is intact</li>
</ul>
<p><strong>Reviewed by:</strong> _________________ <strong>Date:</strong> _________________</p>
</body>
</html>"""


class TestSpotCheckReport:
    def test_generate_spot_check_report(self, load_fixture):
        """Generate the HTML report for human review. Always passes — it's a tool, not a check."""
        fixtures = [
            "conversation_with_pii.txt",
            "conversation_edge_cases.txt",
            "conversation_no_pii.txt",
        ]

        pairs = []
        for name in fixtures:
            original = load_fixture(name)
            anonymized = anonymize_text(original)
            pairs.append((name, original, anonymized))

        html = _generate_html_report(pairs)
        with open(REPORT_OUTPUT, "w", encoding="utf-8") as f:
            f.write(html)

        assert os.path.exists(REPORT_OUTPUT)
        print(f"\n✓ Spot-check report written to: {REPORT_OUTPUT}")
