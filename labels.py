def generate_label(attribution, confidence):
    """Turn an attribution + confidence score into a plain-language label."""
    confidence_percent = round(confidence * 100)

    if attribution == "likely_ai":
        return f"This content is likely AI-generated ({confidence_percent}% confidence)."
    if attribution == "likely_human":
        return f"This content is likely human-written ({confidence_percent}% confidence)."
    return f"We're not sure whether this content is AI or human ({confidence_percent}% confidence)."