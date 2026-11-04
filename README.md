<img src="assets/icon.svg" width="64" height="64" alt="BiblioMarie">

# BiblioMarie — Infectiologie pédiatrique

Veille bibliographique pour Marie : les publications qui comptent en **pédiatrie générale**, **infectiologie pédiatrique** (communautaire et hospitalière) et **infectiologie adulte**. Chaque article est présenté avec sa revue, son **impact factor**, son schéma d'étude, une synthèse en français, l'abstract original, la référence Vancouver, le PDF quand il est en accès libre et l'envoi vers Zotero.

Site statique (un seul `index.html`), installable sur l'écran d'accueil du téléphone.

## Rubriques

| Rubrique | Contenu |
|---|---|
| Pédiatrie générale | Grands essais à fort impact clinique |
| Vaccins & infections communautaires | VRS (nirsévimab, vaccin maternel, clesrovimab), coqueluche, streptocoque A |
| Sepsis & réanimation | Critères de Phoenix, remplissage, oxygénation, sepsis néonatal |
| Immunodéprimés & fongiques | Neutropénie fébrile (ECIL-10), candidoses, isavuconazole |
| Infections ostéo-articulaires | GPIP 2023, Kingella, scores pronostiques, DAIR, pied diabétique |
| Respiratoire, ORL, peau & méninges | PediCAP, GPIP ORL et méningites, décolonisation S. aureus |
| Anti-infectieux & antibioprophylaxie | Durées courtes, procalcitonine, prophylaxie RVU et prothèses, fluoroquinolones |
| Infectiologie adulte | BALANCE, SNAP, CloCeBa, DOTS, ImmunoSep, PAC SPILF 2025 |

## Fichiers

- `data/editorial.json` : **les fiches rédigées** (titre français, résumé, points clés, « En pratique », tags). C'est le seul fichier à modifier à la main.
- `data/categories.json` : les rubriques.
- `data/impact_factors.json` : impact factors par revue (JIF 2024, Clarivate JCR édition 2025), indexés par abréviation ISO. Ajouter la revue ici quand un nouvel article vient d'un nouveau journal.
- `data/articles.json`, `data/embedded_data.js` : générés.
- `data/pubmed_cache.json` : cache des métadonnées Europe PMC.
- `pdfs/PMID_<pmid>.pdf` : uniquement de vrais PDF en accès libre (Unpaywall / OpenAlex / Europe PMC). Sinon, lien direct vers l'article.
- `exports/` : `bibliomarie_zotero.ris`, `.bib`, `bibliomarie_csl.json`.

## Ajouter un article

1. Ajouter une entrée dans `data/editorial.json` (`pmid`, `category`, `audience`, `design`, `title_fr`, `study_fr`, `summary_fr`, `key_points_fr`, `pratique_fr`, `tags`).
2. Reconstruire :

```bash
python3 scripts/build.py          # métadonnées, PDF libres, données du site, exports Zotero
python3 scripts/build.py --refresh  # forcer la mise à jour des métadonnées et des PDF
```

## Zotero

- Depuis le site : lien « Envoyer la bibliothèque vers Zotero » en bas de page, ou « Zotero » en bas de chaque article. La clé API reste dans le navigateur.
- En ligne de commande :

```bash
ZOTERO_API_KEY="votre_cle" python3 scripts/zotero_sync.py
```

Les articles arrivent dans la collection **BiblioMarie — Pédiatrie & Infectiologie**, avec la fiche française en note enfant et le PDF libre en pièce jointe.
