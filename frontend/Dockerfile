FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY .streamlit ./.streamlit

ENV PYTHONPATH=/app

EXPOSE 8501

CMD ["streamlit", "run", "src/app.py", "--server.address", "0.0.0.0", "--server.port", "8501", "--browser.gatherUsageStats", "false"]
