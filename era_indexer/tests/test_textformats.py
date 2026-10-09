from career_history.textformats import captions_to_markdown, eml_to_markdown

SRT = """1
00:00:01,220 --> 00:00:04,760
and then draw from the DA's experiences.

2
00:00:05,400 --> 00:00:08,120
So for this round, <i>Think Global</i>,

3
00:00:05,400 --> 00:00:08,120
So for this round, <i>Think Global</i>,

4
00:01:10,000 --> 00:01:12,000
Next topic &amp; wrap-up.
"""

VTT = """WEBVTT

00:00.500 --> 00:02.000
Hello team.
"""


def test_srt_merges_cues_into_timestamped_paragraphs():
    md = captions_to_markdown(SRT, "SCDS Alignment Discussion")
    assert md.splitlines()[0] == "# Transcript: SCDS Alignment Discussion"
    assert "[00:00:01] and then draw from the DA's experiences. So for this round, Think Global," in md
    assert "[00:01:10] Next topic & wrap-up." in md
    assert "-->" not in md
    assert md.count("Think Global") == 1


def test_vtt_header_and_short_timestamps():
    md = captions_to_markdown(VTT, "x")
    assert "[00:00:00] Hello team." in md
    assert "WEBVTT" not in md


EML = b"""From: Tan Bin Ru <binru.tan@example.com>
To: Eugene <eugene@example.com>
Date: Mon, 07 Sep 2026 12:31:11 +0000
Subject: RE: SCDS Leadership Forum H2-2026 Draft Topics
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="B"

--B
Content-Type: text/html; charset=utf-8

<html><style>p{color:red}</style><body><p>Hi Eugene,</p><p>Draft topics attached.</p></body></html>
--B
Content-Type: application/pdf
Content-Disposition: attachment; filename="Topics.pdf"

JVBERi0=
--B
Content-Type: image/png
Content-Disposition: attachment; filename="image001.png"

iVBORw0=
--B--
"""


def test_eml_headers_html_body_and_attachments():
    md = eml_to_markdown(EML, "fallback")
    assert md.startswith("# Email: RE: SCDS Leadership Forum H2-2026 Draft Topics")
    assert "**From:** Tan Bin Ru <binru.tan@example.com>" in md
    assert "Hi Eugene," in md and "Draft topics attached." in md
    assert "color:red" not in md
    assert "**Attachments:** Topics.pdf" in md
    assert "image001.png" not in md
