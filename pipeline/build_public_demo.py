"""Public demo built from the QABAT reader and original sample course."""
import argparse
import json
import re
from pathlib import Path
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("out", type=Path, help="Папка для статического демо")
out = parser.parse_args().out
web = Path(__file__).resolve().with_name("web")
(out / "course").mkdir(parents=True, exist_ok=True)
shutil.copytree(web, out / "course" / "web", dirs_exist_ok=True)

topics = [
    ("Пористость", "Porosity", "Пористость — доля объёма пор в общем объёме породы.",
     "Что показывает значение пористости 20%?", ["Поры занимают пятую часть объёма", "Порода состоит на 20% из кварца", "Вода течёт со скоростью 20 м/с"]),
    ("Проницаемость", "Permeability", "Проницаемость характеризует способность породы пропускать флюид через связанные поры.",
     "Почему высокая пористость не гарантирует высокую проницаемость?", ["Поры могут не сообщаться друг с другом", "Высокая пористость всегда уменьшает размер образца", "Проницаемость зависит только от цвета породы"]),
    ("Водонасыщенность", "Water saturation", "Водонасыщенность — доля порового объёма, занятая водой.",
     "Какой объём берут за 100% при расчёте водонасыщенности?", ["Поровый объём", "Весь объём породы", "Объём минерального скелета"]),
]
layer = {
    "schema_version": "1.0", "offline_demo": True,
    "chapter": {"id": "qabat-public-v1", "title": "Основы свойств пород", "author": "QABAT",
                "book": "Демонстрационный курс", "pages": [1, 3], "pdf": ""},
    "parts": [{"id": "intro", "title": "Свойства коллектора"}], "nodes": [], "tasks": [], "glossary": [],
}
for n, (name, en, explanation, question, options) in enumerate(topics, 1):
    node = f"demo-{n}"
    layer["nodes"].append({"id": node, "order": n, "part_id": "intro", "title": name, "pages": [n, n],
                           "minutes": 2, "claims": [],
                           "summary": [{"text": explanation, "by": "model", "claims": []}]})
    layer["glossary"].append({"id": node+"-term", "node_id": node, "term": name, "en": en, "definition": explanation})
    position = (n - 1) % len(options)
    options.insert(position, options.pop(0))
    layer["tasks"].append({"id": node+"-question", "node_id": node, "type": "single", "question": question, "options": options,
                           "answer": position, "explanation": explanation})

template = (web / "index.html").read_text(encoding="utf-8")
(out / "course" / "index.html").write_text(template.replace("__LAYER__", json.dumps(layer, ensure_ascii=False)), encoding="utf-8")

home = (web / "home.html").read_text(encoding="utf-8")
home = re.sub(r'  <script src="/course/web/home\.js[^"]*" defer></script>', '',
              home.replace('/assets/', '/course/web/'))
start = home.index('    <div class="homeLayout">')
end = home.index('  </main>', start)
home = home[:start] + '''    <section class="spaceCard" style="margin-top:16px">
      <h2>Демонстрационный курс</h2>
      <p>Открой уроки о свойствах пород, проверь термины в поиске и попробуй экзамен с таймером.</p>
      <p class="muted">Загрузка документов и новые задания с ИИ доступны в серверной версии QABAT.</p>
      <a href="/course/index.html">Открыть курс</a>
    </section>
''' + home[end:]
home = home.replace('</body>', '''<script>
const theme = document.getElementById('theme');
const setTheme = dark => {
  document.documentElement.dataset.dark = dark;
  theme.setAttribute('aria-pressed', dark);
};
window.addEventListener('DOMContentLoaded', () => {
  startCoverAnimation();
  setTheme(readGeoTheme());
  theme.onclick = () => {
    const dark = !readGeoTheme();
    writeGeoTheme(dark);
    setTheme(dark);
  };
});
</script>
</body>''')
(out / "index.html").write_text(home, encoding="utf-8")
