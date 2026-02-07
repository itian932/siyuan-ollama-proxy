FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -U pip && pip install -r requirements.txt

COPY app.py .

EXPOSE 18000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "18000"]
