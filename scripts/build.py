#!/usr/bin/env python3
"""
Construit la base BiblioMarie.

- Lit les fiches de lecture rédigées à la main (data/editorial.json) et les rubriques (data/categories.json)
- Récupère les métadonnées officielles sur Europe PMC (titre, auteurs, revue, date, DOI, PMCID, abstract)
  avec un cache local (data/pubmed_cache.json) pour ne pas tout re-télécharger
- Télécharge les PDF intégraux uniquement quand ils sont réellement en accès libre (pdfs/PMID_<pmid>.pdf)
- Écrit data/articles.json + data/embedded_data.js (chargé par index.html)
- Régénère les exports Zotero (exports/*.ris, *.bib, *.json)

Usage :  python3 scripts/build.py            (utilise le cache)
         python3 scripts/build.py --refresh  (re-télécharge les métadonnées)
"""

import html
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
PDFS = BASE / "pdfs"
CACHE = DATA / "pubmed_cache.json"
UA = {"User-Agent": "BiblioMarie/1.0 (mailto:biblio-marie@users.noreply.github.com)"}

MONTHS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin", "juillet",
             "août", "septembre", "octobre", "novembre", "décembre"]


def get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_meta(pmid):
    q = urllib.parse.urlencode({"query": f"EXT_ID:{pmid} AND SRC:MED", "format": "json", "resultType": "core"})
    d = json.loads(get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{q}"))
    res = d.get("resultList", {}).get("result", [])
    if not res:
        raise RuntimeError(f"PMID {pmid} introuvable sur Europe PMC")
    return res[0]


ALLOWED_TAGS = re.compile(r"</?(i|b|em|strong|sup|sub|p|h4|h3|br|span)[^>]*>", re.I)


def clean(text):
    """Retire les balises de mise en forme connues sans manger les « < 18 ans » du texte."""
    if not text:
        return ""
    text = html.unescape(html.unescape(text))
    text = re.sub(r"<h[34][^>]*>\s*(.*?)\s*</h[34]>", r"\n\n\1 — ", text, flags=re.I | re.S)
    text = re.sub(r"</?(i|b|em|strong|sup|sub)>", "", text, flags=re.I)
    text = ALLOWED_TAGS.sub(" ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r" ([,.;:])", r"\1", text)
    return text.strip()


def split_abstract(text):
    """Ajoute des retours à la ligne avant les intertitres collés (BackgroundX, MethodsY…)."""
    heads = ["Background", "Objectives?", "Importance", "Purpose", "Methods", "Design, setting, and participants",
             "Exposures?", "Interventions?", "Main outcomes and measures", "Results", "Findings",
             "Conclusions and relevance", "Conclusions?", "Interpretation", "Funding", "Trial registration",
             "CLINICAL TRIALS", "Background and objectives"]
    for h in heads:
        text = re.sub(rf"(?<=[\.\)\]a-z0-9%])\s*(?=({h})(?=[A-Z]))", "\n\n", text)
        text = re.sub(rf"^({h})(?=[A-Z])", r"\1 — ", text)
        text = re.sub(rf"\n\n({h})(?=[A-Z])", r"\n\n\1 — ", text)
    return text.strip()


def journal_case(name):
    small = {"of", "and", "the", "de", "in", "for", "on", "et"}
    name = re.sub(r"\s*\(.*?\)", "", name.split(" : ")[0]).replace("Lancet. ", "Lancet ").strip()
    if name == "Lancet":
        name = "The Lancet"
    if name.lower().startswith("euro surveillance"):
        name = "Eurosurveillance"
    words = name.split()
    return " ".join(w if (i and w.lower() in small) else (w[:1].upper() + w[1:]) for i, w in enumerate(words))


def short_authors(authors):
    if not authors:
        return ""
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        return f"{authors[0]}, {authors[1]}"
    return f"{authors[0]} et al."


def is_real_pdf(blob):
    return blob[:4] == b"%PDF" and len(blob) > 50_000


def pdf_candidates(meta):
    doi = meta.get("doi", "")
    urls = []
    if doi:
        try:
            uw = json.loads(get(f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email=bibliomarie@users.noreply.github.com", 15))
            for loc in [uw.get("best_oa_location") or {}] + (uw.get("oa_locations") or []):
                if loc.get("url_for_pdf"):
                    urls.append(loc["url_for_pdf"])
        except Exception:
            pass
        try:
            oa = json.loads(get(f"https://api.openalex.org/works/https://doi.org/{doi}", 15))
            for loc in oa.get("locations", []):
                if loc.get("pdf_url"):
                    urls.append(loc["pdf_url"])
        except Exception:
            pass
    if meta.get("pmcid"):
        urls.append(f"https://europepmc.org/articles/{meta['pmcid']}?pdf=render")
    return list(dict.fromkeys(urls))


def try_pdf(pmid, meta):
    """Ne garde que de vrais PDF éditeur / dépôt en accès libre (jamais de PDF généré)."""
    target = PDFS / f"PMID_{pmid}.pdf"
    if target.exists() and is_real_pdf(target.read_bytes()[:60_000]):
        return f"pdfs/{target.name}"
    if meta.get("isOpenAccess") != "Y" and not meta.get("pmcid"):
        # Unpaywall peut quand même connaître une version libre (dépôt, HAL…)
        pass
    tmp = Path(f"/tmp/bibliomarie_{pmid}.pdf")
    for url in pdf_candidates(meta):
        subprocess.run(["curl", "-sL", "--max-time", "25", "-A", "Mozilla/5.0 (Macintosh) BiblioMarie",
                        "-c", "/tmp/bibliomarie_cookies.txt", "-b", "/tmp/bibliomarie_cookies.txt",
                        url, "-o", str(tmp)], check=False)
        if tmp.exists() and is_real_pdf(tmp.read_bytes()):
            PDFS.mkdir(exist_ok=True)
            target.write_bytes(tmp.read_bytes())
            tmp.unlink()
            print(f"  ✓ PDF {pmid} ({target.stat().st_size // 1024} Ko)")
            return f"pdfs/{target.name}"
    if tmp.exists():
        tmp.unlink()
    return None


def reading_minutes(e):
    words = sum(len(str(x).split()) for x in [e["summary_fr"], e["pratique_fr"], *e["key_points_fr"]])
    return max(2, round(words / 180) + 1)


def main():
    refresh = "--refresh" in sys.argv
    editorial = json.loads((DATA / "editorial.json").read_text(encoding="utf-8"))
    cats = {c["id"]: c for c in json.loads((DATA / "categories.json").read_text(encoding="utf-8"))}
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}

    prev = json.loads((DATA / "articles.json").read_text(encoding="utf-8")) if (DATA / "articles.json").exists() else []
    done_pdf = {a["pmid"] for a in prev}  # PDF déjà cherché lors d'un build précédent
    articles = []
    for e in editorial:
        pmid = str(e["pmid"])
        if refresh or pmid not in cache:
            print(f"  ↓ Europe PMC {pmid}")
            cache[pmid] = fetch_meta(pmid)
            time.sleep(0.2)
        m = cache[pmid]
        ji = m.get("journalInfo", {}) or {}
        journal = ji.get("journal", {}) or {}
        authors = [a.get("fullName") or a.get("collectiveName", "")
                   for a in (m.get("authorList", {}) or {}).get("author", [])]
        authors = [a for a in authors if a]
        pub_date = m.get("firstPublicationDate") or m.get("electronicPublicationDate") or ""
        year, month = (int(pub_date[:4]), int(pub_date[5:7])) if len(pub_date) >= 7 else (int(m.get("pubYear", 0)), 0)
        doi = m.get("doi", "")
        pmcid = m.get("pmcid", "")
        cat = cats[e["category"]]
        pdf = try_pdf(pmid, m) if (refresh or "--pdf" in sys.argv or pmid not in done_pdf) else None
        if pdf is None and (BASE / f"pdfs/PMID_{pmid}.pdf").exists():
            pdf = f"pdfs/PMID_{pmid}.pdf"
        articles.append({
            "id": f"pmid-{pmid}",
            "pmid": pmid,
            "pmcid": pmcid,
            "doi": doi,
            "title": clean(m.get("title", "")).replace("\n", " ").rstrip("."),
            "title_fr": e["title_fr"],
            "authors_list": authors,
            "authors_short": short_authors(authors),
            "journal": journal_case(journal.get("title", "")),
            "journal_short": journal.get("isoabbreviation") or journal.get("medlineAbbreviation") or journal.get("title", ""),
            "year": year,
            "month_num": month,
            "pub_date": pub_date,
            "pub_date_fr": f"{MONTHS_FR[month]} {year}".strip() if month else str(year),
            "volume": ji.get("volume", ""),
            "issue": ji.get("issue", ""),
            "pages": m.get("pageInfo", ""),
            "pub_types": (m.get("pubTypeList", {}) or {}).get("pubType", []),
            "category_id": cat["id"],
            "category_label": cat["label"],
            "category_color": cat["color"],
            "audience": e.get("audience", ""),
            "study_fr": e.get("study_fr", ""),
            "summary_fr": e["summary_fr"],
            "key_points_fr": e["key_points_fr"],
            "pratique_fr": e["pratique_fr"],
            "tags": e.get("tags", []),
            "abstract_en": split_abstract(clean(m.get("abstractText", ""))),
            "reading_min": reading_minutes(e),
            "pdf_file": pdf,
            "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "doi_url": f"https://doi.org/{doi}" if doi else "",
            "pmc_url": f"https://europepmc.org/article/PMC/{pmcid}" if pmcid else "",
            "article_url": f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })

    articles.sort(key=lambda a: a["pub_date"], reverse=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    (DATA / "articles.json").write_text(json.dumps(articles, indent=1, ensure_ascii=False), encoding="utf-8")
    payload = {
        "built": time.strftime("%Y-%m-%d"),
        "categories": list(cats.values()),
        "articles": articles,
    }
    (DATA / "embedded_data.js").write_text(
        "window.BIBLIO = " + json.dumps(payload, ensure_ascii=False) + ";\n", encoding="utf-8")

    sys.path.insert(0, str(BASE / "scripts"))
    from zotero_sync import generate_static_exports
    generate_static_exports(articles)

    n_pdf = sum(1 for a in articles if a["pdf_file"])
    print(f"✓ {len(articles)} articles · {n_pdf} PDF en accès libre · {len(cats)} rubriques")


if __name__ == "__main__":
    main()
