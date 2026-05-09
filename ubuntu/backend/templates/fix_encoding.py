from ftfy import fix_text
import os

folder = "/home/ubuntu/backend/templates"

for filename in os.listdir(folder):
    if filename.endswith(".html"):
        path = os.path.join(folder, filename)

        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

        fixed = fix_text(text)

        with open(path, "w", encoding="utf-8") as f:
            f.write(fixed)

        print("fixed:", filename)
