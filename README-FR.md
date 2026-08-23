# ArchivTrace

**Assistant de recherche documentaire fondé sur la citation** — collecter, analyser et synthétiser des archives numériques avec sources verbatim obligatoires.

> **Languages:** [English](README.md) · [Français](README-FR.md)

## Introduction

### À qui s'adresse cet outil ?

Cet outil s'adresse à **toute personne** qui veut creuser un sujet qui la passionne — généalogie, histoire locale, un quartier, une personnalité, un événement — à partir de **sources numériques** (presse ancienne, fonds d'archives en ligne, catalogues institutionnels…).

Vous pouvez être **totalement débutant** en informatique : pas besoin d'être développeur ni chercheur professionnel. Il suffit de savoir ouvrir un **terminal** (invite de commandes) et de copier-coller quelques commandes. Les historiens, archivistes et documentalistes y trouvent aussi un assistant de collecte ; les curieux et les passionnés, un moyen d'aller plus loin que la simple navigation sur un site d'archives.

### Quel problème résout-il ?

Lors d'une recherche sur un sujet qui vous intéresse — par exemple *« Oradour dans ma région »*, ou le nom d'un ancêtre dans la presse locale — vous devez habituellement :

1. interroger plusieurs sites d'archives un par un ;
2. ouvrir des visionneuses, télécharger des PDF ;
3. lire des dizaines de pages pour repérer les passages utiles ;
4. noter à la main ce qui retient votre attention ;
5. recomposer le tout avant d'écrire ce que vous avez découvert.

Cet outil **automatise la collecte et la première analyse** : vous donnez un **mot-clé**, il va chercher les documents, en extrait le texte, repère les passages pertinents et — si vous le souhaitez — fait analyser le contenu par une **LLM**. Par défaut c'est un modèle **local** via [Ollama](https://ollama.com) sur votre machine. Vous pouvez aussi configurer des fournisseurs cloud (`openai`, `openrouter`, `perplexity`) dans `config.json` / `--llm` ; dans ce cas les prompts partent vers ces API.

### Ce que vous obtenez concrètement

À la fin, vous disposez de **fichiers texte structurés** (format Markdown, extension `.md`) que vous pouvez ouvrir avec n'importe quel éditeur de texte, Visual Studio Code, ou une application de notes. Ces fichiers servent à la fois de :

- **carnet de recherche** (trace de ce qui a été trouvé, où, et comment) ;
- **matière première** pour rédiger un texte : article, billet de blog, note personnelle, exposé… ;
- **contexte** à fournir à une LLM (locale ou en ligne) en lui disant : *« Rédige un texte à partir de ce dossier. »*

Trois types de documents sont produits :

| Fichier | Rôle |
|---|---|
| `work/research/…_collecte.md` | Tout ce qui a été trouvé : sources, extraits, analyses |
| `work/synthesys/…_synthese.md` | Vue d'ensemble : faits, chronologie, lacunes |
| `work/synthesys/…_contexte.md` | Dossier prêt pour rédiger un texte (article, note, billet…) |

### Ce dont vous avez besoin (en résumé)

| Élément | À quoi ça sert | Où l'obtenir |
|---|---|---|
| **Python 3.11+** | Fait tourner l'outil | [python.org](https://www.python.org/downloads/) |
| **Ollama** | IA locale pour l'analyse et la synthèse | [ollama.com](https://ollama.com) |
| **Ce dépôt** | Le programme lui-même | Répertoire de votre choix (ex. `archivtrace`) |
| **Une connexion Internet** | Pour interroger les sites d'archives | — |

> **Vocabulaire utile**
> - **Markdown (`.md`)** : format texte simple, lisible tel quel, avec titres et listes.
> - **LLM / modèle** : programme d'IA génératif. Par défaut deux modèles Ollama locaux — `gemma4:26b` pour l'extraction documentaire, `qwen3.5` pour la synthèse longue (voir Configuration).
> - **Terminal** : fenêtre où l'on tape des commandes (PowerShell sur Windows, bash sur Linux/WSL).
> - **Mot-clé / requête** : le terme que vous cherchez, ex. `valmontagne`.

### Principe fondateur

Le **Markdown est l'unique sortie métier** de cet outil : pas de tableur Excel, pas de base de données à administrer. Chaque étape produit un document structuré, relisible et réutilisable.

---

## Installation pas à pas

L'installation se fait **une seule fois** sur votre poste. Prévoyez une demi-heure la première fois (téléchargement du modèle d'IA inclus).

**Comment lire ce guide :** à chaque étape, repérez la colonne qui correspond à **votre** environnement et suivez uniquement celle-ci.

| Environnement | Quand l'utiliser | Terminal à ouvrir |
|---|---|---|
| **Windows** | PC Windows, sans WSL | **PowerShell** (menu Démarrer → taper « PowerShell ») |
| **Linux** | PC ou serveur Linux natif (Ubuntu, Debian…) | **Terminal** (`Ctrl+Alt+T` sur Ubuntu) |
| **WSL** | Windows, mais vous préférez les commandes Linux | **Ubuntu** (menu Démarrer, après activation de WSL) |

> **WSL**, c'est quoi ? C'est un **Linux intégré à Windows**. Les fichiers de votre disque C: sont accessibles depuis WSL sous `/mnt/c/…`. Si vous hésitez entre Windows et WSL sur un PC Windows, choisissez **Windows** (plus simple) ou **WSL** si vous êtes à l'aise avec Linux.

---

### Étape 0 — Créer le répertoire du projet

Créez un dossier pour accueillir le programme, par exemple `archivtrace` (copie depuis une clé USB, téléchargement, clonage Git…).

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| Où créer le dossier | Ex. `C:\Users\VotreNom\archivtrace` | Ex. `~/archivtrace` | Ex. `/mnt/c/Users/VotreNom/archivtrace` (sur le disque Windows) |
| Ouvrir un terminal **dans** ce dossier | Explorateur → clic droit sur le dossier → « Ouvrir dans le terminal », ou `cd C:\Users\...\archivtrace` | `cd ~/archivtrace` | `cd /mnt/c/Users/VotreNom/archivtrace` |
| Vérifier que les fichiers sont là | `dir` — vous devez voir `collecte.py`, `README.md`, `README-FR.md`, `requirements.txt` | `ls` — idem | `ls` — idem |

---

