"""Google Slides MCP server — pdf_to_slides tool over stdio.

One-time setup: run `python slides_mcp_server.py auth` to complete the
OAuth flow. The browser opens, you grant Slides + Drive scopes, and the
refresh token is cached in token.json next to this file. After that,
the chatbot launches this script as a stdio subprocess.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP
from pypdf import PdfReader

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/presentations",
    "https://www.googleapis.com/auth/drive.file",
]
HERE = Path(__file__).parent
CREDENTIALS_FILE = HERE / "credentials.json"
TOKEN_FILE = HERE / "token.json"

MODEL = "claude-haiku-4-5-20251001"
MAX_PDF_CHARS = 150_000

EMU_PER_INCH = 914400


def _rgb(hex_color: str) -> dict:
    """#RRGGBB -> Slides API rgbColor (0-1 floats)."""
    h = hex_color.lstrip("#")
    return {
        "red": int(h[0:2], 16) / 255,
        "green": int(h[2:4], 16) / 255,
        "blue": int(h[4:6], 16) / 255,
    }


# Each theme: slide background, title/body text colour + font, and an
# accent bar drawn under the title on every slide.
THEMES = {
    "warm": {
        "background": "#FBF7F0",
        "title_color": "#4A3528",
        "body_color": "#6B5D4F",
        "accent_color": "#C46A4A",
        "title_font": "Lora",
        "body_font": "PT Sans",
    },
    "corporate": {
        "background": "#FFFFFF",
        "title_color": "#1A2B4A",
        "body_color": "#333333",
        "accent_color": "#2E6FB5",
        "title_font": "Arial",
        "body_font": "Arial",
    },
    "dark": {
        "background": "#1E1E24",
        "title_color": "#F5F5F5",
        "body_color": "#C8C8C8",
        "accent_color": "#2DD4BF",
        "title_font": "Roboto",
        "body_font": "Roboto",
    },
    "minimal": {
        "background": "#FFFFFF",
        "title_color": "#000000",
        "body_color": "#212121",
        "accent_color": "#000000",
        "title_font": "Arial",
        "body_font": "Arial",
    },
}
DEFAULT_THEME = "warm"

STRUCTURE_PROMPT = """You will structure a PDF report into slide content.

Rules:
- Follow the PDF's actual sections — do not invent topics that aren't in it.
- Each slide: a short title (max 8 words) and 3-5 tight bullets (max 15 words each).
- Strip filler; keep substance. Bullets should read as presentation bullets, not full sentences.
- Aim for 5-15 content slides depending on report length and density.
- Return ONLY valid JSON, no commentary, no markdown fences.

JSON shape:
{
  "title": "Overall presentation title",
  "sections": [
    {"title": "Section title", "bullets": ["Bullet 1", "Bullet 2", "Bullet 3"]}
  ]
}

PDF content:
"""


def get_slides_service():
    creds: Credentials | None = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
    return build("slides", "v1", credentials=creds)


def extract_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def structure_pdf(pdf_text: str, override_title: str | None) -> dict:
    client = Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        messages=[{"role": "user", "content": STRUCTURE_PROMPT + pdf_text}],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    outline = json.loads(raw)
    if override_title:
        outline["title"] = override_title
    return outline


def _background_request(slide_id: str, theme: dict) -> dict:
    return {
        "updatePageProperties": {
            "objectId": slide_id,
            "pageProperties": {
                "pageBackgroundFill": {
                    "solidFill": {"color": {"rgbColor": _rgb(theme["background"])}}
                }
            },
            "fields": "pageBackgroundFill.solidFill.color",
        }
    }


def _text_style_request(object_id: str, color_hex: str, font: str, size_pt: int,
                        bold: bool) -> dict:
    return {
        "updateTextStyle": {
            "objectId": object_id,
            "textRange": {"type": "ALL"},
            "style": {
                "foregroundColor": {"opaqueColor": {"rgbColor": _rgb(color_hex)}},
                "fontFamily": font,
                "bold": bold,
                "fontSize": {"magnitude": size_pt, "unit": "PT"},
            },
            "fields": "foregroundColor,fontFamily,bold,fontSize",
        }
    }


def _accent_bar_requests(slide_id: str, bar_id: str, theme: dict,
                         centered: bool) -> list[dict]:
    """A thin horizontal rule in the accent colour, under the title."""
    width_in = 4.0 if centered else 8.0
    x_in = (10.0 - width_in) / 2 if centered else 0.6
    y_in = 2.7 if centered else 1.25
    return [
        {
            "createShape": {
                "objectId": bar_id,
                "shapeType": "RECTANGLE",
                "elementProperties": {
                    "pageObjectId": slide_id,
                    "size": {
                        "width": {"magnitude": width_in * EMU_PER_INCH, "unit": "EMU"},
                        "height": {"magnitude": 0.05 * EMU_PER_INCH, "unit": "EMU"},
                    },
                    "transform": {
                        "scaleX": 1,
                        "scaleY": 1,
                        "translateX": x_in * EMU_PER_INCH,
                        "translateY": y_in * EMU_PER_INCH,
                        "unit": "EMU",
                    },
                },
            }
        },
        {
            "updateShapeProperties": {
                "objectId": bar_id,
                "shapeProperties": {
                    "shapeBackgroundFill": {
                        "solidFill": {"color": {"rgbColor": _rgb(theme["accent_color"])}}
                    },
                    "outline": {"propertyState": "NOT_RENDERED"},
                },
                "fields": "shapeBackgroundFill.solidFill.color,outline.propertyState",
            }
        },
    ]


