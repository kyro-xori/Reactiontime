# Reaction Time Test

A reaction-time game with username/password accounts and a shared leaderboard.

## Run it locally

1. Install Python 3.10 or newer.
2. From this folder, create a virtual environment and install the dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Start the web app:

   ```powershell
   .\.venv\Scripts\python.exe app.py
   ```

4. Open <http://127.0.0.1:5000>.

The local app creates `reactiontime.db` in this folder. The database contains
password hashes, not plain-text passwords. Keep the database file private.

## Deploy to Render

The `render.yaml` file describes a web service and a persistent PostgreSQL
database. It is in the repository root. In Render, create a Blueprint from this
repository and review the services and prices before confirming. The web
service uses the free plan; the database uses Render's `basic-256mb` plan and
may incur a recurring charge. Do not deploy unless you and the account owner
agree to the cost.

Render sets the database URL and generates the application's session-signing
key for you. The site and its API are served from the same HTTPS address.

## Accounts and scores

- Usernames are 3-20 letters, numbers, or underscores and are case-insensitive.
- Passwords must be 8-128 characters.
- Passwords are stored as salted scrypt hashes.
- Signed, HTTP-only cookies keep users signed in; the app never stores passwords
  in the browser.
- The leaderboard ranks each player by their fastest saved reaction.
- Scores are checked by the server but the browser supplies the measured time,
  so this is a friendly game leaderboard, not a tamper-proof competition.
