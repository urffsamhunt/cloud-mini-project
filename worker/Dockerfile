FROM python:3.12-slim
WORKDIR /app
COPY worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY worker/worker.py .
COPY prompts/teacher_prompt.txt prompts/teacher_prompt.txt
ENV PROMPT_PATH=prompts/teacher_prompt.txt
CMD ["python", "-I", "worker.py"]
