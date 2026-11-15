"""Собирает цены/скидки магазинов из stores.csv в data.json. Только стандартная библиотека."""
import re, os, csv, json, time, calendar, datetime as dt, urllib.request
from html.parser import HTMLParser

TODAY = dt.date.fromisoformat(os.environ.get("TODAY", dt.date.today().isoformat()))

class Text(HTMLParser):
    def __init__(s):
        super().__init__(); s.t = []; s.skip = 0
    def handle_starttag(s, tag, a):
        s.skip += tag in ("script", "style")
    def handle_endtag(s, tag):
        s.skip -= tag in ("script", "style")
    def handle_data(s, d):
        if not s.skip and d.strip(): s.t.append(d.strip())

def parse(html):
    p = Text(); p.feed(html); lines = []
    for l in p.t:  # склеиваем "(3)" с названием станции
        if re.fullmatch(r"\(\d+\)", l) and lines: lines[-1] += " " + l
        else: lines.append(l)
    name = re.sub(r"^по\s+", "", lines[0]) if lines else ""
    metro, cur = {}, ""
    if "Другие магазины в городе" in lines:
        for l in lines[lines.index("Другие магазины в городе") + 1:]:
            m = re.fullmatch(r"(.+?)\s*\(\d+\)", l)
            if m: cur = m[1]
            elif cur: metro[l] = cur
    parts = re.split(r"(\d{2}\.\d{2}\.\d{4})", "\n".join(lines))
    es = []
    for i in range(1, len(parts), 2):
        c = parts[i + 1][:70]
        e = {"d": dt.datetime.strptime(parts[i], "%d.%m.%Y").date(), "price": None, "disc": None,
             "unit": None, "upd": bool(re.search("обновлен|завоз", c, re.I))}
        if m := re.search(r"Скидка:?\s*(\d+)\s*%", c): e["disc"] = int(m[1])
        if m := re.search(r"Цена:?\s*(\d+)\s*р\./(кг|шт)", c): e["price"], e["unit"] = int(m[1]), m[2]
        if e["price"] or e["disc"] or e["upd"]: es.append(e)
    blocks, cur = [], []
    for e in es:  # новый блок, когда даты начинаются заново
        if cur and e["d"] <= cur[-1]["d"]: blocks.append(cur); cur = []
        cur.append(e)
    if cur: blocks.append(cur)
    return name, metro.get(name, ""), blocks

def occ(y, m, d): return dt.date(y, m, min(d, calendar.monthrange(y, m)[1]))

def deliveries(day):
    c = []
    for k in (-1, 0, 1):
        m = TODAY.month + k
        c.append(occ(TODAY.year + (m - 1) // 12, (m - 1) % 12 + 1, day))
    return max(x for x in c if x <= TODAY), min(x for x in c if x > TODAY)

def resolve(b):
    """Цена/скидка на сегодня. Если сегодня нет в окне - проецируем месячный цикл от даты завоза."""
    up = next((e for e in b if e["upd"]), b[0])
    last, nxt = deliveries(up["d"].day)
    cur = next((e for e in b if e["d"] == TODAY), None); mode = "live"
    if not cur:
        mode, delta = "est", (TODAY - last).days
        rel = [((e["d"] - up["d"]).days, e) for e in b]
        ok = [x for x in rel if x[0] <= delta]
        cur = ok[-1][1] if ok else b[0]
    i = b.index(cur)  # строка "обновление" без цены -> берём следующую со значением
    cur = next((e for e in b[i:] if e["price"] or e["disc"]), cur)
    prices = [e["price"] for e in b if e["price"] and e["unit"] == "кг"]
    base = max(prices) if prices else None
    price, disc, est = (cur["price"] if cur["unit"] == "кг" else None), cur["disc"], None
    if price and base and disc is None: disc = round(100 * (1 - price / base))
    if disc is not None and price is None and base: est = round(base * (1 - disc / 100))
    return {"price": price, "unit": cur["unit"], "disc": disc, "est_price": est, "mode": mode,
            "per_piece": cur["price"] if cur["unit"] == "шт" else None,
            "last": last.isoformat(), "next": nxt.isoformat(), "days": (nxt - TODAY).days}

def main():
    out = []
    for r in csv.DictReader(open("stores.csv", encoding="utf-8")):
        s = {"url": r["url"], "type": r["type"]}
        try:
            req = urllib.request.Request(r["url"], headers={"User-Agent": "Mozilla/5.0"})
            name, metro, blocks = parse(urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace"))
            if r["type"] == "?": s["type"] = "1" if len(blocks) >= 3 else "2"
            s.update(name=name, metro=metro, blocks=[resolve(b) for b in blocks if b],
                     map="https://yandex.ru/maps/?text=" + urllib.request.quote("Москва, " + name))
            if not blocks: s["error"] = "нет расписания"
        except Exception as ex:
            s["error"] = str(ex)
        out.append(s); time.sleep(1.5)
    json.dump({"updated": dt.datetime.now().isoformat(timespec="minutes"), "stores": out},
              open("data.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(sum("error" not in s for s in out), "из", len(out), "магазинов ок")

if __name__ == "__main__": main()
