FROM node:20-slim AS graph-web

WORKDIR /graph-web

COPY era_graph_web/package*.json ./
RUN npm ci

COPY era_graph_web/ ./
RUN npm run build


FROM python:3.11-slim

WORKDIR /app

COPY era_mcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY era_mcp/era_mcp/ era_mcp/
COPY --from=graph-web /graph-web/dist era_graph_web/dist
RUN python -c "import era_mcp.server"

EXPOSE 8808

CMD ["python", "-m", "era_mcp.server"]
