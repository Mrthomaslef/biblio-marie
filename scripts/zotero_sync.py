#!/usr/bin/env python3
"""
Zotero Web API v3 Synchronization & Export Engine for BiblioMarie
-----------------------------------------------------------------
- Automatically discovers Zotero userID from the API Key via GET /keys/{key}
- Creates collection "BiblioMarie — Pédiatrie & Infectiologie"
- Pushes journalArticle entries with:
  * Full bibliographic metadata (Title, Authors, Journal, Year, Volume, Issue, Pages, DOI, PMID)
  * Combined French Structured Summary + Original Abstract in abstractNote
  * Dedicated HTML Child Note with the Clinical Synthesis
  * Linked PDF attachment (only when a real open-access PDF exists)
- Usage:
    python3 scripts/zotero_sync.py                         -> exports only
    ZOTERO_API_KEY=xxxx python3 scripts/zotero_sync.py     -> exports + push to Zotero
- Also generates local 1-click import files:
  * exports/bibliomarie_zotero.ris
  * exports/bibliomarie_zotero.bib
  * exports/bibliomarie_csl.json
"""

import hashlib
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ARTICLES_JSON = BASE_DIR / "data" / "articles.json"
EXPORTS_DIR = BASE_DIR / "exports"
PDFS_DIR = BASE_DIR / "pdfs"
ZOTERO_STATE_FILE = BASE_DIR / "data" / "zotero_sync_state.json"

ZOTERO_API_BASE = "https://api.zotero.org"
COLLECTION_NAME = "BiblioMarie — Pédiatrie & Infectiologie"


