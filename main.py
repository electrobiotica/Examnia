from flask import Flask, request, jsonify, send_from_directory, render_template_string
import os
import uuid
import base64
import json
from dotenv import load_dotenv
from docx import Document
from docx.shared import Pt
import openai
import traceback

load_dotenv()

app = Flask(__name__, static_folder='static')

# === Config ===
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise RuntimeError("❌ OPENAI_API_KEY no está configurada en el entorno.")

MODEL_GENERATE = "gpt-4o"
MODEL_GRADE = "gpt-4o"
MODEL_VISION = "gpt-4o"
FILES_DIR = "generated_files"
STATIC_DIR = "static"
UPLOADS_DIR = "uploads"

os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

@app.route("/")
def serve_index():
    try:
        with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
            return render_template_string(f.read())
    except:
        return "<h1>Index.html no encontrado</h1>", 404

@app.route("/files/<filename>")
def download_file(filename):
    return send_from_directory(FILES_DIR, filename)

@app.route('/lang/<path:filename>')
def serve_lang(filename):
    return send_from_directory(os.path.join(STATIC_DIR, 'lang'), filename)

# === Prompts ===
def prompt_generate(req):
    return (
        f"You are an expert educational content creator. Return only valid JSON, no explanations.\n"
        f"Generate {req['n_questions']} {req['q_type']} questions.\n"
        f"Course: {req['course']}\n"
        f"Topic: {req['topic']}\n"
        f"Objectives: {req['objectives']}\n"
        f"Each question must include:\n"
        f"- id (e.g. Q1, Q2...)\n"
        f"- question\n"
        f"- options (only if type is mcq)\n"
        f"- answer\n"
        f"- rubric (with levels: Excelente, Aceptable, Insuficiente)\n"
        f"Return as a JSON array like:\n"
        f"[{{\"id\":\"Q1\", \"question\":\"...\", \"options\":[\"A\",\"B\",\"C\",\"D\"], \"answer\":\"A\", \"rubric\":{{\"Excelente\":\"...\",\"Aceptable\":\"...\",\"Insuficiente\":\"...\"}}}}]"
    )

def prompt_grade(req):
    return (
        f"Question: {req['question']}\n"
        f"Rubric: {req['rubric']}\n"
        f"Student answer: {req['student_answer']}\n"
        "Grade with a score (0-100) and feedback. Return JSON like {\"score\": X, \"feedback\": \"...\"}"
    )

# === Funciones de generación ===
def build_docx(exam, meta):
    doc = Document()
    doc.add_heading(f"Examen – {meta['course']}", level=0)
    doc.add_paragraph(f"Tema: {meta['topic']}")
    doc.add_paragraph(f"Objetivos: {meta['objectives']}")
    doc.add_paragraph("\n")
    for item in exam:
        q_run = doc.add_paragraph().add_run(f"{item['id']}. {item['question']}")
        q_run.font.size = Pt(12)
        if meta['q_type'] == "mcq":
            for letter, opt in zip("ABCD", item.get("options", [])):
                doc.add_paragraph(f"    {letter}) {opt}")
    doc.add_paragraph("\n\n---\nGenerado por ExamGen AI")
    filename = f"exam_{uuid.uuid4().hex}.docx"
    path = os.path.join(FILES_DIR, filename)
    doc.save(path)
    return filename

@app.route("/generate", methods=["POST"])
def generate_exam():
    try:
        req = request.json
        prompt = prompt_generate(req)

        response = openai.ChatCompletion.create(
            model=MODEL_GENERATE,
            messages=[
                {"role": "system", "content": f"You are an assessment generator that replies in {req['language']}."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1500
        )

        exam_json_str = response.choices[0].message.content.strip()
        print("📥 Respuesta bruta del modelo:\n", exam_json_str)

        try:
            exam = json.loads(exam_json_str)
        except Exception as json_err:
            print("❌ Error al parsear JSON:", json_err)
            print("📄 Contenido recibido:\n", exam_json_str)
            return jsonify({"error": "Error procesando la respuesta del modelo"}), 500

        result = {"exam": exam}
        if req.get("output_format") == "docx":
            filename = build_docx(exam, req)
            result["download_url"] = f"/files/{filename}"
        return jsonify(result)

    except Exception as e:
        print("❌ Error en /generate:")
        traceback.print_exc()
        return jsonify({"error": "Error generando el examen"}), 500

@app.route("/grade", methods=["POST"])
def grade_answer():
    try:
        req = request.json
        prompt = prompt_grade(req)
        response = openai.ChatCompletion.create(
            model=MODEL_GRADE,
            messages=[
                {"role": "system", "content": f"You are an exam corrector that responds in {req['language']}."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=300,
        )
        grade_json_str = response.choices[0].message.content.strip()
        return jsonify(json.loads(grade_json_str))
    except Exception as e:
        print("❌ Error en /grade:", e)
        return jsonify({"error": "Error al calificar"}), 500

@app.route("/analyze-image", methods=["POST"])
def analyze_image():
    try:
        file = request.files['file']
        contents = file.read()
        base64_image = base64.b64encode(contents).decode("utf-8")
        response = openai.ChatCompletion.create(
            model=MODEL_VISION,
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": "You are an exam corrector. Analyze this photo, extract questions and answers, and prepare it for scoring. Answer in Spanish."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]},
            ],
            max_tokens=1000,
        )
        return jsonify({"result": response.choices[0].message.content.strip()})
    except Exception as e:
        print("❌ Error en /analyze-image:", e)
        return jsonify({"error": "Error analizando la imagen"}), 500

@app.route("/generate-key", methods=["POST"])
def generate_answer_key():
    try:
        exam = request.json
        doc = Document()
        doc.add_heading("Hoja de respuestas", level=1)
        for item in exam:
            doc.add_paragraph(f"{item['id']}. {item['answer']}")
        filename = f"gabarito_{uuid.uuid4().hex}.docx"
        path = os.path.join(FILES_DIR, filename)
        doc.save(path)
        return jsonify({"download_url": f"/files/{filename}"})
    except Exception as e:
        print("❌ Error generando gabarito:", e)
        return jsonify({"error": "Error generando gabarito"}), 500

@app.route("/healthz")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
