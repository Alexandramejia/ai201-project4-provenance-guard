import uuid

from flask import Flask, jsonify, request

from audit import get_log_entries, log_submission
from detector import detect

app = Flask(__name__)

# Placeholder label text. Real transparency labels come in a later milestone.
PLACEHOLDER_LABEL = "Label logic not implemented yet."


@app.route("/submit", methods=["POST"])
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
            "label": PLACEHOLDER_LABEL,
            "llm_score": llm_score,
            "style_score": style_score,
            "status": status,
        }
    )


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": get_log_entries()})


if __name__ == "__main__":
    app.run(debug=True)
