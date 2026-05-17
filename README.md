# Google Slides MCP

An MCP server that converts a PDF report into a Google Slides presentation.

The single tool `pdf_to_slides(pdf_path, title=None, theme="warm", images=True)`:
1. Extracts text from the PDF with `pypdf`
2. Asks Claude to structure it into slide titles + bullets (following the PDF's actual sections, not inventing them), and to suggest a stock-photo query for slides where an image genuinely helps
3. Creates the deck via the Google Slides API, applies a visual theme, and returns the URL
4. In a second, best-effort pass, sources a relevant photo from Pexels for those slides and lays it out beside the bullets

### Themes

Pass `theme` to style the deck (background colour, title/body fonts and colours, and an accent bar under each title):

| `theme` | Look |
|---|---|
| `warm` *(default)* | Cream background, brown titles, terracotta accent |
| `corporate` | White background, navy titles, blue accent |
| `dark` | Charcoal background, white titles, teal accent |
| `minimal` | White background, black titles, thin black rule |

Unknown values fall back to `warm`. Ask the bot e.g. *"…using the dark theme."*

### Images

Slides are illustrated with stock photos from [Pexels](https://www.pexels.com/api/) (free, license-clean for reuse). Claude decides per section whether a photo adds value — data/summary slides stay text-only — so the deck doesn't fill up with generic filler.

This needs a free Pexels API key in `.env` as `PEXELS_API_KEY`. **It's optional:** with no key (or `images=False`), the deck is still produced, just text-only. Image sourcing runs as a separate pass, so a failed photo lookup never breaks the deck.

## Setup

1. **Install dependencies**

   ```powershell
   pip install -r requirements.txt
   ```

2. **Enable Google APIs** — in the same Google Cloud project you used for Gmail, enable:
   - Google Slides API
   - Google Drive API

   (Console → APIs & Services → Library → search and enable each.)

3. **Copy OAuth credentials**

   Copy `credentials.json` from the `basic_chatbot` project into this folder. It's tied to your Cloud project, not to specific APIs, so the same file works.

4. **Set up `.env`**

   Create a `.env` file in this folder with:

   ```
   ANTHROPIC_API_KEY=your-key-here
   # Optional — enables slide images. Free key: https://www.pexels.com/api/
   PEXELS_API_KEY=your-key-here
   ```

   `PEXELS_API_KEY` is optional; without it, decks are generated text-only.
   `.env` is gitignored — keep your keys in it, not in any committed file.

5. **One-time auth**

   ```powershell
   python slides_mcp_server.py auth
   ```

   A browser opens; grant the Slides + Drive scopes. Token is cached in `token.json`.

## Usage

The server speaks MCP over stdio. To wire it into the existing chatbot, add a second entry to the `MultiServerMCPClient` config in `chatbot_langgraph.py`:

```python
client = MultiServerMCPClient({
    "gmail": {
        "command": sys.executable,
        "args": [GMAIL_SERVER_PATH],
        "transport": "stdio",
    },
    "google_slides": {
        "command": sys.executable,
        "args": [SLIDES_SERVER_PATH],
        "transport": "stdio",
    },
})
```

Then ask the bot something like: *"Turn the report at C:\path\to\report.pdf into a slide deck."*
