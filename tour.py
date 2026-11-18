from __future__ import annotations


TOUR_TOPICS = {
    "1": {
        "title": "Daily priorities",
        "body": (
            "Use /daily_brief to see birthdays, follow-ups due today, "
            "overdue follow-ups, and drafts waiting for review.\n\n"
            "Your automatic Daily Brief is informational only. It will not "
            "change client records or send emails."
        ),
    },
    "2": {
        "title": "Find and update clients",
        "body": (
            "Try:\n"
            "/list_clients\n"
            "/get_client Mary Lee\n\n"
            "Or say by voice:\n"
            '“Get client Mary Lee”\n'
            '“Update client Mary Lee, status touring”\n\n'
            "Close voice matches require confirmation before an update, and "
            "client deletion always requires confirmation."
        ),
    },
    "3": {
        "title": "Import clients from Excel",
        "body": (
            "1. Use /client_import_template to download the spreadsheet.\n"
            "2. Fill in the Clients sheet.\n"
            "3. Use /import_clients and upload the file.\n"
            "4. Review the preview before confirming.\n\n"
            "Nothing is imported until you confirm it."
        ),
    },
    "4": {
        "title": "Draft birthday emails",
        "body": (
            "Try:\n"
            "/generate_birthday_email Mary Lee\n\n"
            "The Copilot creates a personalized draft for review. It does not "
            "send the email automatically."
        ),
    },
    "5": {
        "title": "Revise and send drafts",
        "body": (
            "After creating a draft, send a voice message such as:\n"
            '“Make it warmer and shorter.”\n\n'
            "Then use /send_last_email to preview the recipient and final draft.\n"
            "Only /confirm_send_email sends it; /cancel_email cancels it."
        ),
    },
}


def format_tour_menu(agent_name: str = "") -> str:
    greeting = f"Hi {agent_name}!" if agent_name else "Hi!"
    return (
        f"{greeting} Here are five things I can help you with:\n\n"
        "1. Daily priorities\n"
        "2. Find and update clients\n"
        "3. Import clients from Excel\n"
        "4. Draft birthday emails\n"
        "5. Revise and send drafts\n\n"
        "Reply with a number from 1 to 5.\n"
        "Use /cancel_tour when you are finished."
    )


def format_tour_topic(selection: str) -> str | None:
    topic = TOUR_TOPICS.get(str(selection).strip())
    if topic is None:
        return None
    return (
        f"{topic['title']}\n\n"
        f"{topic['body']}\n\n"
        "Reply with another number from 1 to 5, or use /cancel_tour."
    )
