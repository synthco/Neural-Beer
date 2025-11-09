

# 🍺 BeerFinder

BeerFinder — це утиліта для збирання зображень пива з відкритих джерел (наразі Bing Images, пізніше буде додано Instagram та інші).
Мета — сформувати сирий датасет пива в бокалах для подальшої обробки й тренування моделей комп’ютерного зору.

---

## 📂 Структура проєкту
``````
beerfinder/
  BeerFinder/
    __init__.py
    cli.py            # CLI інтерфейс
    config.py         # завантаження YAML, шляхи
    meta.py           # робота з метаданими (TODO)
    hashing.py        # утиліти хешування (TODO)
    utils.py          # допоміжні функції
    sources/
      __init__.py
      bing.py         # джерело Bing
      instagram.py    # (в процесі)
  configs/
    classes.yaml      # список класів пива
    queries.yaml      # пошукові квері для Bing / Instagram
  data/
    raw/              # сирі зображення
      bing/
      instagram/
    meta/             # CSV з метаданими
      bing.csv
      instagram.csv
  requirements.txt
  README.md
``````
---

## ⚙️ Як це працює

1. Конфігурація
	•	configs/classes.yaml
Містить список цільових класів (наприклад lager, ipa, stout, …).

``classes:
lager
wheat
ipa 
staut
porter 
sour``
`
---

Для кожного класу задано список пошукових запитів.
Зараз підтримується секція bing.

bing:
  lager:
    - "lager beer glass -bottle -can -logo"
    - "pilsner beer flute glass -bottle -can -mockup"
  stout:
    - "stout pint glass -bottle -can -logo"

2. Завантаження
	•	У CLI (BeerFinder/cli.py) реалізовано команду:

python -m BeerFinder.cli download-bing


	•	Вона:
	1.	читає класи та квері з configs/,
	2.	створює папки в data/raw/bing/<class>/,
	3.	качає зображення через icrawler (Bing),
	4.	відсікає дрібні файли (--min-side, за замовчуванням 512px),
	5.	зберігає метадані у data/meta/bing.csv.

Метадані включають:
	•	image_id (sha1 вмісту файлу),
	•	class (категорія),
	•	source (bing),
	•	orig_path, orig_filename,
	•	width, height,
	•	added_at (UTC-час).

⸻

🚀 Використання

Встановлення

git clone <repo>
cd beerfinder
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

Запуск Bing-завантаження

python -m BeerFinder.cli download-bing \
  --classes configs/classes.yaml \
  --queries configs/queries.yaml \
  --per-query 120 \
  --min-side 512

Параметри:
	•	--classes — шлях до YAML зі списком класів (за замовчуванням configs/classes.yaml)
	•	--queries — шлях до YAML із пошуковими запитами
	•	--per-query — скільки зображень качати на один запит (default 120)
	•	--min-side — мінімальна сторона зображення (default 512 px)

Приклад

[bing] lager: 2 queries × 120
[bing] lager: +150 images
[bing] stout: +80 images
...
[bing] done. meta → data/meta/bing.csv, total +480

### Завантаження з Pexels

1. **Отримай API key** у [Pexels Developers](https://www.pexels.com/api/).
2. Створи `secrets/pexels.yaml` (формат довільний, головне щоб ключ потрапив під `pexels.key`, приклад нижче):

   ```yaml
   pexels:
     key: "PEXELS_API_KEY"
   ```

3. Переконайся, що у `configs/queries.yaml` є секція `pexels:` із запитами для кожного класу (вже додано базові фрази на кшталт `"lager beer pint glass on bar"`).
4. Запусти команду:

   ```bash
   python -m BeerFinder.cli download-pexels \
     --classes configs/classes.yaml \
     --queries configs/queries.yaml \
     --secrets secrets/pexels.yaml \
     --per-query 60 \
     --min-side 512 \
     --preferred-size original \
     --orientation landscape
   ```

   Доступні ще `--max-pages`, `--orientation any|landscape|portrait|square`, `--locale en-US` тощо (див. `BeerFinder/cli.py`).

5. Результат:
   - зображення зберігаються у `data/raw/pexels/<class>/`;
   - метадані → `data/meta/pexels.csv`;
   - атрибуція (фотограф, посилання, замітка про ліцензію) → `data/meta/pexels_attribution.csv`.

   При повторних запусках файли не дублюються — `image_id` рахується як SHA1 контенту (`BeerFinder/sources/pexels.py`).

⸻

📊 Результат
	•	Зображення зберігаються у:

data/raw/bing/<class>/<query_name>/*.jpg


	•	Метадані у CSV:

data/meta/bing.csv



Приклад рядка:

image_id,class,source,source_url,orig_path,orig_filename,width,height,added_at
c1a9f0...,lager,bing,,data/raw/bing/lager/query1/img1.jpg,img1.jpg,1024,768,2025-09-29T12:34:56Z


⸻

🛠 Подальші кроки
	•	Додати завантаження з Instagram (download-instagram).
	•	Окремі скрипти препроцесингу:
	•	дедуплікація pHash,
	•	фільтр «beer / not beer»,
	•	нормалізація та ресайз,
	•	стабільний train/val/test split.

⸻

Хочеш, я в цьому README ще зразу додам секцію «FAQ / поширені проблеми» (типу «Bing заблокував, як обійти» / «чому CSV пустий»)?
