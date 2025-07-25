from flask import Flask, request, jsonify, send_from_directory, render_template_string
import os, uuid, base64, json, traceback
from dotenv import load_dotenv
from docx import Document
from docx.shared import Pt
import openai   # v ≥ 1.0
from openai import OpenAIError

load_dotenv()

app = Flask(__name__, static_folder='static')

# === Config ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("❌ OPENAI_API_KEY no está configurada en el entorno.")

# ⬇️ NUEVO: instancia de cliente
client = openai.OpenAI(api_key=OPENAI_API_KEY)

MODEL_GENERATE = MODEL_GRADE = MODEL_VISION = "gpt-4o"
FILES_DIR, STATIC_DIR, UPLOADS_DIR = "generated_files", "static", "uploads"
os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)

# -------------------------------------------------------------------
@app.route("/")
def serve_index():
    try:
        with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
            return render_template_string(f.read())
    except FileNotFoundError:
        return "<h1>Index.html no encontrado</h1>", 404

@app.route("/files/<filename>")
def download_file(filename):
    return send_from_directory(FILES_DIR, filename)

@app.route("/lang/<path:filename>")
def serve_lang(filename):
    return send_from_directory(os.path.join(STATIC_DIR, "lang"), filename)
# -------------------------------------------------------------------

def prompt_generate(req):
    return (
        "You are an expert educational content creator. Return only valid JSON, no explanations.\n"
        f"Generate {req['n_questions']} {req['q_type']} questions.\n"
        f"Course: {req['course']}\n"
        f"Topic: {req['topic']}\n"
        f"Objectives: {req['objectives']}\n"
        "Each question must include:\n"
        "- id (e.g. Q1)\n- question\n- options (if mcq)\n- answer\n"
        "- rubric (Excelente, Aceptable, Insuficiente)\n"
        "Return as JSON array."
    )

def prompt_grade(req):
    return (
        f"Question: {req['question']}\nRubric: {req['rubric']}\n"
        f"Student answer: {req['student_answer']}\n"
        'Return JSON {"score": X, "feedback": "..."}'
    )

def build_docx(exam, meta):
    doc = Document()
    doc.add_heading(f"Examen – {meta['course']}", 0)
    doc.add_paragraph(f"Tema: {meta['topic']}")
    doc.add_paragraph(f"Objetivos: {meta['objectives']}\n")
    for item in exam:
        run = doc.add_paragraph().add_run(f"{item['id']}. {item['question']}")
        run.font.size = Pt(12)
        if meta['q_type'] == "mcq":
            for letter, opt in zip("ABCD", item.get("options", [])):
                doc.add_paragraph(f"    {letter}) {opt}")
    doc.add_paragraph("\n---\nGenerado por ExamGen AI")
    filename = f"exam_{uuid.uuid4().hex}.docx"
    doc.save(os.path.join(FILES_DIR, filename))
    return filename
# -------------------------------------------------------------------

@app.route("/generate", methods=["POST"])
def generate_exam():
    try:
        req = request.json
        prompt = prompt_generate(req)

        response = client.chat.completions.create(
            model=MODEL_GENERATE,
            messages=[
                {"role": "system", "content": f"You are an assessment generator that replies in {req['language']}."},
                {"role": "user",    "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1500,
            # response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content.strip()
        print("📥 RAW model reply:\n", content)

        try:
            exam = json.loads(content)
        except Exception as json_err:
            print("❌ JSON parse error:", json_err)
            print("📄 Content:\n", content)
            return jsonify({"error": "Respuesta del modelo inválida"}), 500

        result = {"exam": exam}
        if req.get("output_format") == "docx":
            result["download_url"] = f"/files/{build_docx(exam, req)}"
        return jsonify(result)

    except OpenAIError as openai_err:
        print("❌ OpenAI API error:", openai_err)
        return jsonify({"error": f"Error OpenAI: {str(openai_err)}"}), 500

    except Exception as e:
        print("❌ Error general:")
        traceback.print_exc()
        return jsonify({"error": "Error generando el examen"}), 500

# -------------------------------------------------------------------

@app.route("/grade", methods=["POST"])
def grade_answer():
    try:
        req = request.json
        response = client.chat.completions.create(
            model=MODEL_GRADE,
            messages=[
                {"role": "system", "content": f"You are an exam corrector that replies in {req['language']}."},
                {"role": "user",    "content": prompt_grade(req)}
            ],
            temperature=0.2,
            max_tokens=300
        )
        return jsonify(json.loads(response.choices[0].message.content))
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Error al calificar"}), 500
# -------------------------------------------------------------------

@app.route("/analyze-image", methods=["POST"])
def analyze_image():
    try:
        file = request.files["file"]
        b64 = base64.b64encode(file.read()).decode()
        response = client.chat.completions.create(
            model=MODEL_VISION,
            messages=[
                {"role": "user", "content": [
                    {"type": "text",       "text": "You are an exam corrector. Analyze this photo and extract questions and answers. Answer in Spanish."},
                    {"type": "image_url",  "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]}
            ],
            max_tokens=1000
        )
        return jsonify({"result": response.choices[0].message.content.strip()})
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Error analizando la imagen"}), 500
# -------------------------------------------------------------------

@app.route("/generate-key", methods=["POST"])
def generate_answer_key():
    try:
        exam = request.json
        doc = Document()
        doc.add_heading("Hoja de respuestas", 1)
        for item in exam:
            doc.add_paragraph(f"{item['id']}. {item['answer']}")
        filename = f"gabarito_{uuid.uuid4().hex}.docx"
        doc.save(os.path.join(FILES_DIR, filename))
        return jsonify({"download_url": f"/files/{filename}"})
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Error generando gabarito"}), 500
# -------------------------------------------------------------------


# -------------------------------------------------------------------


@app.route("/healthz")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
