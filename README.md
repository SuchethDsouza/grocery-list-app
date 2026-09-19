# Pantry List

A one-tap grocery list builder for households. Select what's needed for tomorrow's
cooking, then send the list straight to whoever's doing the shopping — over
WhatsApp or email. No more forgetting an item or scribbling on paper.

## Features

- **Accounts per household** — sign up, log in, everyone on the account shares one live list
- **Search** — instantly filter the grocery catalog as you type
- **Frequently added** — quick-pick chips for items you send most often, based on your own history
- **Tap-to-select items** grouped by pantry category, with a clear checkmark state (not just color)
- **Quantity steppers** — adjust +/- directly on Today's List without retyping
- **Add custom items** on the fly, with quantity and unit, added straight to the list
- **Live receipt panel** that fills up as you select — the visual metaphor for the list itself
- **Shopping mode** — check items off while you're actually in the store, with a completion counter
- **Undo on clear** — clearing the list shows a 5-second "Undo" toast before it's actually gone
- **Send via WhatsApp** — opens a pre-filled WhatsApp chat, no API keys needed
- **Send via Email** — sends directly from the server via SMTP
- **History** — every list you've sent, so you can reuse patterns later
- **Responsive** — a proper mobile layout with a bottom sheet for Today's List, not just a shrunk desktop view

## Setup

```bash
cd grocery-list-app
pip install -r requirements.txt
python app.py
```

Visit `http://127.0.0.1:5000`. The database (`grocery.db`) and a starter catalog of
~40 common grocery items across 7 categories are created automatically on first run.

## Enabling email sending

Email sending uses SMTP and reads credentials from a `.env` file, so they're never
hardcoded in the code and never committed to version control (`.env` is already
in `.gitignore`).

1. Copy `.env.example` to a new file named `.env` in the project root.
2. Fill in your real values:
   ```
   MAIL_USERNAME=youraddress@gmail.com
   MAIL_PASSWORD=your16charapppassword
   MAIL_SERVER=smtp.gmail.com
   MAIL_PORT=587
   ```
3. For Gmail, `MAIL_PASSWORD` must be a 16-character **App Password**, not your
   normal Gmail password — generate one at
   `myaccount.google.com/apppasswords` (requires 2-Step Verification to be
   enabled first). Remove the spaces when you paste it in.
4. Restart the app (Run/Debug in PyCharm, or `python app.py`).

The app loads `.env` automatically via `python-dotenv` on startup — this works
the same way whether you run it from PyCharm's Run button, Debug button, or a
plain terminal, so there's nothing to configure per-environment. If `.env` is
missing or the two values are blank, "Send by Email" returns a clear error
instead of failing silently.

## WhatsApp sending

No setup needed — this uses the free `wa.me` deep link, which opens WhatsApp
(app or web) with the grocery list pre-typed into a chat with the given number.
The person still taps "Send" inside WhatsApp themselves; nothing is sent
automatically on your behalf, and no WhatsApp Business API account is required.

## Project structure

```
grocery-list-app/
├── app.py                  # Flask app: models, auth, routes
├── requirements.txt
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── signup.html
│   ├── dashboard.html      # main item-selection + receipt UI
│   └── history.html
└── static/
    ├── css/style.css       # pantry/receipt design system
    └── js/app.js           # item toggling, live receipt, send actions
```

## Notes for deployment

- Shopping mode's checked-off state lives only in the browser tab — it resets on page reload. This is intentional (nothing to configure), but flag it if you want it to persist across a refresh; that would need a small backend addition.
- Set a real `SECRET_KEY` environment variable in production — the default is for
  local development only.
- The dev server (`app.run(debug=True)`) is not production-safe. For a real
  deployment, use `gunicorn` or similar behind a reverse proxy, and turn `debug`
  off.
- SQLite is fine for a household-scale app; if this ever needs to serve many
  families concurrently, migrate to Postgres by changing `SQLALCHEMY_DATABASE_URI`.
