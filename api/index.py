import os
import logging
import requests

from flask import Flask, request, jsonify
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

DISCORD_PUBLIC_KEY = os.getenv("DISCORD_PUBLIC_KEY", "")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_API = "https://discord.com/api/v10"

PING = 1
APPLICATION_COMMAND = 2
CHANNEL_MESSAGE = 4
DEFERRED_CHANNEL_MESSAGE = 5
EPHEMERAL = 64


def response(content, ephemeral=False, embeds=None):
    data = {"allowed_mentions": {"parse": []}}

    if content:
        data["content"] = str(content)[:2000]

    if ephemeral:
        data["flags"] = EPHEMERAL

    if embeds:
        data["embeds"] = embeds

    return {"type": CHANNEL_MESSAGE, "data": data}


def verify_signature():
    if not DISCORD_PUBLIC_KEY:
        app.logger.error("DISCORD_PUBLIC_KEY is missing")
        return False

    signature = request.headers.get("X-Signature-Ed25519", "")
    timestamp = request.headers.get("X-Signature-Timestamp", "")

    if not signature or not timestamp:
        return False

    try:
        key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        key.verify(
            timestamp.encode("utf-8") + request.get_data(),
            bytes.fromhex(signature)
        )
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False


def get_options(interaction):
    return {
        item["name"]: item.get("value")
        for item in interaction.get("data", {}).get("options", [])
    }


def is_admin(interaction):
    try:
        permissions = int(
            interaction.get("member", {}).get("permissions", "0")
        )
        return bool(permissions & 8)
    except (TypeError, ValueError):
        return False


def edit_original(interaction, content):
    try:
        url = (
            f"{DISCORD_API}/webhooks/"
            f"{interaction['application_id']}/"
            f"{interaction['token']}/messages/@original"
        )
        result = requests.patch(
            url,
            json={
                "content": content[:2000],
                "allowed_mentions": {"parse": []}
            },
            timeout=8
        )
        result.raise_for_status()
        return True
    except (requests.RequestException, KeyError):
        app.logger.exception("Could not update interaction response")
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
        "message": "API is working"
    })


# Both routes are supported for different Vercel routing setups.
@app.route("/api/interactions", methods=["GET", "POST"])
@app.route("/interactions", methods=["GET", "POST"])
def interactions():
    # Browser health check. Discord uses signed POST requests.
    if request.method == "GET":
        return jsonify({
            "status": "online",
            "message": "Discord interactions endpoint is reachable"
        }), 200

    # Never process unsigned Discord interactions.
    if not verify_signature():
        return jsonify({"error": "Invalid Discord signature"}), 401

    interaction = request.get_json(silent=True)

    if not isinstance(interaction, dict):
        return jsonify({"error": "Invalid JSON"}), 400

    interaction_type = interaction.get("type")

    # Discord endpoint verification handshake.
    if interaction_type == PING:
        return jsonify({"type": PING})

    if interaction_type != APPLICATION_COMMAND:
        return jsonify({"error": "Unsupported interaction"}), 400

    command = interaction.get("data", {}).get("name", "").lower()
    options = get_options(interaction)

    if command == "ping":
        return jsonify(response("Pong! The bot is online."))

    if command == "say":
        message = options.get("message", "")
        if not isinstance(message, str) or not message.strip():
            return jsonify(response(
                "Enter a message.", ephemeral=True
            ))
        return jsonify(response(message))

    if command == "embed":
        title = options.get("title", "Announcement")
        description = options.get("description", "")
        color_text = options.get("color", "#5865F2")

        if not isinstance(title, str) or not isinstance(description, str):
            return jsonify(response("Invalid embed text.", ephemeral=True))

        if not description.strip():
            return jsonify(response(
                "Enter an embed description.", ephemeral=True
            ))

        if not isinstance(color_text, str):
            return jsonify(response(
                "Color must be a hex string, like #5865F2.",
                ephemeral=True
            ))

        color_text = color_text.removeprefix("#")
        try:
            if len(color_text) != 6:
                raise ValueError()
            color = int(color_text, 16)
        except ValueError:
            return jsonify(response(
                "Invalid color. Example: #5865F2",
                ephemeral=True
            ))

        embed = {
            "title": title[:256],
            "description": description[:4096],
            "color": color
        }
        return jsonify(response("", embeds=[embed]))

    if command == "announce":
        if not is_admin(interaction):
            return jsonify(response(
                "Administrator permission is required.",
                ephemeral=True
            ))

        channel_id = options.get("channel")
        message = options.get("message", "")

        if not channel_id or not isinstance(message, str) or not message.strip():
            return jsonify(response(
                "Provide a channel and message.", ephemeral=True
            ))

        if not DISCORD_BOT_TOKEN:
            return jsonify(response(
                "DISCORD_BOT_TOKEN is not configured.",
                ephemeral=True
            ))

        # Acknowledge within Discord's response deadline first.
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
            app.logger.exception("Could not acknowledge announcement")
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
            edit_original(
                interaction,
                f"Announcement sent to <#{channel_id}>."
            )
        except requests.RequestException:
            app.logger.exception("Announcement failed")
            edit_original(
                interaction,
                "Announcement failed. Check the bot's channel permissions."
            )

        return "", 200

    return jsonify(response(
        f"Unknown command: {command}",
        ephemeral=True
    ))


@app.errorhandler(404)
def not_found(_error):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(_error):
    return jsonify({"error": "Internal server error"}), 500
