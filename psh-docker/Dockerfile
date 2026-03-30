FROM node:22-alpine AS frontend_builder

WORKDIR /build/psh-react
COPY psh-react/package*.json ./
RUN npm install --no-audit --no-fund
COPY psh-react/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app/psh-fastapi

COPY psh-fastapi/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY psh-fastapi/ ./
RUN rm -rf ./static && mkdir -p ./static
COPY --from=frontend_builder /build/psh-react/dist/ ./static/

EXPOSE 9000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
