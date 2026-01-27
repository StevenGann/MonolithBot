FROM python:3.11-slim

WORKDIR /app

RUN useradd --create-home --shell /bin/bash botuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/

RUN chown -R botuser:botuser /app
USER botuser

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "bot.main"]
