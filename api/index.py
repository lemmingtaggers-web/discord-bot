import os
import json
import time

from flask import Flask, request, jsonify
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

app = Flask(__name__)

@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "online",
        "name": "Discord Vercel Bot"
    })

@app.route("/api/interactions", methods=["POST"])
def interactions():
    public_key = os.getenv("DISCORD_PUBLIC_KEY")
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")

    if not public_key or not signature or not timestamp:
        return jsonify({"error": "Missing signature headers"}), 401

    try:
        if abs(time.time() - int(timestamp)) > 300:
            return jsonify({"error": "Expired request"}), 401

        verify_key = VerifyKey(bytes.fromhex(public_key))
        verify_key.verify(
            timestamp.encode() + request.get_data(),
            bytes.fromhex(signature)
        )
    except (ValueError, BadSignatureError):
        return jsonify({"error": "Invalid signature"}), 401

    try:
        interaction = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    # Discord endpoint verification
    if interaction.get("type") == 1:
        return jsonify({"type": 1})

    # Slash command
    if interaction.get("type") == 2:
        command = interaction.get("data", {}).get("name")

        if command == "ping":
            return jsonify({
                "type": 4,
                "data": {
                    "content": "The bot is online."
                }
            })

        return jsonify({
            "type": 4,
            "data": {
                "content": "Unknown command."
            }
        })

    return jsonify({"error": "Unsupported interaction"}), 400
