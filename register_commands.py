import os
import requests

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
APP_ID = os.getenv("DISCORD_APP_ID")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")

if not all([BOT_TOKEN, APP_ID, GUILD_ID]):
    raise SystemExit(
        "Set DISCORD_BOT_TOKEN, DISCORD_APP_ID, and DISCORD_GUILD_ID first."
    )

commands = [
    {
        "name": "ACTIVITY",
        "description": "CHECK IF THE BOT IS ONLINE"
    },
    {
        "name": "",
        "description": "",
        "options": [
            {
                "name": "",
                "description": "",
                "type": 3,
                "required": True
            }
        ]
    },
    {
        "name": "embed",
        "description": "",
        "options": [
            {
                "name": "title",
                "description": "The embed title.",
                "type": 3,
                "required": True
            },
            {
                "name": "description",
                "description": "The embed description.",
                "type": 3,
                "required": True
            },
            {
                "name": "color",
                "description": "Hex color, such as #5865F2.",
                "type": 3,
                "required": False
            }
        ]
    },
    {
        "name": "announce",
        "description": "Send an announcement to a channel.",
        "default_member_permissions": "8",
        "options": [
            {
                "name": "channel",
                "description": "The channel to announce in.",
                "type": 7,
                "required": True,
                "channel_types": [0]
            },
            {
                "name": "message",
                "description": "The announcement text.",
                "type": 3,
                "required": True
            }
        ]
    }
]

url = (
    f"https://discord.com/api/v10/applications/"
    f"{APP_ID}/guilds/{GUILD_ID}/commands"
)

result = requests.put(
    url,
    headers={"Authorization": f"Bot {BOT_TOKEN}"},
    json=commands,
    timeout=20
)

if result.ok:
    print("Successfully registered slash commands!")
    for command in result.json():
        print(f"/{command['name']}")
else:
    print(f"Registration failed: HTTP {result.status_code}")
    print(result.text)