def generate_static_exports(articles: list, github_pages_url: str = "https://mrthomaslef.github.io/biblio-marie"):
    """Generate .ris, .bib, and CSL-JSON files for 1-click Zotero import."""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. RIS Export
    ris_lines = []
    for art in articles:
        ris_lines.append("TY  - JOUR")
        ris_lines.append(f"TI  - {art['title']}")
        for author in art.get("authors_list", []):
            ris_lines.append(f"AU  - {author}")
        ris_lines.append(f"JO  - {art.get('journal', '')}")
        ris_lines.append(f"PY  - {art.get('year', '')}")
        if art.get("volume"):
            ris_lines.append(f"VL  - {art['volume']}")
        if art.get("issue"):
            ris_lines.append(f"IS  - {art['issue']}")
        if art.get("pages"):
            ris_lines.append(f"SP  - {art['pages']}")
        if art.get("doi"):
            ris_lines.append(f"DO  - {art['doi']}")
        pmid = art.get("pmid", "")
        pmcid = art.get("pmcid", "")
        combined_ab = (
            f"[RÉSUMÉ FR] {art.get('summary_fr', '')} "
            f"| Points clés : {' ; '.join(art.get('key_points_fr', []))} "
            f"| En pratique : {art.get('pratique_fr', '')} "
            f"|| [ABSTRACT ORIGINAL - EN] {art.get('abstract_en', '')}"
        )
        ris_lines.append(f"AB  - {combined_ab}")
        ris_lines.append(f"N1  - PMID: {pmid} | PMCID: {pmcid} | Rubrique: {art.get('category_label', '')}")
        if art.get("pdf_file"):
            ris_lines.append(f"L1  - {github_pages_url}/{art['pdf_file']}")
        ris_lines.append(f"UR  - https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
        for tag in art.get("tags", []):
            ris_lines.append(f"KW  - {tag}")
        ris_lines.append("ER  - ")
        ris_lines.append("")

    (EXPORTS_DIR / "bibliomarie_zotero.ris").write_text("\n".join(ris_lines), encoding="utf-8")

    # 2. BibTeX Export
    bib_lines = []
    for art in articles:
        pmid = art.get("pmid", "unknown")
        first_author_last = (art.get("authors_list", ["Author"])[0].split(",")[0].split()[0]).lower()
        first_author_last = "".join(c for c in first_author_last if c.isalnum())
        cite_key = f"{first_author_last}{art.get('year', '')}_{pmid}"
        bib_lines.append(f"@article{{{cite_key},")
        bib_lines.append(f"  title = {{{art['title']}}},")
        bib_lines.append(f"  author = {{{' and '.join(art.get('authors_list', []))}}},")
        bib_lines.append(f"  journal = {{{art.get('journal', '')}}},")
        bib_lines.append(f"  year = {{{art.get('year', '')}}},")
        if art.get("volume"):
            bib_lines.append(f"  volume = {{{art['volume']}}},")
        if art.get("issue"):
            bib_lines.append(f"  number = {{{art['issue']}}},")
        if art.get("pages"):
            bib_lines.append(f"  pages = {{{art['pages']}}},")
        if art.get("doi"):
            bib_lines.append(f"  doi = {{{art['doi']}}},")
        bib_lines.append(f"  pmid = {{{pmid}}},")
        bib_lines.append(f"  url = {{https://pubmed.ncbi.nlm.nih.gov/{pmid}/}},")
        if art.get("pdf_file"):
            bib_lines.append(f"  file = {{Full Text PDF:{github_pages_url}/{art['pdf_file']}:application/pdf}},")
        clean_ab = art.get("summary_fr", "").replace("{", "").replace("}", "")
        bib_lines.append(f"  abstract = {{{clean_ab}}}")
        bib_lines.append("}\n")

    (EXPORTS_DIR / "bibliomarie_zotero.bib").write_text("\n".join(bib_lines), encoding="utf-8")

    # 3. CSL-JSON Export
    csl_items = []
    for art in articles:
        pmid = art.get("pmid", "")
        authors_csl = []
        for a in art.get("authors_list", []):
            parts = a.rsplit(" ", 1)
            if len(parts) == 2:
                authors_csl.append({"family": parts[0], "given": parts[1]})
            else:
                authors_csl.append({"family": a})
        csl_items.append({
            "id": f"pmid-{pmid}",
            "type": "article-journal",
            "title": art.get("title", ""),
            "container-title": art.get("journal", ""),
            "volume": art.get("volume", ""),
            "issue": art.get("issue", ""),
            "page": art.get("pages", ""),
            "DOI": art.get("doi", ""),
            "PMID": pmid,
            "PMCID": art.get("pmcid", ""),
            "URL": art.get("article_url") or f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "abstract": f"[FR] {art.get('summary_fr', '')}\n\n[EN] {art.get('abstract_en', '')}",
            "author": authors_csl,
            "issued": {"date-parts": [[int(art.get("year", 2025))]]},
        })

    (EXPORTS_DIR / "bibliomarie_csl.json").write_text(
        json.dumps(csl_items, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[Exports] Generated RIS, BibTeX & CSL-JSON in {EXPORTS_DIR}")



def zotero(path, api_key, method="GET", payload=None):
    req = urllib.request.Request(
        f"{ZOTERO_API_BASE}{path}", method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Zotero-API-Version": "3", "Zotero-API-Key": api_key,
                 "Content-Type": "application/json", "User-Agent": "BiblioMarie/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read() or b"null")


def child_note_html(art):
    pts = "".join(f"<li>{html.escape(p)}</li>" for p in art.get("key_points_fr", []))
    return (f"<h2>{html.escape(art.get('title_fr', ''))}</h2>"
            f"<p><em>{html.escape(art.get('study_fr', ''))}</em></p>"
            f"<p>{html.escape(art.get('summary_fr', ''))}</p>"
            f"<h3>À retenir</h3><ul>{pts}</ul>"
            f"<h3>En pratique</h3><p>{html.escape(art.get('pratique_fr', ''))}</p>")


def sync_to_zotero(articles, api_key, github_pages_url="https://mrthomaslef.github.io/biblio-marie"):
    user_id = zotero(f"/keys/{urllib.parse.quote(api_key)}", api_key)["userID"]
    cols = zotero(f"/users/{user_id}/collections?limit=100", api_key)
    col = next((c["key"] for c in cols if c["data"]["name"] == COLLECTION_NAME), None)
    if not col:
        col = zotero(f"/users/{user_id}/collections", api_key, "POST", [{"name": COLLECTION_NAME}])["successful"]["0"]["key"]
    state = json.loads(ZOTERO_STATE_FILE.read_text()) if ZOTERO_STATE_FILE.exists() else {"synced_pmids": []}
    done = set(state.get("synced_pmids", []))
    for art in articles:
        if art["pmid"] in done:
            continue
        creators = []
        for a in art.get("authors_list", []):
            parts = a.rsplit(" ", 1)
            creators.append({"creatorType": "author", "lastName": parts[0], "firstName": parts[1]} if len(parts) == 2
                            else {"creatorType": "author", "name": a})
        item = {
            "itemType": "journalArticle", "title": art["title"], "creators": creators,
            "publicationTitle": art.get("journal", ""), "journalAbbreviation": art.get("journal_short", ""),
            "volume": art.get("volume", ""), "issue": art.get("issue", ""), "pages": art.get("pages", ""),
            "date": art.get("pub_date") or str(art.get("year", "")), "DOI": art.get("doi", ""),
            "url": art.get("article_url", ""), "abstractNote": art.get("abstract_en", ""),
            "extra": f"PMID: {art['pmid']}" + (f"\nPMCID: {art['pmcid']}" if art.get("pmcid") else ""),
            "collections": [col],
            "tags": [{"tag": t} for t in art.get("tags", [])] + [{"tag": art.get("category_label", "")}, {"tag": "BiblioMarie"}],
        }
        parent = zotero(f"/users/{user_id}/items", api_key, "POST", [item])["successful"]["0"]["key"]
        children = [{"itemType": "note", "parentItem": parent, "note": child_note_html(art), "tags": [{"tag": "Fiche FR"}]}]
        if art.get("pdf_file"):
            children.append({"itemType": "attachment", "parentItem": parent, "linkMode": "linked_url",
                             "title": f"PDF — PMID {art['pmid']}", "contentType": "application/pdf",
                             "url": f"{github_pages_url}/{art['pdf_file']}"})
        zotero(f"/users/{user_id}/items", api_key, "POST", children)
        done.add(art["pmid"])
        print(f"  ✓ Zotero : PMID {art['pmid']}")
    state.update({"synced_pmids": sorted(done), "collection_key": col, "user_id": user_id})
    ZOTERO_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


if __name__ == "__main__":
    arts = json.loads(ARTICLES_JSON.read_text(encoding="utf-8"))
    generate_static_exports(arts)
    key = os.environ.get("ZOTERO_API_KEY")
    if key:
        sync_to_zotero(arts, key)
