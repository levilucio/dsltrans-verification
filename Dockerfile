FROM node:20-bullseye

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/web-app/package*.json ./packages/web-app/
RUN cd packages/web-app && npm install

COPY packages/prover/pyproject.toml ./packages/prover/
COPY packages/prover/src ./packages/prover/src
COPY packages/prover/scripts ./packages/prover/scripts
COPY packages/prover/examples ./packages/prover/examples
RUN python3 -m pip install --no-cache-dir ./packages/prover

COPY packages/web-app ./packages/web-app
COPY screenshots ./screenshots
COPY README.md LICENSE render.yaml ./

RUN cd packages/web-app && npm run build

WORKDIR /app/packages/web-app
ENV NODE_ENV=production
ENV PORT=10000
EXPOSE 10000
CMD ["npm", "run", "serve"]
