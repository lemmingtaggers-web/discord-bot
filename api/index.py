
import os
import json
import logging
import requests

from datetime import datetime, timezone
from flask import Flask, request, jsonify
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

DISCORD_PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY", "6399df85c0f8af4d3bfc5dc0edaeb34165ba7865007f85988292adc36931229a")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "MTU1OTQxMDk1MDI3MDg4NTk0OA.GFVwe1.gvTModgS4FWY3ornWXslzyld5qnU0KVTXOG1L8")
DISCORD_API = "https://discord.com/api/v10"

# Discord interaction callback types
PING = 1
APPLICATION_COMMAND = 2
CHANNEL_MESSAGE = 4
DEFERRED_CHANNEL_MESSAGE = 5

EPHEMERAL = 1 << 6


def json_response(data, status=200):
    return jsonify(data), status


def interaction_response(content, ephemeral=False, embeds=None):
    data = {
        "content": str(content)[:2000],
        "allowed_mentions": {"parse": []}
    }

    if ephemeral:
        data["flags"] = EPHEMERAL

    if embeds:
        data["embeds"] = embeds

    return {"type": CHANNEL_MESSAGE, "data": data}


def get_options(interaction):
    """Convert Discord command options into a dictionary."""
    result = {}

    for option in interaction.get("data", {}).get("options", []):
        result[option["name"]] = option.get("value")

    return result


def is_admin(interaction):
    """Check the invoking member's Administrator permission."""
    member = interaction.get("member") or {}
    permissions = member.get("permissions", "0")

    try:
        return bool(int(permissions) & (1 << 3))
    except (ValueError, TypeError):
        return False


def verify_discord_request():
    """Verify Discord's Ed25519 signature against the raw request body."""
    if not DISCORD_PUBLIC_KEY:
        app.logger.error("DISCORD_PUBLIC_KEY is not configured.")
        return False

    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")

    if not signature or not timestamp:
        return False

    try:
        verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        verify_key.verify(
            timestamp.encode("utf-8") + request.get_data(),
            bytes.fromhex(signature)
        )
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False


def edit_original_response(interaction, content):
    """Update an acknowledged interaction response."""
    app_id = interaction.get("application_id")
    token = interaction.get("token")

    if not app_id or not token:
        return False

    try:
        response = requests.patch(
            f"{DISCORD_API}/webhooks/{app_id}/{token}/messages/@original",
            json={
                "content": content[:2000],
                "allowed_mentions": {"parse": []}
            },
            timeout=8
        )
        response.raise_for_status()
        return True
    except requests.RequestException:
        app.logger.exception("Failed to update interaction response.")
        return False


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "name": "Discord Vercel Bot",
        "status": "online"
    })


@app.route("/api/test", methods=["GET"])
def test():
    return jsonify({
        "status": "success",
        "message": "Discord bot API is working."
    })


# Support either path if your Vercel routing strips the /api prefix.
@app.route("/api/interactions", methods=["POST"])
@app.route("/interactions", methods=["POST"])
def interactions():
    # Never process unverified Discord requests.
    if not verify_discord_request():
        return jsonify({"error": "Invalid Discord signature"}), 401

    try:
        interaction = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    if not isinstance(interaction, dict):
        return jsonify({"error": "Invalid interaction"}), 400

    interaction_type = interaction.get("type")

    # Discord sends this when validating your endpoint.
    if interaction_type == PING:
        return jsonify({"type": PING})

    if interaction_type != APPLICATION_COMMAND:
        return jsonify({"error": "Unsupported interaction type"}), 400

    command = interaction.get("data", {}).get("name", "").lower()
    options = get_options(interaction)

    # /ping
    if command == "ping":
        return jsonify(interaction_response("Pong! The bot is online."))

    # /say message:<text>
    if command == "say":
        message = options.get("message", "")

        if not isinstance(message, str) or not message.strip():
            return jsonify(interaction_response(
                "Please provide a message.", ephemeral=True
            ))

        return jsonify(interaction_response(message[:2000]))

    # /embed title:<text> description:<text> color:<hex>
    if command == "embed":
        title = options.get("title", "Announcement")
        description = options.get("description", "")
        color_text = options.get("color", "#5865F2")

        if not isinstance(title, str) or not isinstance(description, str):
            return jsonify(interaction_response(
                "Invalid embed title or description.", ephemeral=True
            ))

        if not description.strip():
            return jsonify(interaction_response(
                "Please provide an embed description.", ephemeral=True
            ))

        if not isinstance(color_text, str):
            return jsonify(interaction_response(
                "Color must be a hex string, such as #5865F2.",
                ephemeral=True
            ))

        color_text = color_text.removeprefix("#")

        try:
            if len(color_text) != 6:
                raise ValueError("Expected six hex digits.")
            color = int(color_text, 16)
        except ValueError:
            return jsonify(interaction_response(
                "Invalid color. Use a hex value such as #5865F2.",
                ephemeral=True
            ))

        embed = {
            "title": title[:256],
            "description": description[:4096],
            "color": color
        }

        return jsonify(interaction_response(
            "",
            embeds=[embed]
        ))

    # /announce channel:<channel> message:<text>
    # Administrator-only. Acknowledge immediately, then post.
    if command == "announce":
        if not is_admin(interaction):
            return jsonify(interaction_response(
                "You need the Administrator permission to use this command.",
                ephemeral=True
            ))

        channel_id = options.get("channel")
        message = options.get("message", "")

        if not channel_id or not isinstance(message, str) or not message.strip():
            return jsonify(interaction_response(
                "Provide a channel and a message.", ephemeral=True
            ))

        if not DISCORD_BOT_TOKEN:
            return jsonify(interaction_response(
                "The bot token is not configured on the server.",
                ephemeral=True
            ))

        # Acknowledge before making the Discord API request.
        callback_url = (
            f"{DISCORD_API}/interactions/"
            f"{interaction['id']}/{interaction['token']}/callback"
        )

        try:
            callback = requests.post(
                callback_url,
                json={
                    "type": DEFERRED_CHANNEL_MESSAGE,
                    "data": {"flags": EPHEMERAL}
                },
                timeout=5
            )
            callback.raise_for_status()
        except requests.RequestException:
            app.logger.exception("Could not acknowledge announcement.")
            return "", 500

        try:
            posted = requests.post(
                f"{DISCORD_API}/channels/{channel_id}/messages",
                headers={
                    "Authorization": f"Bot {DISCORD_BOT_TOKEN}"
                },
                json={
                    "content": message[:2000],
                    "allowed_mentions": {"parse": []}
                },
                timeout=8
            )
            posted.raise_for_status()

            edit_original_response(
                interaction,
                f"Announcement sent to <#{channel_id}>."
            )

        except requests.RequestException:
            app.logger.exception("Announcement failed.")
            edit_original_response(
                interaction,
                "I couldn't send the announcement. Check the bot's channel permissions."
            )

        return "", 200

    return jsonify(interaction_response(
        f"Unknown command: {command}",
        ephemeral=True
    ))


@app.errorhandler(404)
def not_found(_error):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(_error):
    return jsonify({"error": "Internal server error"}), 500
