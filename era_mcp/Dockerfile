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
# Judge / synthesis / agent prompts live beside the package (agent.py resolves
# <pkg>/../prompts); without this COPY the container silently ran on the short
# inline fallback prompts.
COPY era_mcp/prompts/ prompts/
COPY --from=graph-web /graph-web/dist era_graph_web/dist
RUN python -c "import era_mcp.server; from era_mcp import agent; agent.assert_prompts_loaded()"

EXPOSE 8808

CMD ["python", "-m", "era_mcp.server"]
