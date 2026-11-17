# Feuille de route — corpus vidéo (YouTube2Post → ArchivTrace)

Ce document couvre les deux projets : [YouTube2Post](https://github.com/fdepierre/YouTube2Post)
acquiert et transcrit les vidéos, ArchivTrace en extrait des affirmations sourcées, les
vérifie et les rapproche. Il dit ce qui est fait, ce qui reste, et dans quel ordre.

Règle commune : rien n'est annoncé comme disponible avant d'être écrit et testé. Les
principes de données sont dans [DATA_LINEAGE.md](DATA_LINEAGE.md).

## Fait

| Incrément | Contenu |
|---|---|
| 0 | Une citation est vérifiée contre le texte source seulement, jamais contre la sortie du modèle. |
| 1 | YouTube2Post garde les horodatages et exporte un JSON `yt2post-source/1` par transcription (`-j`). |
| 2 | `import_sources.py` déclare les vidéos dans un carnet ; chaque affirmation est localisée `[mm:ss–mm:ss]` ; réimport sans doublon ; nouvelle transcription = analyse obsolète. |
| 3 | Les longues vidéos sont analysées en entier, par blocs, avec cache, reprise et relance en deux moitiés d'un bloc tronqué. |
| 4 | État de chaque vidéo d'une playlist (`yt2post-playlist/1`), reprise et lots (`-n`), `import_sources.py --status`, fichier d'analyse tenu à jour, `analyse.py --limit` et `--source`. Écrit et testé, pas encore fusionné. |
| Affichage | Toutes les commandes d'ArchivTrace affichent des étapes numérotées, leur résultat et leur durée, comme `yt2post.py` (`utils/console.py`) ; `rich` n'est plus utilisé. Écrit et testé, pas encore fusionné. |

## Mesures de référence

Faites sur un PC avec un GPU de 6 Go, Whisper `large-v3-turbo` et qwen3.5 9B.

| Étape | Mesure |
|---|---|
| Transcription | environ 36 fois plus vite que l'audio (18 min en 30 s) |
| Analyse | environ le temps réel : 51 min de vidéo, 8 blocs, 71 affirmations, 40 min |
| Réponse tronquée | environ 10 min perdues par bloc (appel, réparation, relance en moitiés) |
| Playlist « Conférences et cours publics » (Musée de l'Homme) | 161 vidéos, 197 h : 5 à 6 h de transcription, de l'ordre de 200 h d'analyse |

Test du 16 novembre 2026 sur cette playlist (4 vidéos transcrites, 1 analysée) :

| Étape | Mesure |
|---|---|
| Transcription de 3 vidéos (3 h 11 d'audio) | 8 min 15 s, téléchargement compris |
| Téléchargement | de 46 s à 6 min 33 s pour une vidéo de taille comparable : c'est YouTube qui limite |
| État et import de la playlist (161 vidéos) | 1 s chacun |
| Analyse d'une vidéo de 32 min | 19 min 27 s, 17 affirmations (15 exactes, 2 approchées), 3 vérifiées à la main |
| Répartition de ces 19 min | 2 blocs de 13 min de parole : 50 s chacun ; le dernier bloc de 6 min : 17 min (réponse tronquée, réparation, puis deux moitiés) |

Deux enseignements :

- **Le sujet par défaut ne convient pas.** Sans `--query`, le sujet est le titre de la
  playlist, ici « Conférences et cours publics ». Le modèle a jugé les 26 premières minutes
  hors sujet et n'en a tiré **aucune** affirmation ; les 17 viennent des 6 dernières minutes.
  Un titre de playlist n'est pas un sujet de recherche.
- **Le coût vient des réponses tronquées**, pas de la longueur de la vidéo : 87 % du temps
  est passé sur un bloc dont la réponse dépassait la limite de sortie.

Seconde analyse de la même vidéo, le même jour, sans rien changer :

- **Un bloc tronqué n'est jamais mis en cache.** Les deux premiers blocs sont revenus du
  cache en quelques secondes, le troisième a été redemandé au modèle : 10 min.
- **Le résultat n'est pas stable.** Cette fois la réparation de la réponse a réussi, et la
  vidéo a donné 10 affirmations au lieu de 17. Le résultat réparé est maintenant en cache.

La transcription d'une grande playlist est faisable en une nuit. **L'analyse ne l'est pas** :
c'est le premier chantier.

## Chantiers

Chaque chantier a un objectif, un critère de réussite, et ce qu'il ne doit pas faire.

### A et A bis. Coût et sujet de l'analyse — faits (branche `analysis-cost`)

Mesures du 17 novembre 2026 (GPU de 6 Go), après le chantier :

| Configuration | Conférence de 32 min | Affirmations | Citations exactes | Tranches de 5 min couvertes |
|---|---|---|---|---|
| Avant : 9B, sujet = titre de la playlist | 19 min 27 s | 17 | 88 % | 2 sur 7 |
| 9B, nouvelle consigne | 11 min 24 s | 32 | 90 % | 7 sur 7 |
| 4b, nouvelle consigne | 1 min 42 s | 36 | 69 % | 6 sur 7 (la 7e dure 1 min 40) |

Avec le 4b, les deux autres conférences de référence (77 et 83 min) prennent 3 min 58 s et
6 min, 71 % et 81 % de citations exactes, toutes leurs tranches couvertes, aucune réponse
coupée. La playlist de 197 h demanderait environ 12 h avec le 4b, environ 70 h avec le 9B
(estimation d'après la vidéo de 32 min).

Ce qui a été fait :

- **A bis** : une consigne propre aux transcriptions (`analyze_transcript`) demande les
  affirmations principales de chaque passage ; le sujet et le titre sont un contexte, pas un
  filtre. Critère atteint : des affirmations sur toute la durée de la vidéo.
- **A, piste 0** : au plus 6 affirmations par bloc d'environ 6 min, champs de longueur
  bornée, imposés à Ollama par un schéma JSON pendant la génération.
- **A, piste 0 bis** : une réponse coupée n'est plus réparée (même longueur, coupée de
  nouveau) : le bloc est tout de suite coupé en deux, et la décision est mise en cache. Une
  réponse obtenue au second essai le dit dans les limites de la source.
- **A, piste 1** : 4b contre 9B mesuré (tableau ci-dessus) ; le 9B reste le modèle par
  défaut, le 4b est documenté pour les playlists entières.
- **A, piste 3** : la limite de sortie est relevée à la longueur de la plus longue réponse
  que le schéma permet.
- **A, piste 4** : le temps restant est estimé dès le premier bloc, à partir des appels
  précédents du même modèle (`work/logs/llm/llm_calls.jsonl`).
- Une citation dont seuls la casse et la ponctuation diffèrent est exacte (Whisper devine
  la ponctuation).

Critère « durée divisée par 4 sans baisse de la part de citations exactes » : **atteint
par aucun des deux modèles seul**. Le 9B garde l'exactitude (90 %) mais n'est que 1,7 fois
plus rapide ; le 4b est 11 fois plus rapide mais reformule une citation sur quatre. Une
consigne plus stricte sur la copie n'a rien changé pour le 4b (69 %).

Reste :

- **Piste 2, analyse ciblée** : abandonnée, elle contredit A bis (ne rien écarter à
  l'extraction).
- **Réconcilier vitesse et exactitude** : analyser au 4b, puis faire vérifier ou recopier
  par le 9B les seules citations `(fuzzy)` ; mesurer le gain.
- Afficher par source le nombre de citations exactes et approchées.
- ~~Trois copies du client `ollama_shared`~~ : fait, ArchivTrace appelle directement le
  client officiel `ollama`.
- Les tests écrivent leurs appels factices dans le vrai journal `llm_calls.jsonl` (filtrés
  par l'estimation, mais à séparer).

### B. Types d'éléments et fiches

- **Objectif** : passer d'une liste d'affirmations par vidéo à des fiches par notion,
  alimentées par plusieurs vidéos.
- **Contenu** :
  - types d'éléments : concept, définition attribuée, hypothèse, référence, question ouverte ;
  - filtre des citations de faible valeur (fragments sans contenu, vus au test de 51 min) ;
  - occurrences d'une même notion regroupées en fiche, chacune avec sa vidéo et son horodatage ;
  - décisions humaines (fusionner, rejeter, corriger) dans un fichier séparé, jamais régénéré ;
  - une analyse par fichier pour les grandes playlists, au lieu d'un seul Markdown de
    plusieurs Mo.
- **Réussite** : sur 10 vidéos, chaque fiche renvoie à des passages vérifiables ; relancer
  l'analyse ne perd aucune décision humaine.
- **À ne pas faire** : laisser une fusion renforcer le statut d'une affirmation.

### C. Confrontation avec des articles scientifiques

- **Objectif** : distinguer « dit dans la vidéo » de « établi par une publication ».
- **Contenu** : recherche par les connecteurs existants à partir des références citées dans
  les vidéos ; synthèse en deux colonnes ; une vidéo reste une preuve secondaire.
- **Réussite** : pour une fiche, la synthèse cite au moins une source primaire ou dit qu'elle
  n'en a pas trouvé.

### D. Sous-titres YouTube

- **Objectif** : utiliser les sous-titres d'origine quand ils existent, plus rapides et
  parfois relus.
- **Contenu** : même format `yt2post-source/1`, avec la provenance (`subtitles`, automatique
  ou fourni par la chaîne) ; comparaison avec Whisper sur quelques vidéos.
- **À ne pas faire** : mélanger deux provenances dans une même version de texte.

### E. Qualité de transcription

- Noms propres et termes savants (sites, espèces, auteurs) : liste de vocabulaire par
  playlist donnée à Whisper.
- Intervenants multiples : qui parle, quand c'est possible.
- Relecture ciblée : ne relire que les passages cités par une affirmation retenue.

### F. Robustesse du format Markdown

- **Fait** : un texte de modèle ne peut plus commencer une ligne du carnet (retours à la
  ligne retirés à l'affichage) ; les champs placés après l'analyse sont lus à leur dernière
  occurrence.
- **Reste** : encadrer le bloc d'analyse par des marqueurs explicites ; test de non-régression
  sur les carnets existants ; même vérification pour les extraits mécaniques, qui viennent du
  texte source.

### G. Chaîne commune

- Une commande qui enchaîne, par lots, transcription → import → analyse d'une playlist, avec
  reprise à chaque étape.
- Un test partagé qui vérifie les formats `yt2post-source/1` et `yt2post-playlist/1` des deux
  côtés.
- Versions des outils de CI épinglées (la CI d'ArchivTrace a été rouge d'octobre à novembre
  2026 à cause d'outils non épinglés).
- Affichage commun : `utils/console.py` suit `modules/ui.py` de YouTube2Post ; un test signale
  une dérive. Reste : le compte rendu final de `archivtrace.py` (« Done. ») garde son ancienne
  forme ; `synthesize.py` montre deux étapes (lecture, rédaction) et non le détail des
  vérifications ; le nombre de citations exactes et approchées n'est pas affiché par source ;
  les messages du journal sont encore en français et en anglais mêlés.

### H. YouTube2Post seul

- Reprise d'une playlist sans `-j`.
- Téléchargement de la vidéo suivante pendant la transcription de la précédente.
- Estimation de l'espace disque et de la durée avant de commencer une playlist.

## Ordre proposé

1. ~~**A** et **A bis**~~ : faits, sauf la réconciliation vitesse et exactitude.
2. **B** : c'est ce qui rend le corpus utilisable.
3. **F** et **G** en continu, à chaque incrément.
4. **C**, puis **D** et **E** selon les besoins constatés sur les fiches.
