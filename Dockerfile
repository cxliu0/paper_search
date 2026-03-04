# 使用 Python 3.10 基础镜像
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制整个项目代码
# 注意：假设你的项目结构是根目录下有 api.py, agent.py 和 paper_agent/ 文件夹
COPY . .

# 暴露端口 (Hugging Face Spaces 通常自动映射，但声明一下是好习惯)
EXPOSE 7860

# 启动命令
# 关键修改：
# 1. 监听 0.0.0.0 (允许外部访问)，而不是默认的 127.0.0.1
# 2. 使用环境变量 $PORT (HF 动态分配端口) 或固定为 7860
CMD ["python", "api.py", "--host", "0.0.0.0", "--port", "7860"]
