# Gunakan image python yang ringan
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /code

# Install dependencies sistem (opsional, tapi berguna utk psycopg2)
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Copy requirements dan install
COPY code/requirements.txt /code/
RUN pip install --no-cache-dir -r requirements.txt

# COPY SELURUH PROJECT (Penting! Beda dengan docker-compose lokal)
COPY code/ /code/

# Pindah ke folder dimana manage.py berada untuk collectstatic
WORKDIR /code/simplelms

# Kumpulkan static files (CSS/JS)
RUN python manage.py collectstatic --noinput

# Buka port (Railway otomatis inject PORT env, tapi kita expose 8000 sbg default)
EXPOSE 8000

# Jalankan Gunicorn
# simplelms.wsgi:application artinya menjalankan file simplelms/wsgi.py
CMD ["gunicorn", "simplelms.wsgi:application", "--bind", "0.0.0.0:8000"]