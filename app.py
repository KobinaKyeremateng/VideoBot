from flask import Flask, render_template, request, jsonify
import os
import speech_recognition as sr
import subprocess
import tempfile
import json
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv 


load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

#source venv/bin/activate


#Get the API key from environment
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize client
client = OpenAI(api_key=OPENAI_API_KEY)

# Ensure upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# --------- Utility Functions --------- #

def extract_audio(video_path):
    audio_path = video_path.rsplit('.', 1)[0] + '.wav'
    try:
        command = [
            'ffmpeg',
            '-i', video_path,
            '-vn',
            '-acodec', 'pcm_s16le',
            '-ar', '16000',
            '-ac', '1',
            audio_path,
            '-y'
        ]
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return audio_path
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg error: {e.stderr.decode()}")
        return ""
    except FileNotFoundError:
        print("FFmpeg not found. Ensure it's installed and in your PATH.")
        return ""

def transcribe_audio(audio_path):
    if not audio_path or not os.path.exists(audio_path):
        return ""
    try:
        recognizer = sr.Recognizer()
        with sr.AudioFile(audio_path) as source:
            audio_data = recognizer.record(source)
            return recognizer.recognize_google(audio_data)
    except Exception as e:
        print(f"Transcription error: {e}")
        return ""

def analyze_responses(qa_list):
    summary = []
    for qa in qa_list:
        q = qa["question"].lower()
        a = qa["answer"].strip()

        if not a:
            summary.append(f"For the question '{qa['question']}', no understandable answer was given.")
        elif "subject" in q or "topic" in q:
            summary.append(f"The student enjoys studying '{a}', indicating an interest in that academic area.")
        elif "challenge" in q:
            summary.append(f"Described facing a challenge: '{a}', which reflects their ability to overcome academic difficulties.")
        elif "prepare" in q:
            summary.append(f"Prepares for exams or assignments by: '{a}', giving insight into their study strategy.")
        elif "goals" in q:
            summary.append(f"The future goals are: '{a}', indicating their ambition and career plans.")
        else:
            summary.append(f"Response to '{qa['question']}': {a}")
    return summary


#generates the summary of the responses
def generate_gpt_summary(summary_points):
    prompt = (
        "You are an academic counselor writing a detailed student interview report. "
        "Based on the following summary points, generate a comprehensive, formal summary:\n\n"
        + "\n".join(summary_points)
    )

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You write professional academic reports from student interviews."},
            {"role": "user", "content": prompt}
        ],
        max_tokens=800,
        temperature=0.7
    )

    return response.choices[0].message.content.strip()

# --------- Routes --------- #

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/instructions')
def instructions():
    return render_template('instructions.html')

@app.route('/jobLoved')
def jobLoved():
    return render_template('jobLoved.html')

@app.route('/interview')
def interview():
    return render_template('interview.html')

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('video_data')
    question = request.form.get('question', 'No question provided')

    if not file or file.filename == '':
        return jsonify({"error": "No video file received"}), 400

    with tempfile.NamedTemporaryFile(delete=False, suffix='.webm') as temp_video:
        file.save(temp_video.name)
        video_path = temp_video.name

    audio_path = extract_audio(video_path)
    answer = transcribe_audio(audio_path)

    # Clean up temp files
    if os.path.exists(video_path): os.remove(video_path)
    if os.path.exists(audio_path): os.remove(audio_path)

    return jsonify({
        "timestamp": datetime.now().isoformat(),
        "question": question,
        "answer": answer
    })

@app.route('/overview', methods=['POST'])
def overview():
    data = request.get_json()
    answer = data.get("answer", "").strip()

    if not answer:
        return jsonify({"error": "No answer provided"}), 400

    #Gives an overview of profession 
    try:
        prompt = (
            f"Provide a brief and informative overview of the profession mentioned in the following answer:\n\n"
            f"\"{answer}\"\n\n"
            "Do not repeat the answer. Summarize what the profession typically involves, its roles, and value."
        )

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You provide clear, concise overviews of professions mentioned in student answers."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=300,
            temperature=0.6
        )

        overview = response.choices[0].message.content.strip()
        return jsonify({"overview": overview})
    except Exception as e:
        import traceback
        print("Overview generation error:", e)
        traceback.print_exc()
    return jsonify({"error": "Failed to generate overview"}), 500


@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    responses = data.get("responses", [])
    profile_id = data.get("profile_id", "unknown")
    job_overview = data.get("overview", "")  # <- NEW: capture overview

    # Analyze the responses
    summary = analyze_responses(responses)
    detailed_report = generate_gpt_summary(summary)

    # Prepare data to save
    session_data = {
        "session_timestamp": datetime.now().isoformat(),
        "profile_id": profile_id,
        "job_overview": job_overview,               # <- NEW: include in saved data
        "responses": responses,
        "summary": summary,
        "detailed_report": detailed_report
    }


    # Ensure "responses" folder exists
    response_folder = os.path.join(os.path.dirname(__file__), "responses")
    os.makedirs(response_folder, exist_ok=True)

    # filename = f"session_{profile_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    # filepath = os.path.join(os.path.dirname(__file__), filename)

    # with open(filepath, "w") as f:
    #     json.dump(session_data, f, indent=4)

    # return jsonify({
    #     "analysis_timestamp": datetime.now().isoformat(),
    #     "summary": summary,
    #     "report": detailed_report,
    #     "filename": filename
    # })

     # Save JSON
    filename_base = f"session_{profile_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    json_filename = filename_base + ".json"
    #json_filepath = os.path.join(os.path.dirname(__file__), json_filename)
    json_filepath = os.path.join(response_folder, json_filename)
    

    with open(json_filepath, "w") as f:
        json.dump(session_data, f, indent=4)

    # Save TXT
    txt_filename = filename_base + ".txt"
    #txt_filepath = os.path.join(os.path.dirname(__file__), txt_filename)
    txt_filepath = os.path.join(response_folder, txt_filename)
    
    
    with open(txt_filepath, "w") as f:
        f.write("=== Student Interview Analysis ===\n\n")
        f.write(f"Profile ID: {profile_id}\n")
        f.write(f"Session Timestamp: {session_data['session_timestamp']}\n\n")
        
        if job_overview:
            f.write("Job Overview:\n")
            f.write(job_overview + "\n\n")

        f.write("Summary Points:\n")
        for point in summary:
            f.write("- " + point + "\n")
        
        f.write("\nDetailed Report:\n")
        f.write(detailed_report + "\n")

    return jsonify({
        "analysis_timestamp": datetime.now().isoformat(),
        "summary": summary,
        "report": detailed_report,
        "json_file": json_filename,
        "txt_file": txt_filename
    })

# --------- Run --------- #

if __name__ == '__main__':
    app.run(debug=True)
