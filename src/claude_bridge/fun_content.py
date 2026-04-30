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
    (
        "Middle finger",
        "      _\n     | |\n     | |\n  ___| |___\n |         |\n |         |\n  \\\\_______/\n    || ||\n    || ||\n   _|| ||_\n  |______|\n     /  \\\\\n    /    \\\\\n   |      |\n   |      |\n    \\\\    /\n     \\\\__/",
    ),
    ("Poop", "   ____\n  /    \\\\\n |      |\n |      |\n  \\\\____/\n   ||||\n   ||||"),
    (
        "Shark",
        '       /^\\\\_/^\n      / o o \\\\\n     (   "   )\n      \\\\~(*)~/\n       /   \\\\\n      /     \\\\\n    __/       \\\\__\n   /    \\\\     /   \\\\\n  /      \\\\   /     \\\\\n /        \\\\_/       \\\\\n(   ^   ^   ^   ^    )\n \\\\  (     @   @    )  /\n  \\\\                 /\n   \\\\               /\n    \\\\             /\n     \\\\           /\n      \\\\         /\n       \\\\       /\n        \\\\_____/',
    ),
]

ABSURD_STORIES = [
    "Bir zamanlar stack overflow kapatıldı. O gün 4 milyar developer aynı anda 'ama benim kodum çalışıyordu' dedi. Kimse inanmadı.",
    "GitHub'a push'ladığın kod aslında git'e gidiyor. Git de 'commit' diyor. Yani kodun bir tür manevi yolculuğa çıkıyor. Yayınlandığında artık o kod değil, ruh hali.",
    "Bilgisayar mühendisi, evindeki lambayı değiştirmek ister. Socket programming ile başlar, 3 saat sonra Kubernetes cluster kurar. Lamba hala yanmıyor.",
    "Junior developer: 'Bu kodda bug var.' Senior developer: 'Hayır, o bir feature.' Lead developer: 'Hayır, o kasten.' CTO: 'Hayır, o stratejik.' Sprint'in sonunda herkes haklı çıktı. Bug production'a gitti.",
    "Pair programming yaparken yanındaki kişi 'return False' yazdı. Sen içinden 'hayatın özeti bu' dedin. Gülümsetin dedi. Git commit mesajı: 'hayatin_ozeti.py'",
    "Product manager: 'Kullanıcılar bu butonu sevecek.' Developer butonu yazar. 2 hafta sonra PM: 'Ama her tıkladığında crash ediyor?' Developer: 'Evet, sevmek acıdır.'",
    "pip install hayallerim && python manage.py runserver --noreality=True",
    "Bug report: 'Uygulama karanlık modda çalışmıyor.' Developer: 'Ben de çalışmıyorum.' Issue closed: wontfix.",
    "Tech interview'da interviewer sorar: 'Binary tree'yi ters çevir. Aday der: 'rm -rf /'. Interviewer: 'Hired.'",
    "Bir developer gece 3'te koda bakar. Kod çalışıyor. Ama neden? Bilmiyor. Korkuyla yatağa döner. Ertesi sabah kod hala çalışıyor. Kimse sorarmış değil. Kimse sormaz.",
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
    "Bu kod benden değil, git blame'e bak.",
    "Bilgisayarım bugün Türkçe konuşmak istemedi, İngilizce çıktı.",
    "Bu bir bug değil, bu bir easter egg. Çok gizli.",
    "Normalde çalışıyordu. Demek ki normal değildi.",
    "Ben kod yazmıyorum, ben sanat yapıyorum. Sanat hata yapmaz. İzleyici hata yapar.",
    "Bu debug değil, bu keşif. Columbus da Amerika'ya gitmek istememişti.",
    "import antigravity dedim, bilgisayar uçtu. Yanlış anladım herhalde.",
    "RegEx yazarken bir türlü bitiremedim. 3 gündür aynı pattern'deyim. Yardım edin.",
    "merge conflict çıktı, her iki tarafı da kabul ettim. Sonuç: her iki taraf da bozuldu. Ama en azından adil.",
    "try: yazmak zorundayım. except: anlamak zorunda değilim. finally: kahve.",
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
        "Claude Bridge v0.1.0 yayınlandığında, bir test 417. kez çalıştı ve geçti. Sonunda insan gibi davranmaya başladı.",
        f"Bu bilgisayarın uptime'ı {rand.randint(1, 999)} gün. Ama senin oda süren {rand.randint(1, 48)} saat gibi görünüyor.",
        f"Bugün yazdığın kodun {rand.randint(2, 99)}%'ı stack overflow'dan geldi. Ama bunu kimse bilmeyecek.",
        "Claude Bridge şu an senin tüm dosyalarını okuyabilir. Ama endişelenme, gizli klasörünüzde ne olduğunu bilmiyoruz... henüz.",
        f"Dünya üzerinde yaklaşık {rand.randint(20, 30)} milyon developer var. Tam {rand.randint(1, 99)} tanesi şu an bu mesajı okuyor.",
        "Claude Bridge bir MCP server'dır. MCP = Model Context Protocol. Ya da Must Coffee Please. Bilemiyoruz.",
        "Bu tool'u çağırmak için harcadığın token'larla neler yapabilirdin? Mesela bir AI'a 'bana kahve getir' de. Aynı sonucu alırsın.",
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
