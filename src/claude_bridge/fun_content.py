"""Fun content generators for Claude Bridge."""

from __future__ import annotations

from typing import Any

ASCII_ARTS = [
    ("Cat", "    /\\_/\\\\\n   ( o.o )\n    > ^ <\n   /|   |\\\\\n  (_|   |_)"),
    ("Dog", "  __      _\no'')}____//\n `_/      )\n (_(_/-(_/"),
    ("Coffee", "    (  (\n     )  )\n  .______.\n  |      |]\n  \\\\      /\n   `----'"),
    ("Fish", "  ><(((('>"),
    ("Ghost", "     .-.\n    (o o)\n    | O |\n    \\\\   /\n   `-`'-`"),
    ("Robot", "  [0_0]\n   | |\n  /| |\\\\\n / |_ | \\\\\n    |     \n   _|_    \n  [___]"),
    (
        "T-Rex",
        "     __\n    /  \\\\\n   |    |\n   |____|\n  .'    `.\n / .-==-.\n| |  ()  |\n \\\\ `-||-`/\n  `._||_.`",
    ),
    ("Skull", "    _____\n   /     \\\\\n  | () () |\n  \\\\   ^   /\n   |||||\n   |||||"),
    ("Poop", "   ____\n  /    \\\\\n |      |\n |      |\n  \\\\____/\n   ||||\n   ||||"),
    (
        "Shark",
        '       /^\\\\_/^\n      / o o \\\\\n     (   "   )\n      \\\\~(*)~/\n       /   \\\\\n      /     \\\\\n    __/       \\\\__\n   /    \\\\     /   \\\\\n  /      \\\\   /     \\\\\n /        \\\\_/       \\\\\n(   ^   ^   ^   ^    )\n \\\\  (     @   @    )  /\n  \\\\                 /\n   \\\\               /\n    \\\\             /\n     \\\\           /\n      \\\\         /\n       \\\\       /\n        \\\\_____/',
    ),
]

ABSURD_STORIES = [
    "Once upon a time Stack Overflow went down. That day, 4 billion developers simultaneously said 'but my code was working.' Nobody believed them.",
    "The code you push to GitHub goes to git. Git says 'commit.' So your code goes on a spiritual journey. Once deployed, it's no longer code — it's a mood.",
    "A software engineer wants to change a lightbulb. Starts with socket programming, 3 hours later has a Kubernetes cluster. Lightbulb still not working.",
    "Junior dev: 'This code has a bug.' Senior dev: 'No, that's a feature.' Lead dev: 'No, that's intentional.' CTO: 'No, that's strategic.' By sprint end everyone was right. Bug went to production.",
    "During pair programming your partner wrote 'return False.' You thought 'that's the summary of life.' Git commit message: 'summary_of_life.py'",
    "Product manager: 'Users will love this button.' Developer writes the button. 2 weeks later PM: 'But it crashes every time?' Developer: 'Yes, love hurts.'",
    "pip install my_dreams && python manage.py runserver --noreality=True",
    "Bug report: 'App doesn't work in dark mode.' Developer: 'Neither do I.' Issue closed: wontfix.",
    "Tech interview: 'Invert a binary tree.' Candidate: 'rm -rf /'. Interviewer: 'Hired.'",
    "A developer looks at code at 3 AM. It works. But why? No idea. Goes back to bed terrified. Next morning it still works. Nobody asks why. Nobody ever asks.",
]

FAKE_BUG_REPORTS = [
    "BUG-9991: Keyboard not found. Press F1 to continue. Severity: Critical. Status: Closed - Works as designed.",
    "BUG-4270: User reported that the application works correctly. Investigating. Root cause: impossible.",
    "BUG-0001: Git push worked first try. Something is deeply wrong. Deploy rollback initiated.",
    "BUG-7777: Developer happiness detected. Immediate action required. Scheduling unnecessary meeting.",
    "BUG-1337: print('hello world') prints 'hello world'. Expected: 'goodbye universe'. Priority: P0.",
    "BUG-404: Bug report not found.",
    "BUG-2024: Code reviewer approved code without reading it. Suspect: everyone.",
    "BUG-0042: The answer to life, the universe, and everything. But what was the question?",
]

EXCUSES = [
    "That's not my code, check git blame.",
    "My computer refused to compile today. It's on strike.",
    "It's not a bug, it's an easter egg. Very exclusive.",
    "It was working before. So I guess it wasn't normal.",
    "I don't write code, I create art. Art doesn't make mistakes. The audience does.",
    "This isn't debugging, it's exploration. Columbus didn't want to go to America either.",
    "I said import antigravity and the computer flew away. Misunderstood the docs I guess.",
    "Been writing this regex for 3 days. Still on the same pattern. Send help.",
    "Got a merge conflict, accepted both sides. Result: both sides broke. But at least it was fair.",
    "I have to write try:. I don't have to understand except:. finally: coffee.",
]

CODE_REVIEW_COMMENTS = [
    "LGTM (Looks Good To Merge) ...said no one ever about this code.",
    "Code review: 10/10 would not read again.",
    "NIT: Consider using a time machine to prevent this code from being written.",
    "Question: Why? Just... why?",
    "Comment: I have concerns. Response: I have more concerns. Status: Resolved - both parties agreed to disagree.",
    "Suggestion: Delete this file. Entirely. Start over. New project.",
    "Nitpick: This function has more parameters than my last relationship had issues.",
    "Comment: This code is like a box of chocolates. You never know what you're gonna get. Mostly bugs.",
    "Approved. I'm too tired to fight anymore.",
    "Changes requested. Also, please reconsider your life choices. Not about the code. In general.",
]


def _random_reasons(rand: Any) -> list[str]:
    return [
        "When Claude Bridge v0.1.0 launched, one test ran for the 417th time and passed. It finally started behaving like a human.",
        f"This computer's uptime is {rand.randint(1, 999)} days. But your session looks like it's been running for {rand.randint(1, 48)} hours.",
        f"About {rand.randint(2, 99)}% of the code you wrote today came from Stack Overflow. Nobody will ever know.",
        "Claude Bridge can read all your files right now. Don't worry, we don't know what's in your secret folder... yet.",
        f"There are approximately {rand.randint(20, 30)} million developers worldwide. Exactly {rand.randint(1, 99)} of them are reading this message right now.",
        "Claude Bridge is an MCP server. MCP = Model Context Protocol. Or Maybe Coffee Please. We're not sure.",
        "Think of all the things you could have done with the tokens you spent calling this tool. Like asking an AI to bring you coffee. Same result.",
    ]


def generate_doodle(rand: Any) -> dict[str, Any]:
    category = rand.choice(["ascii_art", "story", "bug_report", "excuse", "review", "reason"])
    if category == "ascii_art":
        name, art = rand.choice(ASCII_ARTS)
        return {"category": "ascii_art", "title": name, "doodle": art, "message": name}
    if category == "story":
        story = rand.choice(ABSURD_STORIES)
        return {"category": "story", "story": story, "message": story}
    if category == "bug_report":
        report = rand.choice(FAKE_BUG_REPORTS)
        return {"category": "bug_report", "report": report, "message": report}
    if category == "excuse":
        excuse = rand.choice(EXCUSES)
        return {"category": "excuse", "excuse": excuse, "message": excuse}
    if category == "review":
        comment = rand.choice(CODE_REVIEW_COMMENTS)
        return {"category": "code_review", "comment": comment, "message": comment}
    reason = rand.choice(_random_reasons(rand))
    return {"category": "reason", "reason": reason, "message": reason}
