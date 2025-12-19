FROM python:3.10-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /code
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*
COPY code/requirements.txt /code/
RUN pip install --no-cache-dir -r requirements.txt
COPY code/ /code/
WORKDIR /code/simplelms
RUN python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["gunicorn", "simplelms.wsgi:application", "--bind", "0.0.0.0:8000"]