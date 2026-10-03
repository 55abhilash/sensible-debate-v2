# Sensible Debate - production image.
#
# psycopg[binary] and redis are pure-Python/precompiled-wheel installs, so
# no build toolchain is needed - a single slim stage is enough. This image
# is architecture-agnostic: build it with --platform linux/arm64 for the
# Graviton (t4g) instances used in the Terraform in terraform/, or
# linux/amd64 if you change the instance family.
FROM python:3.12-slim

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh && chmod +x /usr/local/bin/docker-entrypoint.sh

RUN chown -R app:app /app
USER app

EXPOSE 8000

ENTRYPOINT ["/bin/sh", "/usr/local/bin/docker-entrypoint.sh"]
