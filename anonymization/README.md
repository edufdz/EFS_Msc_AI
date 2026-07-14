# Anonymization Platform

A platform for automatically anonymizing customer-support conversation transcripts. Upload TXT or JSON files and get back clean, PII-free text with all personal data replaced by typed placeholders.

## Supported JSON Formats

The platform auto-detects common conversation JSON structures:

```json
// Array of messages
[{"role": "cliente", "content": "Hola..."}, {"role": "agente", "content": "..."}]

// Object with messages key
{"messages": [{"role": "...", "content": "..."}]}

// Also supports keys: "conversation", "turns", "data", "chat"
// Message fields: "content", "text", "message", "body"
// Role fields: "role", "sender", "from"
```

---

## Prerequisites

- Python 3.10+
- Node.js 18+
- npm

---

## Setup

### Backend

```bash
cd anonymization/backend

# Create and activate virtual environment (first time only)
python3 -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Download the Spanish NER model (first time only)
python -m spacy download es_core_news_lg
```

> Every time you open a new terminal, activate the venv first:
> ```bash
> source ~/Desktop/dos-agent-debugger/MSC_AI_Project/anonymization/backend/venv/bin/activate
> ```

### Frontend

```bash
cd anonymization/frontend

# Install Node dependencies
npm install
```

---

## Running

### 1. Start the backend (port 8000)

```bash
cd anonymization/backend
source venv/bin/activate
python -m uvicorn app:app --reload --port 8000
```

### 2. Start the frontend (port 5173)

```bash
cd anonymization/frontend
npm run dev
```

### 3. Open the UI

Go to `http://localhost:5173`

---

## Usage

1. Drag-and-drop one or more TXT/JSON files into the upload zone (or click to browse)
2. Click **Anonymize**
3. View the side-by-side comparison with color-coded replacements:
   - **Yellow** — person names
   - **Green** — phone numbers
   - **Blue** — emails
   - **Red** — brand/device/product terms
   - **Purple** — other (addresses, account numbers, IDs)
4. Click **Download** for a single file or **Download All (ZIP)** for batch
5. Use **Copy** to copy anonymized text to clipboard

---

## API (without frontend)

### Anonymize a file (TXT or JSON)

```bash
curl -X POST http://localhost:8000/api/anonymize \
  -F "file=@conversation.txt"

# Also works with JSON
curl -X POST http://localhost:8000/api/anonymize \
  -F "file=@conversation.json"
```

Response:
```json
{
  "anonymized_text": "Cliente: Hola, soy [PERSON_1] y necesito ayuda...",
  "replacement_counts": {"PERSON": 1, "PHONE": 2, "EMAIL": 1},
  "total_replacements": 4
}
```

### Preview (original + anonymized)

```bash
curl -X POST http://localhost:8000/api/anonymize/preview \
  -F "file=@conversation.txt"
```

Response includes both `original_text` and `anonymized_text` for comparison.

### Health check

```bash
curl http://localhost:8000/api/health
```

---

## What Gets Anonymized

### Pass 1 — Regex (pattern-based)

| Category | Examples | Placeholder |
|----------|----------|-------------|
| Phone numbers | +52 55 1234 5678, 5512345678 | `[PHONE_1]` |
| Emails | user@domain.com | `[EMAIL_1]` |
| CURP | GALO850315HDFRRL09 | `[CURP_1]` |
| RFC | GALO850315AB1 | `[RFC_1]` |
| Order IDs | orden ORD-2024-78543, folio TKT-001 | `[ORDER_ID_1]` |
| Account numbers | IMEI 356938035643809, CLABE 012... | `[ACCOUNT_NUMBER_1]` |
| Addresses | Calle Reforma 234, Col. Centro | `[ADDRESS_1]` |
| URLs | https://support.example.com/user/123 | `[URL_1]` |

### Pass 2 — NER (AI-based, spaCy)

Catches person names and locations that the regex missed, especially Spanish full names (e.g., "María García López").

### Pass 3 — Brand scrub

Replaces brand-confidential terms from the configurable dictionary:

| Category | Placeholder |
|----------|-------------|
| Brand names | `[BRAND_1]` |
| Device names | `[DEVICE_1]` |
| Product names | `[PRODUCT_1]` |
| Service names | `[SERVICE_1]` |

---

## Customizing Brand Terms

Edit `backend/brand_terms.json`:

```json
{
  "brands": ["TechRepair", "Apple"],
  "devices": ["Galaxy S24 Ultra", "Galaxy A55", "iPhone 15"],
  "products": ["TechRepair Pay", "Apple Pay"],
  "services": ["TechRepair Service Center"]
}
```

Longer compound terms are always matched before shorter substrings.

---

## Running Tests

```bash
cd anonymization

# Full test suite (50 tests)
python3 -m pytest tests/ -v

# Only regex tests (fast, no spaCy needed)
python3 -m pytest tests/test_regex_pass.py -v

# Only NER tests
python3 -m pytest tests/test_ner_pass.py -v

# Only brand scrub tests
python3 -m pytest tests/test_brand_scrub.py -v

# Full pipeline integration tests
python3 -m pytest tests/test_pipeline_integration.py -v

# Generate HTML spot-check report for manual review
python3 -m pytest tests/test_spot_check.py -v
# Report saved to: tests/spot_check_report.html
```

---

## Project Structure

```
anonymization/
├── backend/
│   ├── app.py              # FastAPI application + endpoints
│   ├── pipeline.py         # Orchestrates all 3 anonymization passes
│   ├── regex_pass.py       # Pass 1: pattern-based PII detection
│   ├── ner_pass.py         # Pass 2: NER-based PII detection (spaCy/Presidio)
│   ├── brand_scrub.py      # Pass 3: brand term replacement
│   ├── config.py           # Regex patterns, category order, PlaceholderTracker
│   ├── brand_terms.json    # Configurable brand/device/product terms
│   └── requirements.txt    # Python dependencies
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx         # Main app with upload + results view
│   │   ├── components/     # UploadZone, DiffViewer, StatsBar, DownloadBar, etc.
│   │   ├── lib/            # API client, highlight logic, download helpers
│   │   └── ...
│   ├── package.json
│   └── vite.config.ts      # Proxies /api → localhost:8000
│
├── tests/
│   ├── fixtures/           # Test conversations with planted PII
│   ├── test_regex_pass.py  # Regex pattern tests
│   ├── test_ner_pass.py    # NER tests
│   ├── test_brand_scrub.py # Brand scrub tests
│   ├── test_pipeline_integration.py  # Full pipeline tests
│   └── test_spot_check.py  # HTML report generator
│
├── CONTEXT.md              # Project context for AI assistants
├── SPRINT_1_BACKEND.md     # Backend sprint spec
├── SPRINT_2_FRONTEND.md    # Frontend sprint spec
└── SPRINT_3_TESTING.md     # Testing sprint spec
```

---

## Notes

- First request after starting the backend takes 2-3 seconds (spaCy model loading)
- The platform is designed for Spanish-language conversations (Mexican Spanish)
- Same entity appearing multiple times gets the same placeholder number for traceability
- Over-anonymization is preferred over under-anonymization — false positives are acceptable, false negatives are not
