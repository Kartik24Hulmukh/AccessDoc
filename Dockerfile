FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --requirement requirements.txt \
 && useradd --system --uid 10001 --no-create-home accessdoc
COPY --chown=10001:10001 app app
COPY --chown=10001:10001 public public
COPY --chown=10001:10001 fixtures fixtures
USER 10001:10001
ENV HOST=0.0.0.0 PORT=8000 PYTHONUNBUFFERED=1 ALLOW_NETWORK_EXPOSURE=true
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz',timeout=2)"
CMD ["python","-m","app.main"]