def build_presentation(slides_service, outline: dict,
                       theme_name: str = DEFAULT_THEME) -> str:
    pres = slides_service.presentations().create(
        body={"title": outline["title"]}
    ).execute()
    pres_id = pres["presentationId"]
    default_slide_id = pres["slides"][0]["objectId"]
    theme = THEMES.get(theme_name, THEMES[DEFAULT_THEME])

    requests: list[dict] = [{"deleteObject": {"objectId": default_slide_id}}]

    centered_title_id = "centered_title"
    requests.append({
        "createSlide": {
            "objectId": "title_slide",
            "insertionIndex": 0,
            "slideLayoutReference": {"predefinedLayout": "TITLE"},
            "placeholderIdMappings": [{
                "layoutPlaceholder": {"type": "CENTERED_TITLE", "index": 0},
                "objectId": centered_title_id,
            }],
        }
    })
    requests.append({"insertText": {"objectId": centered_title_id, "text": outline["title"]}})
    requests.append(_background_request("title_slide", theme))
    requests.append(_text_style_request(
        centered_title_id, theme["title_color"], theme["title_font"], 40, bold=True))
    requests.extend(_accent_bar_requests(
        "title_slide", "title_bar", theme, centered=True))

    for i, section in enumerate(outline["sections"]):
        title_id = f"title_{i}"
        body_id = f"body_{i}"
        requests.append({
            "createSlide": {
                "objectId": f"slide_{i}",
                "insertionIndex": i + 1,
                "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
                "placeholderIdMappings": [
                    {"layoutPlaceholder": {"type": "TITLE", "index": 0}, "objectId": title_id},
                    {"layoutPlaceholder": {"type": "BODY", "index": 0}, "objectId": body_id},
                ],
            }
        })
        requests.append({"insertText": {"objectId": title_id, "text": section["title"]}})
        bullets_text = "\n".join(section["bullets"])
        requests.append({"insertText": {"objectId": body_id, "text": bullets_text}})
        requests.append({
            "createParagraphBullets": {
                "objectId": body_id,
                "textRange": {"type": "ALL"},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE",
            }
        })
        requests.append(_background_request(f"slide_{i}", theme))
        requests.append(_text_style_request(
            title_id, theme["title_color"], theme["title_font"], 26, bold=True))
        requests.append(_text_style_request(
            body_id, theme["body_color"], theme["body_font"], 14, bold=False))
        requests.extend(_accent_bar_requests(
            f"slide_{i}", f"bar_{i}", theme, centered=False))

    slides_service.presentations().batchUpdate(
        presentationId=pres_id, body={"requests": requests}
    ).execute()

    return f"https://docs.google.com/presentation/d/{pres_id}/edit"


mcp = FastMCP("google_slides")


@mcp.tool()
def pdf_to_slides(pdf_path: str, title: str | None = None,
                  theme: str = DEFAULT_THEME) -> str:
    """Convert a PDF report into a styled Google Slides presentation.

    Args:
        pdf_path: Absolute path to the PDF file on the local machine.
        title: Optional override for the presentation title. If omitted,
            the title is inferred from the PDF content.
        theme: Visual theme for the deck. One of "warm" (cream/terracotta,
            default), "corporate" (white/navy/blue), "dark" (charcoal/teal),
            or "minimal" (black & white). Unknown values fall back to "warm".

    Returns a message with the URL of the created presentation.
    """
    if not TOKEN_FILE.exists():
        return (
            "Error: Google Slides not authorized yet. "
            "Run `python slides_mcp_server.py auth` once, then retry."
        )
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "Error: ANTHROPIC_API_KEY not set. Add it to .env."

    pdf = Path(pdf_path)
    if not pdf.exists():
        return f"Error: PDF not found at {pdf_path}"

    text = extract_pdf_text(pdf)
    if not text.strip():
        return "Error: no extractable text in PDF (scanned image?)."
    if len(text) > MAX_PDF_CHARS:
        text = text[:MAX_PDF_CHARS]

    try:
        outline = structure_pdf(text, title)
    except json.JSONDecodeError as e:
        return f"Error: LLM did not return valid JSON ({e})."

    theme_name = theme if theme in THEMES else DEFAULT_THEME
    service = get_slides_service()
    url = build_presentation(service, outline, theme_name)
    return (
        f"Created '{theme_name}' presentation with "
        f"{len(outline['sections'])} sections: {url}"
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        get_slides_service()
        print(f"Auth complete. Token saved to {TOKEN_FILE}")
    else:
        mcp.run()
