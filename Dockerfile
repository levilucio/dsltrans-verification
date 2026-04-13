FROM python:3.12-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/web-app/package*.json ./packages/web-app/
RUN cd packages/web-app && npm install

COPY packages/prover/pyproject.toml ./packages/prover/
COPY packages/prover/src ./packages/prover/src
COPY packages/prover/scripts ./packages/prover/scripts
COPY packages/prover/examples ./packages/prover/examples
RUN python -m pip install --no-cache-dir ./packages/prover

COPY packages/web-app ./packages/web-app
COPY screenshots ./screenshots
COPY README.md LICENSE render.yaml ./

RUN cd packages/web-app && npm run build

WORKDIR /app/packages/web-app
ENV NODE_ENV=production
ENV PORT=10000
EXPOSE 10000
CMD ["npm", "run", "serve"]
