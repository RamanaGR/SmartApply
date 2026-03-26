# SmartApply - AI-Powered Job Application Email Generator

Automated email generation and sending for job applications using local Ollama LLM and Gmail API.

## Features

- 📧 **Automated Email Generation** - Uses local Ollama LLM to generate personalized emails
- 🤖 **LLM-Powered Personalization** - Matches candidate skills to job requirements
- 📨 **Gmail API Integration** - Sends emails via Google OAuth2
- 📎 **Resume Attachment** - Automatically attaches PDF resume
- 🎯 **Batch Processing** - Process multiple job postings from CSV
- ⚙️ **Config-Driven** - All settings in `config.yaml`, no complex CLI arguments
- 📊 **Tracking** - Prevents duplicate emails, logs all activity
- 🔒 **Secure** - OAuth2 authentication, minimal permissions

## Quick Start

### 1. Install Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

Edit `config.yaml`:
```yaml
input:
  csv_filename: your_jobs.csv
  column_mapping:
    email: "Email Column"
    description: "Job Description"

resume:
  json_path: resume/Your_Name_Resume.json
  pdf_path: resume/Your_Name_Resume.pdf
```

### 3. Setup Credentials

Create `.env` file:
```bash
GMAIL_API_CREDENTIALS_PATH=credentials.json
```

Place `credentials.json` in project root (from Google Cloud Console).

### 4. Run

```bash
# Preview (dry-run)
python run.py --dry-run

# Send emails
python run.py
```

## Configuration

See `config.yaml` for complete options:
- `input.csv_filename` - CSV file with job postings
- `input.column_mapping` - Map CSV columns to email/description
- `email_processing.email_limit` - Limit number of emails (null = all)
- `ollama` - Ollama LLM settings
- `gmail` - Gmail API settings
- `resume` - Resume file paths

## File Structure

```
SmartApply/
├── src/                      # Source code
│   ├── main.py              # CLI entry point
│   ├── config_loader.py     # Configuration
│   ├── csv_reader.py        # CSV parsing
│   ├── llm_client.py        # Ollama integration
│   ├── email_sender.py      # Gmail API
│   └── validators.py        # Pre-flight checks
├── input/                    # CSV files
├── resume/                   # Resume files (JSON + PDF)
├── logs/                     # Output logs
├── data/                     # Tracking data
├── config.yaml              # Configuration
├── .env                      # Credentials (git-ignored)
├── credentials.json         # OAuth2 credentials (git-ignored)
└── requirements.txt         # Python dependencies
```

## CSV Format

```csv
Email Column,Job Description Column
email@example.com,"Senior Engineer position at Company..."
another@example.com,"Software Developer role at StartupXYZ..."
```

## Resume JSON Format

```json
{
  "cv": {
    "name": "Your Name",
    "email": "your@email.com",
    "phone": "+1-xxx-xxx-xxxx",
    "sections": {
      "experience": [
        {
          "company": "Company",
          "position": "Role",
          "highlights": ["Achievement 1", "Achievement 2"]
        }
      ],
      "skills": [
        { "name": "Skill", "level": "Expert" }
      ]
    }
  }
}
```

## How It Works

1. Reads job postings from CSV
2. Extracts recipient email and description
3. Loads your resume from JSON
4. Sends to Ollama LLM: "Here's a candidate, here's a job. Write a compelling application email."
5. Ollama generates personalized email matching your skills to the job
6. Sends via Gmail API with resume PDF attached
7. Tracks sent emails to prevent duplicates

## Security

- **OAuth2** - No passwords stored, uses Google OAuth2
- **Minimal Permissions** - Only `gmail.send` scope
- **Git-Ignored** - `.env` and `credentials.json` never committed
- **Local LLM** - Data stays local, no external AI services

## Troubleshooting

### Ollama Not Available
```bash
ollama serve  # Start Ollama
ollama pull llama3  # Download model
```

### Gmail Authentication Failed
- Verify `GMAIL_API_CREDENTIALS_PATH` in `.env` points to valid credentials.json
- First run opens browser for OAuth2 authentication
- Clear `token.pickle` if issues persist

### No Valid Rows Found
- Check CSV file exists in `input/` directory
- Verify `csv_filename` in `config.yaml` is correct
- Check `column_mapping` matches your CSV column names

### CSV Not Processing
- Ensure email addresses are valid
- Check column names in `column_mapping` match CSV exactly

## Logs

- `logs/app.log` - Application logs
- `logs/error.log` - Error logs
- `logs/results_*.csv` - Results for each run
- `data/sent_emails.json` - Tracking of sent emails

## License

Personal Use
