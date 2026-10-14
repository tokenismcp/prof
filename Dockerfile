FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY prof ./prof
RUN pip install --no-cache-dir -e .
ENV PROF_DEMO=1 PORT=8091
EXPOSE 8091
CMD ["python", "-m", "prof", "gateway"]