### Étape 1 — Installer Python 3.11 ou plus récent

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| Comment installer | Installateur sur [python.org/downloads](https://www.python.org/downloads/) — **cochez « Add Python to PATH »** | `sudo apt update` puis `sudo apt install python3 python3-pip python3-venv` | **D'abord** activer WSL (voir encadré ci-dessous), **puis** les mêmes commandes que Linux |
| Vérifier | `python --version` | `python3 --version` | `python3 --version` |
| Résultat attendu | `Python 3.11.x` ou `3.12.x` | idem | idem |

**Windows (PowerShell) — vérification :**
```powershell
python --version
```

**Linux et WSL — installation et vérification :**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
python3 --version
```

> **WSL — première activation (une seule fois, avant l'étape 1)**  
> Dans PowerShell **en administrateur** sur Windows : `wsl --install`  
> Redémarrez le PC, puis ouvrez **Ubuntu** depuis le menu Démarrer. Les étapes suivantes se font dans ce terminal Ubuntu.

---

### Étape 2 — Installer Ollama et les modèles d'IA

Ollama fait tourner l'intelligence artificielle **sur votre machine**. Téléchargements recommandés (~24 Go au total, une seule fois) :

| Modèle | Rôle | Taille approx. |
|---|---|---|
| `gemma4:26b` | Extraction d'affirmations sourcées (JSON + citations) | ~17 Go |
| `qwen3.5` | Synthèse à long contexte | ~6,6 Go |
| `llama3.2` (optionnel) | Repli si un modèle de tâche manque | ~2 Go |

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| Installer Ollama | Installateur sur [ollama.com/download](https://ollama.com/download) — icône dans la barre des tâches une fois lancé | `curl -fsSL https://ollama.com/install.sh \| sh` | **Option A (recommandée)** : installez Ollama sur **Windows** (installateur) — accessible depuis WSL via `localhost` · **Option B** : script Linux dans le terminal Ubuntu |
| Télécharger les modèles | `ollama pull gemma4:26b` puis `ollama pull qwen3.5` | idem | idem |
| Vérifier | `ollama list` — les deux modèles doivent apparaître | idem | idem |

**Commandes communes (Windows PowerShell, Linux ou WSL) :**
```bash
ollama pull gemma4:26b
ollama pull qwen3.5
ollama pull llama3.2   # repli optionnel
ollama list
```

> **WSL + Ollama sur Windows (option A)** : laissez `config.json` avec `"host": "http://localhost:11434"` dans le bloc `llm` (ou la clé plate `"ollama_host"`) — cela fonctionne depuis WSL sans configuration supplémentaire.

---

### Étape 3 — Installer le programme (environnement Python)

Placez-vous dans le répertoire du projet (étape 0), puis créez un **environnement virtuel** (`.venv`) et installez les dépendances.

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| Aller dans le projet | `cd C:\chemin\vers\archivtrace` | `cd ~/chemin/vers/archivtrace` | `cd /mnt/c/Users/VotreNom/.../archivtrace` |
| Créer l'environnement | `python -m venv .venv` | `python3 -m venv .venv` | `python3 -m venv .venv` |
| Activer l'environnement | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` | `source .venv/bin/activate` |
| Installer les paquets | `pip install -r requirements.txt` | idem | idem |
| Client Ollama partagé | `pip install -e ..\shared\ollama_shared` | `pip install -e ../shared/ollama_shared` | `pip install -e ../shared/ollama_shared` |
| Signe que c'est bon | le prompt affiche `(.venv)` au début de la ligne | idem | idem |

**Windows (PowerShell) :**
```powershell
cd C:\chemin\vers\archivtrace
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e ..\shared\ollama_shared
```

**Linux :**
```bash
cd ~/chemin/vers/archivtrace
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ../shared/ollama_shared
```

**WSL (terminal Ubuntu) :**
```bash
cd /mnt/c/Users/VotreNom/chemin/vers/archivtrace
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ../shared/ollama_shared
```

> **Windows — si PowerShell refuse d'activer le venv** (« exécution de scripts désactivée »), lancez une fois :  
> `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`

---

### Étape 4 — Vérifier que tout fonctionne

Test sans téléchargement réel de PDF (`--dry-run`).

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| Activer l'environnement | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` | `source .venv/bin/activate` |
| Lancer le test | `python collecte.py --query "valmontagne" --connector numelyo --dry-run --max-results 2` | idem (`python3` si `python` absent) | idem |
| Résultat attendu | un fichier apparaît dans `work\research\` | un fichier apparaît dans `work/research/` | idem |

---

### Première utilisation — le cycle en 4 commandes

À **chaque nouvelle ouverture** de terminal, réactivez d'abord l'environnement :

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| Activer l'environnement | `.\.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` | `source .venv/bin/activate` |

Puis exécutez (identique sur les trois environnements) :

```bash
# 1. Collecter les documents sur le mot-clé (un fichier par site)
python collecte.py --query "valmontagne" --connector numelyo --max-results 5

# 2. Analyse sémantique par l'IA, document par document — plus lent
python analyse.py --input work/research/2026-06-28_valmontagne_numelyo_collecte.md --only-matches

# 3. Synthèse multi-sites (fusionne tous les connecteurs pour le mot-clé)
python synthesize.py --query "valmontagne"

# 4. Dossier pour rédiger votre texte
python synthesize.py --query "valmontagne" --mode contexte
```

Les résultats sont dans les dossiers **`work/research/`** et **`work/synthesys/`**. Ouvrez les fichiers `.md` avec votre éditeur préféré.

> **Conseil** : commencez toujours par `--dry-run` ou `--max-results 2` pour un essai rapide sans télécharger trop de PDF.

### Options avancées (facultatif)

| | **Windows** | **Linux** | **WSL** |
|---|---|---|---|
| OCR optionnel (**PaddleOCR**) | `pip install paddlepaddle paddleocr` | idem | idem |
| Exemple d'utilisation | `python analyse.py --input work/research/…_collecte.md --only-matches --enable-ocr` | idem | idem |

---

## Table des matières

**Pour démarrer**
- [Introduction](#introduction)
- [Installation pas à pas](#installation-pas-à-pas) (Windows, Linux, WSL)

**Documentation technique**

1. [Vue d'ensemble du flux](#vue-densemble-du-flux)
2. [Architecture du projet](#architecture-du-projet)
3. [Modèles de données](#modèles-de-données)
4. [Le pipeline de collecte (étape par étape)](#le-pipeline-de-collecte-étape-par-étape)
5. [Connecteurs (sources)](#connecteurs-sources)
6. [Stratégies de téléchargement](#stratégies-de-téléchargement)
7. [Extraction de texte et OCR](#extraction-de-texte-et-ocr)
8. [Matching de mots-clés (mécanique)](#matching-de-mots-clés-mécanique)
9. [Extraction d'idées par LLM (Ollama)](#extraction-didées-par-llm-ollama)
10. [Synthèse et contexte de rédaction](#synthèse-et-contexte-de-rédaction)
11. [Fichiers Markdown produits](#fichiers-markdown-produits)
12. [Configuration](#configuration)
13. [Référence installation (résumé)](#référence-installation-résumé)
14. [Utilisation — CLI](#utilisation--cli)
15. [Gateway LLM et package Ollama partagé](#gateway-llm-et-package-ollama-partagé)
16. [Tests](#tests)
17. [Ajouter une nouvelle source](#ajouter-une-nouvelle-source)
18. [Exemple complet](#exemple-complet)

---

## Vue d'ensemble du flux

```
┌─────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 1 — COLLECTE                         collecte.py                     │
│                                                                         │
│  mot-clé ──► connecteur ──► recherche HTML/API sur le site d'archives │
│                    │                                                    │
│                    ▼                                                    │
│              candidats (titres, URLs, IDs)                               │
│                    │                                                    │
│                    ▼                                                    │
│              stratégie de téléchargement ──► PDF local (work/downloads/)     │
│                    │                                                    │
│                    ▼                                                    │
│              extraction texte (PDF natif ou PaddleOCR)                   │
│                    │                                                    │
│                    └──► matcher mécanique (extraits autour du mot-clé)  │
│                    │                                                    │
│                    ▼                                                    │
│         work/research/{date}_{sujet}_{connector}_collecte.md                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 2 — ANALYSE                          analyse.py                  │
│                                                                         │
│  Relit le Markdown + PDF locaux ──► tâche LLM « extraction »            │
│  (modèle défaut : gemma4:26b — affirmations JSON + citations verbatim)  │
│                    │                                                    │
│                    ▼                                                    │
│         work/research/{date}_{sujet}_{connector}_collecte.md  (enrichi)     │
│         (section « Idées extraites (LLM) » par source)                  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 3 — SYNTHÈSE                         synthesize.py               │
│                                                                         │
│  Relit le Markdown de collecte ──► tâche LLM « synthesis »              │
│  (modèle défaut : qwen3.5 — narration long contexte + blocs structurés) │
│                    │                                                    │
│                    ▼                                                    │
│         work/synthesys/{date}_{sujet}_synthese.md                             │
│         (note de recherche : faits, chronologie, sources, lacunes)      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  ÉTAPE 4 — CONTEXTE DE RÉDACTION            synthesize.py --mode contexte│
│                                                                         │
│  Même famille de modèle que la synthèse ──► dossier de rédaction        │
│                    │                                                    │
│                    ▼                                                    │
│         work/synthesys/{date}_{sujet}_contexte.md                             │
│         (prêt à alimenter une LLM ou un humain pour écrire l'article)  │
└─────────────────────────────────────────────────────────────────────────┘
```

**Deux tâches LLM (même gateway, modèles différents) :**

| Moment | Commande | Module | Rôle de tâche | Modèle Ollama défaut |
|---|---|---|---|---|
| Après la collecte | `analyse.py` | `llm_idea_extractor.py` | `extraction` | `gemma4:26b` |
| Après l'analyse | `synthesize.py` | `synthesizer.py` | `synthesis` | `qwen3.5` |

Routage : `pipeline/llm_task_models.py` (`get_model_for_task`). Un seul chemin d'appel (`LlmGateway`) ; le modèle, le mode thinking et le fallback sont choisis par tâche. Modèle manquant → avertissement + `llm.fallback_model` (défaut `llama3.2`), sans crash. Détails : [Configuration — Multi-modèles Ollama](#multi-modèles-ollama-routage-par-tâche).

Le matcher mécanique (`keyword_matcher.py`) reste utile : il localise vite les pages et passages contenant le mot-clé, et sert d'aide à la LLM.

### Comment ce README décrit l'architecture (vs le code)

| Couche | Ce qu'elle documente | Ce qu'elle ne duplique **pas** |
|---|---|---|
| **Ce README** | Étapes, contrats (citation obligatoire), config, CLI, module propriétaire | Signatures de fonctions, listes de paramètres, algorithmes internes |
| **Docstrings modules / fonctions** | *Comment* un composant fonctionne | Positionnement produit / guides d'install |
| **`AGENTS.md` + `.cursor/skills/`** | Conventions agents (chemins, venv, OCR, entrée LLM) | Tutoriels utilisateur |

Privilégier un **flux + tableau de responsabilités + contrat de config**. Quand le comportement change, mettre à jour le flux/tableau ici ; garder le détail d'implémentation dans les docstrings Python.

---

## Architecture du projet

```
archivtrace/
│
├── work/                        # Artefacts hors code
│   ├── research/                # Collecte + analyse Markdown
│   ├── downloads/               # Cache PDF / images
│   └── synthesys/               # Synthèses / contextes
│
├── collecte.py                  # CLI collecte — ne contient pas de logique métier
├── analyse.py                   # CLI analyse LLM (tâche : extraction)
├── synthesize.py                # CLI synthèse / contexte (tâche : synthesis)
├── synthesize.py                # Synthèse corpus (+ option --reverify)
├── config.py                    # Objet Config typé (dataclass)
├── config.json                  # Paramètres LLM / pipeline (JSONC ; bloc llm imbriqué)
├── models.py                    # Tous les modèles de données (dataclasses + enums)
│
├── connectors/                  # Une source d'archives = un package
│   ├── __init__.py              # REGISTRY + build_connector()
│   ├── base.py                  # Classe abstraite Connector
│   ├── numelyo/                 # Numelyo / BM Lyon
│   │   ├── connector.py
│   │   └── parsing.py
│   ├── archives_rhone/          # Archives du Rhône
│   │   ├── connector.py
│   │   └── parsing.py
│   ├── archives_map/            # MPP / Archiv'MH (Ligeo)
│   │   ├── connector.py
│   │   └── parsing.py
│   └── catalog_html/            # Template générique HTML
│       └── connector.py
│
├── strategies/                  # Comment télécharger un document résolu
│   ├── base.py                  # Classe abstraite DownloadStrategy
│   ├── direct_download.py       # URL directe vers un fichier
│   ├── viewer_to_pdf.py         # Viewer → PDF (Numelyo : ISSUE_PDF)
│   ├── session_cookie.py        # Session PHPSESSID puis téléchargement
│   ├── html_scrape.py           # Page HTML → lien vers le fichier
│   ├── api_query.py             # API JSON/REST
│   └── browser_automation.py    # Playwright (dernier recours, optionnel)
│
├── pipeline/                    # Cœur métier — indépendant des sources
│   ├── collector.py             # Orchestrateur : search → … → CollectionRun
│   ├── text_extractor.py        # PDF → texte page par page
│   ├── ocr_extractor.py         # Fallback OCR (PaddleOCR, optionnel)
│   ├── keyword_matcher.py       # Repérage mécanique du mot-clé + contexte
│   ├── llm_idea_extractor.py    # Analyse sémantique par document (extraction)
│   ├── llm_gateway.py           # Point d'entrée LLM unique (Ollama + APIs compatibles)
│   ├── llm_task_models.py       # Tâche → modèle / thinking / fallback
│   ├── llm_validation_stats.py  # Compteurs de validation JSON par modèle
│   ├── llm_call_log.py          # Journal JSONL rotatif (télémétrie / coûts)
│   ├── llm_client.py            # Réexports depuis llm_gateway (compat)
│   ├── prompts.py               # Charge les prompts versionnés depuis prompts/
│   ├── prompt_loader.py         # Chargeur de fichiers de prompts
│   ├── prompt_schemas.py        # Validation Pydantic des sorties JSON LLM
│   ├── grounded_claims.py       # Filtre déterministe : affirmations confirmées → synthèse
│   ├── source_classifier.py     # Classification source probante / non probante
│   ├── source_criticism.py      # Priors de critique externe (inspiration Gottschalk)
│   ├── synthesis_structure.py   # Structures catalogue / chronologie / thèmes
│   ├── nli_verifier.py          # Contrôle NLI optionnel sur faits établis
│   ├── cove_verifier.py         # Chain-of-Verification optionnelle
│   ├── verification_pipeline.py # Combine NLI + CoVe
│   ├── analyse_policy.py        # Décision reprise / filtres analyse
│   ├── markdown_format.py       # Format Markdown canonique (marqueurs)
│   ├── markdown_reporter.py     # CollectionRun → Markdown de collecte
│   ├── markdown_patcher.py      # Injection / remplacement sections LLM
│   ├── markdown_reader.py       # Markdown de collecte → structure relue
│   ├── collection_analyzer.py   # Boucle analyse (OCR + LLM + persistance)
│   └── synthesizer.py           # Collecte relue → synthèse ou contexte
│
├── prompts/                     # Prompts LLM versionnés (XML ; dernière = plus haut vN)
│   ├── analyze_document.v2.xml.txt
│   ├── synthesize_claims.v2.xml.txt
│   ├── classify_source.v1.xml.txt
│   └── article_context.v1.xml.txt
├── utils/
│   ├── http.py                  # Client HTTP (timeout, delay, retries, UTF-8)
│   ├── strings.py               # Normalisation, slug, variantes de mot-clé
│   ├── dates.py                 # run_id, horodatages
│   ├── files.py                 # Écriture sûre, chemins
│   └── app_config.py            # config.json → Config (CLI > json > défauts)
│
├── tests/                       # Tests unitaires et d'intégration offline
├── work/research/               # Sortie métier : Markdown de collecte/analyse
├── work/downloads/              # Cache des PDF téléchargés (gitignored)
├── work/synthesys/              # Synthèses et contextes
├── queries.txt                  # Exemple de fichier de requêtes multiples
├── requirements.txt
└── pyrightconfig.json           # Résolution du package ollama_shared pour le linter
```

Package externe partagé (sibling) :

```
../shared/ollama_shared/         # Client Ollama factorisé (YouTube2Post, etc.)
```

### Séparation des responsabilités

| Couche | Fichiers | Responsabilité | Connaît la source ? |
|---|---|---|---|
| **CLI** | `collecte.py`, `analyse.py`, `synthesize.py` | Arguments, config, câblage | Non |
| **Connecteur** | `connectors/*.py` | URLs, recherche, parsing, résolution | **Oui** |
| **Stratégie** | `strategies/*.py` | Télécharger un fichier local | Partiellement |
| **Pipeline** | `pipeline/*.py` | Orchestration, texte, matching, LLM, Markdown | **Non** |
| **Prompts** | `prompts/*.xml.txt` | Instructions LLM versionnées (citation obligatoire) | Non |
| **Modèles** | `models.py` | Contrats de données entre composants | Non |
| **Utils** | `utils/*.py` | HTTP, strings, fichiers, config | Non |

**Conséquence :** ajouter une archive = un nouveau connecteur (+ éventuellement une stratégie). Le pipeline, le reporter et la synthèse ne changent pas.

**Conséquence LLM :** changer de modèle par tâche = éditer `config.json` `llm.models` (ou CLI/env). Les appels restent sur `build_llm_gateway(..., task=…)` — pas de client Ollama dupliqué.


---

## Modèles de données

Tous les objets échangés entre composants sont définis dans `models.py`.

### Cycle de vie d'un document

```
DocumentCandidate  →  ResolvedDocument  →  DownloadResult
       │                      │                    │
       └──────────────────────┴────────────────────┘
                              │
                              ▼
                    CollectedDocument
                    ( + ExtractedText
                      + KeywordMatch[]
                      + LlmExtraction? )
                              │
                              ▼
                       CollectionRun
                              │
                              ▼
                    Markdown de collecte
```

### Objets principaux

| Classe | Rôle |
|---|---|
| `DocumentCandidate` | Résultat brut d'une recherche (titre, URL, ID, collection) |
| `ResolvedDocument` | Candidat enrichi avec URLs de téléchargement/viewer et stratégie choisie |
| `DownloadResult` | Résultat technique du téléchargement (chemin local, HTTP, erreur) |
| `ExtractedText` | Texte extrait page par page (`ExtractedPage[]`) |
| `KeywordMatch` | Occurrence mécanique du mot-clé + contexte + page |
| `LlmExtraction` | Analyse sémantique Ollama d'un document (Markdown structuré) |
| `CollectedDocument` | Document entièrement traité (unité d'une section Markdown) |
| `CollectionRun` | Résultat complet d'une requête (entrée du reporter) |

### Statuts (`DocumentStatus`)

`found` → `resolved` → `downloaded` → `extracted` | `failed` | `ignored`

---

## Le pipeline de collecte (étape par étape)

Implémenté dans `pipeline/collector.py`, orchestré par `collecte.py`.

| # | Étape | Module | Description |
|---|---|---|---|
| 1 | **Recherche** | `connector.search()` | Requête HTTP sur le site, parsing HTML → liste de `DocumentCandidate` |
| 2 | **Résolution** | `connector.resolve()` | Enrichit chaque candidat (URL PDF, viewer, stratégie) |
| 3 | **Téléchargement** | `connector.download()` → stratégie | PDF local dans `work/downloads/{connector}/` |
| 4 | **Extraction texte** | `TextExtractor` (+ `OcrExtractor`) | pymupdf → pdfplumber → pypdf ; si `--enable-ocr` → **PaddleOCR** |
| 5 | **Matching mécanique** | `KeywordMatcher` | Occurrences du mot-clé + fenêtre de contexte + numéro de page |
| 6 | **Scoring** | `relevance_score()` | Score de pertinence simple par document |
| 7 | **Rapport** | `MarkdownReporter` | `CollectionRun` → fichier `.md` |

**Étape suivante (commande séparée) :** `analyse.py` relit les PDF locaux et enrichit le Markdown avec une section « Idées extraites (LLM) » par source (`LlmIdeaExtractor`).

**Gestion des erreurs :** aucune étape ne casse le pipeline. Échec de téléchargement ou OCR → consigné dans le Markdown (notes techniques), passage au document suivant.

**Mode dry-run (`--dry-run`) :** étapes 1–2 exécutées, téléchargement lourd ignoré, Markdown partiel produit quand même.

---

## Connecteurs (sources)

Un connecteur implémente le contrat de `connectors/base.py` :

```python
class Connector(ABC):
    def build_search_url(self, query: str) -> str: ...
    def search(self, query: str) -> list[DocumentCandidate]: ...
    def resolve(self, candidate: DocumentCandidate) -> ResolvedDocument: ...
    def build_strategies(self) -> list[DownloadStrategy]: ...
```

Enregistrement dans `connectors/__init__.py` → `REGISTRY`.

### Numelyo (`numelyo`) — implémentation principale

Site : [numelyo.bm-lyon.fr](https://numelyo.bm-lyon.fr) / [collections.bm-lyon.fr](https://collections.bm-lyon.fr)

| Action | Détail |
|---|---|
| Recherche | `GET …/list/?order_by=Relevance&cat=quick_filter&typedoc=all&search_keys[0]={query}&rows=5` |
| Pagination | Pages suivantes via `list.php?…&pager_row=N` (5 résultats/page → ex. 396 hits = 80 pages) |
| Types | Presse (`collections.bm-lyon.fr`, PDF via `ISSUE_PDF`) et illustrations (`/f_view/…`, JPEG preview) |
| Parsing | IDs presse (`BML_01PER…`, `PER…`) et illustrations (`BML:…` → `SourceType.IMAGE`) |
| Viewer presse | `collections.bm-lyon.fr/presseXIX/{ID}?pageOrder=N` |
| PDF | `collections.bm-lyon.fr/{ID}/ISSUE_PDF` |
| Stratégie presse | `ViewerToPdfStrategy` ; illustrations → `DirectDownloadStrategy` |
| Limite | `--max-results` borne le nombre de documents traités ; augmenter pour parcourir plus de pages |

### Archives du Rhône (`archives_rhone`)

Site : [archives.rhone.fr](https://archives.rhone.fr) — exemple de recherche : [`/search/results?q=…&scope=all`](https://archives.rhone.fr/search/results?q=rochecardon&scope=all)

- Recherche HTML (`li.element-list`) → notices ARK (`/ark:/28729/…`)
- Téléchargement : PDF `/media/<uuid>.pdf` si présent, sinon image `/images/<uuid>.jpg`
- Notices sans média numérique → scrape HTML de la fiche
- Pagination : `&page=N` (base 1)

```bash
python collecte.py --query "sujet" --connector archives_rhone --max-results 20
python collecte.py --query "sujet" --connector archives_rhone --dry-run --max-results 5
```

### Médiathèque du patrimoine / Archiv'MH (`archives_map`)

Site : [archives-map.culture.gouv.fr](https://archives-map.culture.gouv.fr) (Ligeo Archives) — exemple : [`RECH_S=pontarlier`](https://archives-map.culture.gouv.fr/archive/resultats/simple/lineaire/FRAMAP_806827/n:19?RECH_S=pontarlier&type=simple)

- Recherche simple `RECH_S` → résultats facettés par inventaire (`FRAMAP_*`)
- Notices : `/archive/fonds/FRAMAP_…/view:…`
- Documents numérisés : visionneuse ARK + JPEG IIP (`iipsrv.fcgi`, `HEI` plus élevé pour le téléchargement)
- Notices catalogue seules → téléchargement HTML de la fiche pour le texte / matching
- Pagination dans une facette : `/page:N`

```bash
python collecte.py --query "pontarlier" --connector archives_map --max-results 20
python collecte.py --query "pontarlier" --connector archives_map --dry-run --max-results 5
```

### Catalog HTML (`catalog_html`) — template multi-sources

Connecteur générique pour sites institutionnels avec recherche GET + liste de liens HTML.

```bash
python collecte.py --query "sujet" --connector catalog_html \
  --catalog-search-url "https://archives.example.org/search?q={query}" \
  --catalog-root "archives.example.org"
```

Fixture de test : `tests/fixtures/catalog_results.html`.

---

## Stratégies de téléchargement

Chaque connecteur déclare une liste **ordonnée**. La première stratégie qui `supports(document)` est utilisée.

| Stratégie | Fichier | Cas d'usage |
|---|---|---|
| `ViewerToPdfStrategy` | `viewer_to_pdf.py` | Viewer paginé → URL PDF dérivée (Numelyo) |
| `DirectDownloadStrategy` | `direct_download.py` | Fichier directement accessible par URL |
| `SessionCookieStrategy` | `session_cookie.py` | Visite du viewer pour obtenir un cookie, puis PDF |
| `HtmlScrapeStrategy` | `html_scrape.py` | Page d'atterrissage HTML contenant le lien du fichier |
| `ApiQueryStrategy` | `api_query.py` | API JSON renvoyant l'URL ou le binaire |
| `BrowserAutomationStrategy` | `browser_automation.py` | Playwright headless (**dernier recours**) |

**Contrat :** `download()` ne lève jamais d'exception → retourne toujours un `DownloadResult` (`success=False` + `error` en cas d'échec).

---

## Extraction de texte et OCR

### Extraction native (`pipeline/text_extractor.py`)

Ordre de tentative : **pymupdf → pdfplumber → pypdf** (premier backend installé qui fonctionne).

Le texte est renvoyé **page par page** (`ExtractedPage`) pour permettre la localisation des extraits dans le Markdown.

### OCR (`pipeline/ocr_extractor.py`, optionnel)

Moteur unique : **[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)** (`paddleocr` + runtime `paddlepaddle`), installable entièrement via `pip` — **pas de Tesseract** ni binaire système.

Activé avec `--enable-ocr` / `enable_ocr` si la couche texte native est absente ou insuffisante (`ocr_required`), y compris pour les **illustrations** (`.jpg`, `.png`, …).

```
PDF  : PyMuPDF (fitz) rasterise chaque page (DPI configurable, défaut 200) → PaddleOCR
Image : PaddleOCR direct (API predict() 3.x, repli ocr() 2.x)
```

| Détail | Comportement dans le code |
|---|---|
| Module | `pipeline/ocr_extractor.py` → classe `OcrExtractor` |
| Dépendances | `paddlepaddle`, `paddleocr` (voir `requirements.txt`) |
| Langue CLI | `--ocr-lang fra` (défaut) → code PaddleOCR `fr` ; `eng`/`en` → `en` |
| Extracteur rapporté | `ocr_paddle` (PDF) / `ocr_paddle_image` (illustration) |
| CPU Windows | initialisation avec `enable_mkldnn=False` (évite un bug PaddlePaddle 3.3.x oneDNN/PIR) |
| Premier run | téléchargement des modèles officiels (~centaines de Mo, cache `~/.paddlex/`) |

```bash
pip install paddlepaddle paddleocr

# Collecte ou analyse avec OCR
python collecte.py --query "sujet" --connector numelyo --enable-ocr --ocr-lang fra
python analyse.py --input work/research/…_collecte.md --only-matches --enable-ocr --ocr-lang fra
```

Avec `--enable-ocr`, les sources précédemment marquées « Ignoré » (images / scans sans texte) sont **réessayées** automatiquement.

---

## Matching de mots-clés (mécanique)

Module : `pipeline/keyword_matcher.py`

| Mode | CLI `--match-mode` | Comportement |
|---|---|---|
| `exact` | `exact` | Sous-chaîne sensible à la casse |
| `normalized` | `normalized` (défaut) | Insensible casse, accents, espaces |
| `fuzzy` | `fuzzy` | Token proche via `difflib` (coquilles OCR) |

Pour chaque occurrence : texte du match, contexte avant/après (`--context-window`, défaut 160 car.), numéro de page, type de match, score.

Ces extraits apparaissent dans le Markdown sous **« Extraits liés au mot-clé »** et sont transmis à la LLM comme indices de localisation.

---

## Extraction d'idées par LLM (Ollama)

Module : `pipeline/llm_idea_extractor.py`  
Commande : **`analyse.py`** (étape séparée, après `collecte.py`).  
Modèle de tâche par défaut : **`gemma4:26b`** (`llm.models.extraction`) — thinking off pour du JSON strict.

### Prompts versionnés (citation obligatoire)

Les textes de prompts sont dans **`prompts/`** (pas hardcodés dans le Python).
Chaque fichier a un en-tête `# version: N` et des balises XML
(`<role>`, `<constraints>`, `<output_format>`, `<examples>`).

| Fichier | Tâche |
|---|---|
| `prompts/analyze_document.vN.xml.txt` | Affirmations par document + citation verbatim |
| `prompts/synthesize_claims.vN.xml.txt` | Synthèse de corpus à partir d'affirmations structurées |
| `prompts/classify_source.vN.xml.txt` | Source probante vs non probante |
| `prompts/article_context.vN.xml.txt` | Dossier de contexte rédactionnel |

**Principe :** aucune affirmation sans `citation_exacte` présente dans le texte fourni.
En cas de doute : statut `insuffisant` / `a_revoir_manuellement`.
Validation Pydantic dans `pipeline/prompt_schemas.py` ; JSON invalide → « à revoir
manuellement » (pas d'insertion silencieuse dans la synthèse).
Régression : `pytest tests/test_prompt_grounding.py -q`.

Tous les appels passent par **`pipeline.llm_gateway.LlmGateway`**
(`build_llm_gateway(..., task="extraction"|"synthesis")`).

### Ce que fait la LLM à cette étape

Pour **chaque document** dont le PDF est disponible dans `work/downloads/` :

1. Ré-extrait le texte du PDF local
2. Rejoue le matching mécanique (même mot-clé et paramètres que la collecte)
3. Sélectionne les pages pertinentes (celles avec matches + voisines)
4. Envoie un échantillon de texte (max `llm_max_chars`, défaut 12 000) au modèle **extraction**
5. Demande des **affirmations JSON** (citation + affirmation + confiance + statut), puis rend un Markdown additif (sections historiques + bloc JSON)
6. Met à jour la section **« Idées extraites (LLM) »** dans le Markdown de collecte

**Important :** cette étape est **lente** (plusieurs minutes par document avec un gros modèle). Utiliser `--only-matches` pour ne traiter que les sources pertinentes.

```bash
python analyse.py --input work/research/2026-06-28_valmontagne_collecte.md --only-matches
```

---

## Synthèse et contexte de rédaction

Module : `pipeline/synthesizer.py`  
CLI : `synthesize.py`  
Modèle de tâche par défaut : **`qwen3.5`** (`llm.models.synthesis`) — long contexte ; thinking off par défaut (fences JSON).

Relit un Markdown de collecte (`markdown_reader.py`), filtre les affirmations ancrées (`grounded_claims.py`), et appelle la gateway avec **`task="synthesis"`** pour agréger **tout le corpus**.

### Mode `synthese` (défaut)

Produit une **note de recherche** à partir des **seules affirmations confirmées et
ancrées** (`statut=confirme_par_le_document`, citation non vide, source utilisable
comme preuve), puis applique une **corroboration multi-sources** : un fait n'entre
dans **Faits établis** que s'il est soutenu par au moins **deux sources indépendantes** ;
sinon il reste en **Hypothèses** avec `corroboration_insuffisante`.

| Section | Contenu |
|---|---|
| **Faits établis et sourcés** | Faits validés Pydantic multi-sources avec ancres `[S:n]` |
| **Chronologie sourcée** | Événements datés, chacun avec `[S:n]` |
| **Hypothèses et vérifications à mener** | Claims à source unique, questions ouvertes — jamais des faits |
| **Contrôle des références** | Comptage `[S:n]` vs catalogue ; alertes de critique externe |

Options :

- Préférer `synthesis.facts_mode` dans `config.json` (`tiered` | `strict` | `all`).
  Alias CLI legacy (avertissement) : `--allow-single-source-facts` → `all`,
  `--legacy-corroboration` → `strict`.
- NLI **actif par défaut** (entailment déterministe ; `--nli-llm` ; `--no-nli`)
- `--verify-cove` — Chain-of-Verification contre la citation (coût LLM +)
- NLI/CoVe : politiques `synthesis.*` dans `config.json` (appliquées par `synthesize.py`).
  Pour recontrôler un fichier existant sans régénérer la prose :
  `synthesize.py --input … --reverify chemin/vers_synthese.md`.

Modules : `pipeline/corroboration_checker.py`, `pipeline/source_criticism.py`,
`pipeline/nli_verifier.py`, `pipeline/cove_verifier.py`, `pipeline/verification_pipeline.py`.
Prompt d'extraction v2 : `poids_preuve`. Les connecteurs d'archives démarrent en
`non_determine` jusqu'à la critique externe.

**qwen3.5 n'est jamais une source** : il organise seulement des claims déjà prouvés
par les documents. Une sortie LLM invalide (`[0]`, id inconnu, absence de `[S:n]`)
est **rejetée** (« Synthèse non validée » / bandeau d'avertissement), sans prose
historique non sourcée.

Sans LLM : promotion déterministe des claims **corroborés** (aucune invention).

Fichier : `work/synthesys/{date}_{sujet}_synthese.md`

Régression :

```bash
pytest tests/test_synthesis_grounding.py tests/test_historical_validation.py -q
```

### Mode `contexte`

Produit un **dossier de rédaction** pour alimenter une LLM (ou pour écrire vous-même) :

- Fiche sujet
- Corpus documentaire retenu
- Faits établis (avec sources)
- Passages à citer
- Fil narratif possible
- Lacunes et prudence
- Consignes pour la rédaction

Fichier : `work/synthesys/{date}_{sujet}_contexte.md`

---

## Fichiers Markdown produits

| Fichier | Commande | Contenu |
|---|---|---|
| `{date}_{sujet}_{connector}_collecte.md` | `collecte.py` → `work/research/` | Trace complète **par site** : métadonnées, chaque source, extraits, idées LLM |
| `{date}_{sujet}_synthese.md` | `synthesize.py --query` → `work/synthesys/` | Synthèse multi-sites pour le mot-clé (URL conservées) |
| `{date}_{sujet}_contexte.md` | `synthesize.py --mode contexte` → `work/synthesys/` | Dossier structuré pour rédaction d'article |

### Structure d'un Markdown de collecte (stable)

Chaque source (`## Source N — titre`) contient :

```
### Identité          (URLs, ID, connecteur, stratégie, statut)
### Pertinence        (mot-clé, match count, score)
### Extraits liés au mot-clé     ← matcher mécanique
### Idées extraites (LLM)        ← analyse Ollama (via analyse.py)
### Localisation des extraits    (pages)
### Métadonnées documentaires
### Notes OCR / extraction
### Notes techniques             (HTTP, MIME, erreurs)
```

Sections globales : Métadonnées, Résumé de collecte, Paramètres de recherche, Sources ignorées, Observations, Annexes techniques.

---

## Configuration

### Règle de conception — aucune affirmation sans citation exacte

Toute affirmation produite par l'analyse doit reposer sur une `citation_exacte`
copiée depuis le texte du document fourni. Si le fait manque ou est ambigu, le
modèle doit utiliser le statut `insuffisant` / `document_status: a_revoir_manuellement`
plutôt qu'inventer. Contrat central du projet (prompts + validation Pydantic),
indépendant du modèle local configuré.

### `config.py` — objet `Config`

Conteneur typé passé à tous les composants. Principaux champs :

| Champ | Défaut | Description |
|---|---|---|
| `output_dir` | `work/research` | Dossier des Markdown |
| `download_dir` | `work/downloads` | Cache PDF |
| `timeout` / `delay` | 30s / 1s | HTTP |
| `max_results` | 20 | Limite de documents traités |
| `dry_run` | false | Sans téléchargement lourd |
| `match_mode` | `normalized` | Mode de matching |
| `context_window` | 160 | Caractères de contexte autour des matches |
| `enable_ocr` | false | Fallback **PaddleOCR** (`OcrExtractor`) |
| `ocr_lang` | `fra` | Langue CLI → mappée vers codes PaddleOCR (`fra`→`fr`) |
| `ocr_dpi` | 200 | DPI de rasterisation PDF avant OCR |
| `ollama_host` | `http://localhost:11434` | URL Ollama si `llm_provider=ollama` |
| `llm_provider` | `ollama` | `ollama` \| `openai` \| `openrouter` \| `perplexity` \| `none` |
| `llm_model_extraction` | `gemma4:26b` | Modèle pour l'extraction d'affirmations sourcées |
| `llm_model_synthesis` | `qwen3.5` | Modèle pour la synthèse à long contexte |
| `llm_fallback_model` | `llama3.2` | Utilisé si le modèle de tâche n'est pas installé |
| `llm_thinking_extraction` | `false` | `think` Ollama pour l'extraction (garder off pour le JSON) |
| `llm_thinking_synthesis` | `false` | `think` Ollama pour la synthèse (off par défaut) |
| `llm_model` / `ollama_model` | `qwen3.5` | Repli legacy mono-modèle |
| `llm_api_key` | `null` | Préférer les variables d'env `*_API_KEY` |
| `llm_max_chars` | 12000 | Texte max envoyé à la LLM par document |
| `ollama_timeout` | 600 | Timeout unique de génération LLM (s) |
| `llm_log_dir` | `work/logs/llm` | Logs JSONL rotatifs des appels |

### Multi-modèles Ollama (routage par tâche)

Déclarez les modèles par tâche dans le bloc imbriqué `llm` (forme adaptée à un
futur service en ligne). La résolution passe par
`pipeline.llm_task_models.get_model_for_task(task)` :

| Tâche | Usage typique | Modèle par défaut | Thinking |
|---|---|---|---|
| `extraction` | `analyse.py` / JSON d'affirmations | `gemma4:26b` | off |
| `synthesis` | `synthesize.py` narration | `qwen3.5` | off (mettre `true` pour expérimenter) |
| `classification` | classe de source | même que extraction | off |

Si un modèle configuré manque localement, la gateway avertit et bascule sur
`fallback_model` au lieu de planter.



### Politiques analyse / synthèse (`config.json`)

Pour l’usage quotidien, préférez éditer `config.json` plutôt que d’empiler des flags :

```jsonc
"analyse": { "auto_ocr": false, "two_pass_extraction": false },
"synthesis": {
  "facts_mode": "tiered",   // tiered | strict | all
  "verify_nli": true,
  "verify_cove": false,
  "nli_llm": false,
  "classify_sources": false
}
```

Profil recommandé archives PDF (à activer manuellement) :

```jsonc
"analyse": { "auto_ocr": true, "two_pass_extraction": true }
```

API appelable (futur front) : `pipeline.run_api.run_collect` / `run_analyse` /
`run_synthesize` / `run_reverify` (retour `RunResult` : `exit_code`, `paths`,
`quality_report_path` optionnel). Pas de couche HTTP pour l’instant.

### `config.json` — paramètres persistants (JSONC)

```jsonc
{
    "llm": {
        "provider": "ollama",
        "host": "http://localhost:11434",
        "timeout": 900,
        "models": {
            "extraction": "gemma4:26b",
            "synthesis": "qwen3.5"
        },
        "fallback_model": "llama3.2",
        "thinking_mode": {
            "extraction": false,
            "synthesis": false
        }
    }
}
```

Les clés plates legacy (`llm_provider`, `ollama_model`, …) fonctionnent encore.
Le bloc `llm` est aplati par `utils/app_config.py`. Précédence : **CLI / env >
config.json > défauts Config**.

Surcharges CLI / env pour expérimenter sans éditer le fichier :

| CLI | Env | Effet |
|---|---|---|
| `--model-extraction` / `--model` sur `analyse.py` | `LLM_MODEL_EXTRACTION` | Modèle d'extraction |
| `--model-synthesis` / `--model` sur `synthesize.py` | `LLM_MODEL_SYNTHESIS` | Modèle de synthèse |
| — | `LLM_FALLBACK_MODEL` | Id de repli |

### Test comparatif d'extraction (Rochecardon)

Nécessite Ollama avec `gemma4:26b` et `qwen3.5` installés :

```bash
# Windows
.\.venv\Scripts\python.exe -m pytest tests/test_model_comparison_rochecardon.py -q

# Linux / WSL
.venv/bin/python -m pytest tests/test_model_comparison_rochecardon.py -q
```

Rapport écrit dans `work/logs/llm/rochecardon_model_comparison.md` (et `.csv`).
Les deux modèles traitent le même extrait « garnis insalubres » avec thinking
désactivé ; le rapport compare validité du schéma, ancrage des citations, et
absence d'une surinterprétation « usine toxique ».

---

## Référence installation (résumé)

> Guide détaillé pas à pas : voir [Installation pas à pas](#installation-pas-à-pas) en tête de ce document.

**Python 3.11+** (testé sous 3.12).

```bash
python -m venv .venv

# Windows
.\.venv\Scripts\activate
# Linux/macOS / WSL
source .venv/bin/activate

pip install -r requirements.txt
pip install -e ../shared/ollama_shared   # client Ollama partagé
```

### Ollama

```bash
ollama serve          # si le service n'est pas déjà démarré
ollama pull gemma4:26b
ollama pull qwen3.5
ollama pull llama3.2  # repli optionnel
```

### Dépendances optionnelles

```bash
# OCR — PaddleOCR (pip only, pas de Tesseract)
pip install paddlepaddle paddleocr

# Navigateur automatisé (dernier recours)
pip install playwright && playwright install chromium
```

---

## Utilisation — CLI

### `collecte.py` — collecte

```bash
# Collecte standard
python collecte.py --query "valmontagne" --connector numelyo

# Dry-run (recherche + résolution, sans PDF lourds)
python collecte.py --query "valmontagne" --connector numelyo --dry-run

# Lot de requêtes
python collecte.py --queries-file queries.txt --connector numelyo

# OCR PaddleOCR pour documents scannés / images
python collecte.py --query "sujet" --connector numelyo --enable-ocr --ocr-lang fra
```

| Argument | Défaut | Description |
|---|---|---|
| `--query` / `--queries-file` | — | Requête(s) — l'un des deux est requis |
| `--connector` | `numelyo` | Connecteur source (`numelyo`, `archives_rhone`, `archives_map`, `catalog_html`) |
| `--output-dir` | `work/research` | Dossier Markdown |
| `--download-dir` | `work/downloads` | Cache PDF / images |
| `--dry-run` | off | Sans téléchargement lourd |
| `--max-results` | 20 | Nombre max de documents |
| `--match-mode` | `normalized` | `exact` / `normalized` / `fuzzy` |
| `--context-window` | 160 | Fenêtre de contexte (caractères) |
| `--enable-ocr` | off | Fallback **PaddleOCR** si texte natif insuffisant |
| `--ocr-lang` | `fra` | Langue OCR (`fra`→`fr` PaddleOCR) |
| `--timeout` / `--delay` | 30 / 1.0 | HTTP (secondes) |
| `--verbose` | off | Logs DEBUG |

### `analyse.py` — analyse LLM document par document

```bash
# Analyser les sources avec au moins un match mécanique
python analyse.py --input work/research/2026-06-28_valmontagne_collecte.md --only-matches

# Forcer la ré-analyse de toutes les sources
python analyse.py --input work/research/2026-06-28_valmontagne_collecte.md --force

# Modèle d'extraction explicite (n'écrase pas le fichier de collecte)
python analyse.py --input work/research/…_collecte.md --model-extraction gemma4:26b --only-matches

# Écrire dans un autre fichier
python analyse.py --input work/research/…_collecte.md --output work/research/…_collecte_analyse_eval.md
```

| Argument | Défaut | Description |
|---|---|---|
| `--input` | — | Markdown de collecte (requis) |
| `--output` | `…_collecte_analyse_{model}.md` à côté de `--input` | Fichier enrichi (`--in-place` pour écraser la collecte) |
| `--in-place` | off | Enrichir `--input` directement |
| `--download-dir` | `work/downloads` | Dossier des PDF / images téléchargés |
| `--only-matches` | off | Ignorer les sources sans match mécanique |
| `--skip-existing` / `--no-skip-existing` | activé | Sauter les sources déjà analysées |
| `--force` | off | Ré-analyser même si déjà fait |
| `--llm` | config `llm_provider` | `ollama` \| `openai` \| `openrouter` \| `perplexity` |
| `--model-extraction` | `llm.models.extraction` | Modèle pour l'extraction sourcée |
| `--model` | idem `--model-extraction` | Alias du modèle d'extraction |
| `--timeout` | config.json | Timeout génération (s) |
| `--enable-ocr` | off | Ré-extraction via **PaddleOCR** si texte natif insuffisant |
| `--ocr-lang` | `fra` | Langue OCR (`fra`→`fr` PaddleOCR) |
| `--verbose` | off | Logs DEBUG |

### `synthesize.py` — synthèse et contexte

```bash
# Synthèse multi-sites (défaut) : fusionne tous les connecteurs pour un mot-clé
python synthesize.py --query "valmontagne"

# Fichier de collecte unique
python synthesize.py --input work/research/2026-06-28_valmontagne_numelyo_collecte.md

# Contexte pour rédiger un texte (article, note, billet…)
python synthesize.py --query "valmontagne" --mode contexte

# Modèle de synthèse explicite
python synthesize.py --query "valmontagne" --model-synthesis qwen3.5

# Sans LLM (template déterministe)
python synthesize.py --query "valmontagne" --llm none
```

| Argument | Défaut | Description |
|---|---|---|
| `--query` | — | Mot-clé : découvre et fusionne les fichiers sous `work/research/` |
| `--input` | — | Markdown de collecte unique (alternative à `--query`) |
| `--research-dir` | `work/research` | Dossier scanné avec `--query` |
| `--output-dir` | `work/synthesys` | Dossier de sortie |
| `--mode` | `synthese` | `synthese` ou `contexte` |
| `--llm` | config `llm_provider` | `ollama` \| `openai` \| `openrouter` \| `perplexity` \| `none` |
| `--model-synthesis` | `llm.models.synthesis` | Modèle pour la synthèse longue |
| `--model` | idem `--model-synthesis` | Alias du modèle de synthèse |
| `--timeout` | config.json | Timeout génération (s) |

**Logs** = sortie technique (console). **Markdown** = sortie métier. Les deux sont indépendants.

---

## Gateway LLM et package Ollama partagé

Tous les appels analyse / synthèse passent par un **composant unique**, avec un
**rôle de tâche** :

```python
from pipeline.llm_gateway import build_llm_gateway
from pipeline.llm_task_models import get_model_for_task

model = get_model_for_task("extraction", config)  # ou "synthesis"
gateway = build_llm_gateway(config, task="extraction", operation="analyse")
text = gateway.complete(prompt, system="…")
```

| Fournisseur (`llm_provider` / `--llm`) | Notes |
|---|---|
| `ollama` (défaut) | Local via `../shared/ollama_shared` ; liste `/api/tags` + repli si besoin |
| `openai` / `openrouter` / `perplexity` | HTTP compatible OpenAI ; définir la `*_API_KEY` correspondante |
| `none` | Synthèse template uniquement (pas d'appel API) |

`config.json` est en **JSONC** (commentaires autorisés). Télémétrie des appels :
`work/logs/llm/llm_calls.jsonl`. Compteurs de validation : `pipeline.llm_validation_stats`.

`pipeline/llm_client.py` ne fait que **réexporter** la gateway (et `get_model_for_task`).

Le transport Ollama est factorisé dans `../shared/ollama_shared/` et réutilisé par :

- **ArchivTrace** (ce projet) — quand `llm_provider=ollama`
- **[YouTube2Post](https://github.com/fdepierre/YouTube2Post)** — chat sur transcripts

```python
from ollama_shared import OllamaService, DEFAULT_MODEL  # "qwen3.5"

service = OllamaService(model="qwen3.5")
text = service.generate("Prompt…", system="Instructions…", think=False)
```

Si le linter signale `ollama_shared` introuvable : vérifier que le venv est sélectionné et que `pyrightconfig.json` est présent.

---

## Tests

### Lancer la suite

Utiliser le venv du projet (pas le Python système pour les deps complètes) :

| Plateforme | Commande |
|---|---|
| Windows (PowerShell) | `.\.venv\Scripts\python.exe -m pytest -q` |
| Linux / WSL | `.venv/bin/python -m pytest -q` |

### Plan de test (niveaux)

Exécuter **T0 → T1** avant chaque merge. Exécuter **T2** lors d’un changement de prompts, modèles ou validation de synthèse. Exécuter **T3** avant une release ou après un changement OCR / connecteur / routage LLM.

| Niveau | Objectif | Commande | Prérequis |
|---|---|---|---|
| **T0 — Unitaires rapides** | Connecteurs, Markdown, config, OCR helpers, mocks gateway | `pytest -q --ignore=tests/test_model_comparison_rochecardon.py` | venv seul |
| **T1 — Contrat ancrage / synthèse** | Rejet `[0]`, `[S:n]` inconnus, claim/source incohérente ; prompt v2 | `pytest tests/test_prompt_grounding.py tests/test_synthesis_grounding.py tests/test_synthesis.py tests/test_synthesis_structure.py -q` | venv seul |
| **T2 — Smoke modèles live** | Extraction comparative gemma4 vs qwen3.5 (extrait garnis Rochecardon) | `pytest tests/test_model_comparison_rochecardon.py -q` | Ollama + modèles installés |
| **T3 — Smoke pipeline manuel** | Bout-en-bout sans écraser les fichiers historiques sous `work/` | Voir checklist ci-dessous | Ollama (+ OCR optionnel) |

**Checklist T3** (écrire sous `work/.../eval_YYYY-MM-DD/`) :

1. Analyser une collecte existante (ou variante OCR) :  
   `analyse.py --input … --output-dir work/research/eval_…` (+ `--enable-ocr` si besoin).
2. Synthétiser via le chemin ancré :  
   `synthesize.py --input …_analyse….md --output-dir work/synthesys/eval_…`.
3. Contrôle Markdown : chaque fait sous **Faits établis et sourcés** a un `[S:n]` ; pas de `[0]` / `[n]` nu ; LLM invalide → bandeau « Synthèse non validée », pas de prose non sourcée.
4. Optionnel : comparer entrées `gemma4-26b` vs analyse OCR ; rapports sous `work/logs/llm/eval_…/`.

### Carte de couverture

| Domaine | Fichiers de test |
|---|---|
| Connecteurs (Numelyo, Rhône, Archiv'MH, catalog HTML) | `test_numelyo_connector.py`, `test_archives_rhone_connector.py`, `test_archives_map_connector.py`, `test_catalog_html_connector.py` |
| Stratégies de téléchargement / collector dry-run | `test_strategies.py`, `test_collector.py` |
| Mots-clés, chemins, merge, chaînes | `test_keyword_matcher.py`, `test_research_paths.py`, `test_analyse_paths.py`, `test_merge_collections.py`, `test_strings.py` |
| PDF / OCR / politique d’analyse | `test_text_extractor.py`, `test_ocr.py`, `test_collection_analyzer.py`, `test_analyse_policy.py` |
| Rapport Markdown / patch / aller-retour | `test_markdown_reporter.py`, `test_markdown_patcher.py`, `test_markdown_roundtrip.py` |
| Gateway LLM, modèles par tâche, config | `test_llm_gateway.py`, `test_llm_task_models.py`, `test_llm_idea_extractor.py`, `test_llm_resume.py`, `test_llm_max_chars.py`, `test_config_precedence.py`, `test_ollama_shared.py` |
| Extraction ancrée + synthèse | `test_prompt_grounding.py`, `test_synthesis_grounding.py`, `test_synthesis.py`, `test_synthesis_structure.py` |
| Validation historique (corroboration, critique externe, NLI, CoVe) | `test_historical_validation.py` |
| Comparaison Ollama live | `test_model_comparison_rochecardon.py` |

### État au 2026-08-11

| Contrôle | Résultat |
|---|---|
| Tests collectés (sans Ollama live) | 175 |
| T0+T1 | **175 passed** |
| Validation historique | corroboration + critique externe + NLI + CoVe |
| Scripts | `synthesize.py` (`--reverify` pour recontrôle) |

Mettre à jour ce snapshot après un changement significatif du pipeline.

---

## Ajouter une nouvelle source

1. **Créer** le package `connectors/ma_source/` avec `connector.py` (et optionnellement `parsing.py`) :

```python
# connectors/ma_source/connector.py
class MaSourceConnector(Connector):
    name = "ma_source"
    root_source = "archives.example.org"

    def build_search_url(self, query: str) -> str: ...
    def search(self, query: str) -> list[DocumentCandidate]: ...
    def resolve(self, candidate: DocumentCandidate) -> ResolvedDocument: ...
    def build_strategies(self) -> list[DownloadStrategy]: ...
```

```python
# connectors/ma_source/__init__.py
from connectors.ma_source.connector import MaSourceConnector
__all__ = ["MaSourceConnector"]
```

2. **(Optionnel)** Ajouter une stratégie dans `strategies/` si le téléchargement diffère des cas existants.

3. **Enregistrer** dans `connectors/__init__.py` :

```python
REGISTRY = {
    NumelyoConnector.name: NumelyoConnector,
    MaSourceConnector.name: MaSourceConnector,
}
```

4. **Tester** : parsing offline avec fixture HTML + test d'URL.

Aucune modification du pipeline, du reporter ou du synthesizer n'est nécessaire.

---

## Exemple complet

Recherche documentaire sur « valmontagne » dans la presse lyonnaise (Numelyo) :

```bash
# 1. Collecte (3 documents max)
python collecte.py --query "valmontagne" --connector numelyo --max-results 3

# 2. Analyse LLM par document (sources avec matches)
python analyse.py --input work/research/2026-06-28_valmontagne_collecte.md --only-matches

# 3. Synthèse globale du corpus
python synthesize.py --input work/research/2026-06-28_valmontagne_collecte.md

# 4. Dossier de contexte pour rédiger votre texte
python synthesize.py --input work/research/2026-06-28_valmontagne_collecte.md --mode contexte
```

Résultat dans `work/research/` / `work/synthesys/` :

```
2026-06-28_valmontagne_collecte.md    ← sources, extraits, idées LLM
2026-06-28_valmontagne_synthese.md    ← note de recherche
2026-06-28_valmontagne_contexte.md    ← prêt pour la rédaction
```

Le fichier `_contexte.md` peut ensuite être passé tel quel à une LLM avec la consigne : *« Rédige un texte à partir de ce dossier documentaire. »* — ou servir de base à votre propre rédaction.

Les sorties sont écrites sous `work/research/` et `work/synthesys/` (ignorés par git).
