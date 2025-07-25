# Usa una imagen oficial de Python 3.11 slim
FROM python:3.11-slim

# Establece el directorio de trabajo
WORKDIR /app

# Copia e instala las dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia el resto del código
COPY . .

# Comando para ejecutar la app con Uvicorn en el puerto 10000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
