import os
import logging
import requests

from flask import Flask, request, jsonify
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


class BotInfo:
    def __init__(self):
        self.DiscordPublicKey: str = "6399df85c0f8af4d3bfc5dc0edaeb34165ba7865007f85988292adc36931229a"
        self.DiscordBotToken: str = "MTU1OTQxMDk1MDI3MDg4NTk0OA.GFVwe1.gvTModgS4FWY3ornWXslzyld5qnU0KVTXOG1L8"
        self.DiscordAPI: str = "https://discord.com/api/v10"


Bot = BotInfo()

PING = 1
APPLICATION_COMMAND = 2
CHANNEL_MESSAGE = 4
DEFERRED_CHANNEL_MESSAGE = 5
EPHEMERAL = 64


def MakeResponse(Content="", Ephemeral=False, Embeds=None):
    Data = {
        "allowed_mentions": {
            "parse": ["everyone"]
        }
    }

    if Content:
        Data["content"] = str(Content)[:2000]

    if Ephemeral:
        Data["flags"] = EPHEMERAL

    if Embeds:
        Data["embeds"] = Embeds

    return {"type": CHANNEL_MESSAGE, "data": Data}


def VerifyDiscordRequest():
    if not Bot.DiscordPublicKey:
        app.logger.error("DISCORD_PUBLIC_KEY is not configured.")
        return False

    Signature = request.headers.get("X-Signature-Ed25519", "")
    Timestamp = request.headers.get("X-Signature-Timestamp", "")

    if not Signature or not Timestamp:
        return False

    try:
        Key = VerifyKey(bytes.fromhex(Bot.DiscordPublicKey))
        Key.verify(
            Timestamp.encode("utf-8") + request.get_data(),
            bytes.fromhex(Signature)
        )
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False


def GetOptions(Interaction):
    return {
        Item["name"]: Item.get("value")
        for Item in Interaction.get("data", {}).get("options", [])
    }


def IsAdmin(Interaction):
    try:
        Permissions = int(
            Interaction.get("member", {}).get("permissions", "0")
        )
        return bool(Permissions & 8)
    except (ValueError, TypeError):
        return False


def EditOriginalResponse(Interaction, Content):
    try:
        URL = (
            f"{Bot.DiscordAPI}/webhooks/"
            f"{Interaction['application_id']}/"
            f"{Interaction['token']}/messages/@original"
        )

        Result = requests.patch(
            URL,
            json={
                "content": Content[:2000],
                "allowed_mentions": {"parse": []}
            },
            timeout=8
        )
        Result.raise_for_status()
        return True

    except (requests.RequestException, KeyError):
        app.logger.exception("Failed to update interaction response.")
        return False


@app.route("/", methods=["GET"])
def Home():
    return jsonify({
        "name": "Discord Vercel Bot",
        "status": "online"
    })


@app.route("/api/test", methods=["GET"])
def Test():
    return jsonify({
        "status": "success",
        "message": "Discord bot API is working."
    })


@app.route("/api/interactions", methods=["GET", "POST"])
@app.route("/interactions", methods=["GET", "POST"])
def Interactions():
    # Browser health check
    if request.method == "GET":
        return jsonify({
            "status": "online",
            "message": "Discord interactions endpoint is reachable."
        })

    # Verify all incoming Discord POST requests
    if not VerifyDiscordRequest():
        return jsonify({"error": "Invalid Discord signature"}), 401

    Interaction = request.get_json(silent=True)

    if not isinstance(Interaction, dict):
        return jsonify({"error": "Invalid JSON"}), 400

    InteractionType = Interaction.get("type")

    # Discord endpoint verification
    if InteractionType == PING:
        return jsonify({"type": PING})

    if InteractionType != APPLICATION_COMMAND:
        return jsonify({"error": "Unsupported interaction type"}), 400

    Command = Interaction.get("data", {}).get("name", "").lower()
    Options = GetOptions(Interaction)

    # /ping
    if Command == "ping":
        return jsonify(MakeResponse("Pong! The bot is online."))

    # /say message:<text>
    if Command == "say":
        Message = Options.get("message", "")

        if not isinstance(Message, str) or not Message.strip():
            return jsonify(MakeResponse(
                "Please provide a message.",
                Ephemeral=True
            ))

        return jsonify(MakeResponse(Message))

    # /embed title:<text> description:<text> color:<hex>
    if Command == "embed":
        Title = Options.get("title", "Announcement")
        Description = Options.get("description", "")
        ColorText = Options.get("color", "#5865F2")

        if not isinstance(Title, str) or not isinstance(Description, str):
            return jsonify(MakeResponse(
                "Invalid embed text.",
                Ephemeral=True
            ))

        if not Description.strip():
            return jsonify(MakeResponse(
                "Please provide an embed description.",
                Ephemeral=True
            ))

        if not isinstance(ColorText, str):
            return jsonify(MakeResponse(
                "Color must be a hex string, like #5865F2.",
                Ephemeral=True
            ))

        ColorText = ColorText.removeprefix("#")

        try:
            if len(ColorText) != 6:
                raise ValueError()
            Color = int(ColorText, 16)
        except ValueError:
            return jsonify(MakeResponse(
                "Invalid color. Example: #5865F2",
                Ephemeral=True
            ))

        Embed = {
            "title": Title[:256],
            "description": Description[:4096],
            "color": Color
        }

        return jsonify(MakeResponse("", Embeds=[Embed]))

    # /announce channel:<channel> message:<text>
    if Command == "announce":
        if not IsAdmin(Interaction):
            return jsonify(MakeResponse(
                "Administrator permission is required.",
                Ephemeral=True
            ))

        ChannelID = Options.get("channel")
        Message = Options.get("message", "")

        if not ChannelID or not isinstance(Message, str) or not Message.strip():
            return jsonify(MakeResponse(
                "Provide a channel and a message.",
                Ephemeral=True
            ))

        if not Bot.DiscordBotToken:
            return jsonify(MakeResponse(
                "DISCORD_BOT_TOKEN is not configured.",
                Ephemeral=True
            ))

        # Acknowledge immediately so Discord's deadline is met
        CallbackURL = (
            f"{Bot.DiscordAPI}/interactions/"
            f"{Interaction['id']}/{Interaction['token']}/callback"
        )

        try:
            Callback = requests.post(
                CallbackURL,
                json={
                    "type": DEFERRED_CHANNEL_MESSAGE,
                    "data": {"flags": EPHEMERAL}
                },
                timeout=5
            )
            Callback.raise_for_status()

        except requests.RequestException:
            app.logger.exception("Failed to acknowledge announcement.")
            return "", 500

        try:
            Posted = requests.post(
                f"{Bot.DiscordAPI}/channels/{ChannelID}/messages",
                headers={
                    "Authorization": f"Bot {Bot.DiscordBotToken}"
                },
                json={
                    "content": Message[:2000],
                    "allowed_mentions": {"parse": []}
                },
                timeout=8
            )
            Posted.raise_for_status()

            EditOriginalResponse(
                Interaction,
                f"Announcement sent to <#{ChannelID}>."
            )

        except requests.RequestException:
            app.logger.exception("Announcement failed.")
            EditOriginalResponse(
                Interaction,
                "Announcement failed. Check the bot's channel permissions."
            )

        return "", 200

    return jsonify(MakeResponse(
        f"Unknown command: {Command}",
        Ephemeral=True
    ))


@app.errorhandler(404)
def NotFound(_Error):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def InternalError(_Error):
    return jsonify({"error": "Internal server error"}), 500
