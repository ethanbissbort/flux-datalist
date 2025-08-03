FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY coldstorage_project/ /app/

# Create necessary directories
RUN mkdir -p /app/media /app/staticfiles

EXPOSE 8000

# The command will be overridden by docker-compose
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
