FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY bot ./bot
COPY alembic ./alembic
COPY alembic.ini .

# default command; the bot service overrides it in compose
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
