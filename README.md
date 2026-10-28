# ABU Resolve — starter prototype

A responsive Flask web app prototype for ABU's student complaint classification, prioritisation and resolution workflow. The UI uses a clean teal/green palette, rounded controls, soft cards and mobile navigation inspired by the uploaded TeleHealth reference. The exact colours should be checked against the PDF visually and refined as needed.

## What is included
- Welcome page
- Student registration and login
- Student dashboard
- Submit complaint form
- My complaints and status filtering
- Complaint details and progress timeline
- Admin overview
- Admin complaint management with status, priority, office and response updates
- SQLite database and password hashing
- Basic rule-based routing/priority placeholder (not a trained AI model)

## Run on Windows
1. Install Python 3.11 or newer.
2. Extract this folder somewhere easy to find, for example Desktop.
3. Open PowerShell in the `abu_resolve` folder.
4. Run:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   python app.py
   ```
5. Open `http://127.0.0.1:5000` in your browser.

If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that same terminal, then activate again.

## Development admin login
- Email: `admin@aburesolve.local`
- Password: `Admin123!`

This is for local development only. Change the admin password, use a strong random `SECRET_KEY`, disable debug mode, and add production security protections before deployment. Do not use real sensitive student reports in this prototype.

## Current limitations
- The AI classifier has not been trained or connected yet.
- File/image attachments, email/SMS notifications, anonymous reporting, audit logs and production-grade access controls are not implemented.
- The current status progression is a simple visual timeline; the backend stores the current status and latest admin note.
- `abu_resolve.db` is created automatically on first run.
