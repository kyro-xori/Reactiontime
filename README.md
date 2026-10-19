# Reaction Time Test

This repository contains a reaction-time game with username/password accounts
and an online leaderboard in [`reactiontime/`](./reactiontime/).

To run locally, install its dependencies and start its Python server:

```powershell
cd reactiontime
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Then open <http://127.0.0.1:5000>. For the shared online version, deploy the
root [`render.yaml`](./render.yaml) Blueprint from Render. Review its service
plans and prices before confirming: the web service uses Render's free plan,
but the persistent PostgreSQL database uses the `basic-256mb` plan and may
incur a recurring charge. Do not deploy unless the account owner approves the
cost.
