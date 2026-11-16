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

La transcription d'une grande playlist est faisable en une nuit. **L'analyse ne l'est pas** :
c'est le premier chantier.

## Chantiers

Chaque chantier a un objectif, un critère de réussite, et ce qu'il ne doit pas faire.

### A. Coût de l'analyse des longues playlists — priorité 1

- **Objectif** : analyser une playlist de 100 vidéos en quelques nuits, pas en semaines.
- **Pistes, dans l'ordre** :
  0. Borner la réponse : demander au plus N affirmations par bloc (les plus importantes), et
     adapter la taille du bloc à la densité, pour ne plus tronquer. C'est le gain le plus
     sûr d'après le test.
  1. Mesurer qwen3.5:4b contre 9B sur les mêmes 3 vidéos : durée, nombre d'affirmations,
     part de citations exactes. Le 4b tient en entier sur un GPU de 6 Go.
  2. Analyse ciblée : n'envoyer au modèle que les blocs proches d'un passage qui contient le
     sujet (les extraits mécaniques existent déjà). Afficher le nombre de blocs lus et sautés.
  3. Régler `llm_max_chars` et `ollama_num_predict` pour qu'aucune réponse ne soit tronquée.
  4. Estimer la durée avant de lancer, à partir du nombre de blocs et de la vitesse mesurée.
- **Réussite** : durée d'analyse divisée par 4 au moins sur les 3 vidéos de référence, sans
  baisse de la part de citations exactes.
- **À ne pas faire** : sauter des blocs sans le dire ; une vidéo analysée en partie doit
  l'indiquer dans ses limites.

### A bis. Sujet de l'analyse d'une vidéo — priorité 1

- **Objectif** : une vidéo importée sans sujet précis doit quand même être analysée en entier.
- **Pistes** : un mode « sans sujet » pour les transcriptions, qui extrait les affirmations
  principales de la vidéo elle-même (son titre sert de contexte, pas de filtre) ; le sujet
  de recherche sert ensuite à trier et à rapprocher, pas à écarter à l'extraction.
- **Fait en attendant** : `import_sources.py` prévient quand le sujet est le titre de la
  playlist.
- **Réussite** : sur la vidéo de 32 min du test, des affirmations sur toute la durée, pas
  seulement sur les 6 dernières minutes.

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
  une dérive.

### H. YouTube2Post seul

- Reprise d'une playlist sans `-j`.
- Téléchargement de la vidéo suivante pendant la transcription de la précédente.
- Estimation de l'espace disque et de la durée avant de commencer une playlist.

## Ordre proposé

1. **A** et **A bis** : sans eux, les autres chantiers ne peuvent être essayés que sur quelques vidéos.
2. **B** : c'est ce qui rend le corpus utilisable.
3. **F** et **G** en continu, à chaque incrément.
4. **C**, puis **D** et **E** selon les besoins constatés sur les fiches.
