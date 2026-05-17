# Google Slides MCP

An MCP server that converts a PDF report into a Google Slides presentation.

The single tool `pdf_to_slides(pdf_path, title=None, theme="warm")`:
1. Extracts text from the PDF with `pypdf`
2. Asks Claude to structure it into slide titles + bullets (following the PDF's actual sections, not inventing them)
3. Creates the deck via the Google Slides API, applies a visual theme, and returns the URL

### Themes

Pass `theme` to style the deck (background colour, title/body fonts and colours, and an accent bar under each title):

| `theme` | Look |
|---|---|
| `warm` *(default)* | Cream background, brown titles, terracotta accent |
| `corporate` | White background, navy titles, blue accent |
| `dark` | Charcoal background, white titles, teal accent |
| `minimal` | White background, black titles, thin black rule |

Unknown values fall back to `warm`. Ask the bot e.g. *"…using the dark theme."*

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

   ```powershell
   Copy-Item .env.example .env
   ```

   Then put your `ANTHROPIC_API_KEY` in `.env`.

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
