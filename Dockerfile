FROM python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

ARG STEWARDBENCH_INSTALL_TEST_DEPS=false

RUN addgroup --system stewardbench && adduser --system --ingroup stewardbench stewardbench

COPY pyproject.toml README.md ./
COPY accounts ./accounts
COPY core ./core
COPY stewardbench ./stewardbench
COPY templates ./templates
COPY static ./static
COPY tests ./tests
COPY manage.py ./manage.py

RUN if [ "$STEWARDBENCH_INSTALL_TEST_DEPS" = "true" ]; then \
      python -m pip install --no-cache-dir '.[test]'; \
    else \
      python -m pip install --no-cache-dir .; \
    fi && \
    DJANGO_SECRET_KEY=build-only POSTGRES_DB=build POSTGRES_USER=build POSTGRES_PASSWORD=build \
    python manage.py collectstatic --noinput && \
    chown -R stewardbench:stewardbench /app

USER stewardbench

EXPOSE 8000

CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=2", "--access-logfile=-", "--error-logfile=-", "stewardbench.wsgi:application"]
