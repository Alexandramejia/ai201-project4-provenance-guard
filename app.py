import uuid

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from audit import get_log_entries, log_appeal, log_submission
from detector import detect
from labels import generate_label

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri="memory://",
)


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")

    if not text or not creator_id:
        return jsonify({"error": "Both 'text' and 'creator_id' are required."}), 400

    content_id = str(uuid.uuid4())

    result = detect(text)
    llm_score = result["llm_score"]
    style_score = result["style_score"]
    confidence = result["confidence"]
    attribution = result["attribution"]
    status = "reviewed"
    label = generate_label(attribution, confidence)

    log_submission(
        content_id=content_id,
        creator_id=creator_id,
        attribution=attribution,
        confidence=confidence,
        llm_score=llm_score,
        style_score=style_score,
        status=status,
    )

    return jsonify(
        {
            "content_id": content_id,
            "attribution": attribution,
            "confidence": confidence,
            "label": label,
            "llm_score": llm_score,
            "style_score": style_score,
            "status": status,
        }
    )


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    creator_reasoning = data.get("creator_reasoning")

    if not content_id or not creator_reasoning:
        return jsonify({"error": "Both 'content_id' and 'creator_reasoning' are required."}), 400

    log_appeal(content_id=content_id, creator_reasoning=creator_reasoning)

    return jsonify(
        {
            "content_id": content_id,
            "status": "under_review",
            "message": "Your appeal has been logged and is under review.",
        }
    )


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": get_log_entries()})


if __name__ == "__main__":
    app.run(debug=True)
