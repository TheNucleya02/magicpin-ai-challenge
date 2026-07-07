# Vera Merchant AI Assistant - Deployment Setup

**Project**: magicpin Vera AI Assistant  
**Type**: Assignment Submission  
**Last Updated**: 2026-07-07

---

## Quick Start

### 1. Prerequisites
- Python 3.9+
- pip or conda
- Google Gemini API key
- Docker (optional, for containerization)

### 2. Local Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export GOOGLE_API_KEY="your-api-key-here"

# Run the application
python bot.py

# API runs on http://localhost:8000
```

### 3. Testing

```bash
# Run the judge simulator
python judge_simulator.py

# Generate submission
python generate_submission.py
```

### 4. Docker Deployment (Optional)

```dockerfile
# Dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "bot:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:
```bash
docker build -t vera-bot .
docker run -e GOOGLE_API_KEY="your-key" -p 8000:8000 vera-bot
```

### 5. API Endpoints

- `GET /` - Health check
- `POST /message` - Send merchant/customer message
- `GET /context/{context_id}` - Retrieve context
- `POST /context` - Store context

### 6. Key Features

✅ Intent detection (yes/no/qualifying/opt-out)  
✅ Auto-reply filtering (WhatsApp canned responses)  
✅ Hinglish style switching (English/Romanized Hindi)  
✅ In-memory conversation state tracking  
✅ Google Gemini integration  

---

## Project Structure

```
├── bot.py                      # FastAPI app
├── conversation_handlers.py    # State machine
├── judge_simulator.py          # Test runner
├── generate_submission.py      # Output generator
├── requirements.txt            # Dependencies
├── dataset/                    # Training data
├── expanded/                   # Test cases
└── submission.jsonl            # Output
```

---

## Submission Checklist

- [ ] All tests pass with `python judge_simulator.py`
- [ ] Output generated: `submission.jsonl`
- [ ] Code runs without errors
- [ ] `.gitignore` configured
- [ ] README with instructions (existing)
- [ ] No API keys in committed code

---

## Troubleshooting

**API errors**: Check `GOOGLE_API_KEY` environment variable  
**Port in use**: Change port in `bot.py` or kill process on 8000  
**Import errors**: Run `pip install -r requirements.txt`  
**Test failures**: Check dataset files in `expanded/`

---

**Ready to submit!**
