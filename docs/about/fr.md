# ClaudeBackend — ce que c'est, et pourquoi l'utiliser

[English](en.md) · [فارسی](fa.md) · [日本語](ja.md) · [中文](zh.md) · [Русский](ru.md) · **Français** · [Deutsch](de.md)

> Un **système de développement back-end** universel et multi-agents : confiez-lui
> un dépôt et un objectif rédigé en langage clair, et il implémente le changement
> sur une branche git prête à être relue — conscient des dépendances, vérifié, et
> sans jamais toucher à votre arbre de travail.

## Qu'est-ce que ClaudeBackend ?

ClaudeBackend est un agent en ligne de commande qui prend un dépôt de code ainsi
qu'un objectif arbitraire rédigé en langage clair — « Ajoute l'authentification
JWT », « Refactorise les modèles SQLAlchemy », « Ajoute un endpoint `/health` »,
ou même « Migre ceci de Python 2 vers 3 » — et l'implémente. Il s'appuie sur un
grand modèle de langage (Claude Opus 4.8 par défaut, avec une fenêtre de contexte
d'un million de tokens) encapsulé dans un **pipeline déterministe et isolé de trois
agents** : un **Planner** décide quels fichiers créer, modifier ou supprimer ; un
**Coder** implémente chaque étape ; et un **Verifier** exécute, en guise de filet
de sécurité, des contrôles de syntaxe, `ruff` et la propre suite `pytest` du projet
(avec jusqu'à 3 tentatives). Le modèle effectue le codage à proprement parler ; le
programme qui l'entoure décide *quoi* changer, *dans quel ordre*, et *vérifie le
résultat*. La sortie est écrite dans une **nouvelle branche git** — votre arbre de
travail et votre branche courante ne sont jamais modifiés.

## Le problème qu'il résout

Le véritable travail back-end tient rarement dans un seul fichier. Ajouter un
endpoint, remplacer un schéma d'authentification, remodeler un modèle de données ou
moderniser une base de code héritée : tout cela se propage à travers les modules,
les modèles ORM, la configuration et les tests. Le faire à la main est lent et
source d'erreurs ; le confier à un assistant de code naïf est risqué, car
l'assistant modifie un fichier à la fois et ne peut pas voir comment un changement
à un endroit en casse un autre.

Les bugs dangereux sont ceux qui franchissent les frontières entre fichiers :

> Une fonction utilitaire renvoie `d.keys()`. En Python 2 c'est une `list`, donc
> un autre module écrit sans risque `keys()[0]`. En Python 3, `keys()` est une
> *vue* — `keys()[0]` lève une `TypeError`. Un outil purement local « corrige »
> les deux fichiers et laisse la base de code cassée, parce que le bug n'apparaît
> que lorsqu'on examine les deux fichiers *ensemble*. Le même piège se cache dans
> d'innombrables changements back-end — renommez un champ de modèle, et chaque
> requête et chaque sérialiseur qui s'en servait peut se briser en silence.

## En quoi ClaudeBackend est différent

| | assistants de code naïfs | linters (p. ex. SonarQube) | ClaudeBackend |
|---|---|---|---|
| Implémente un changement (pas seulement éditer/signaler) | un fichier à la fois | lecture seule | de bout en bout, à travers le dépôt |
| Corrections inter-fichiers / conscientes des dépendances | non | non | oui — cartographie imports, ORM, config |
| Signale les choix ambigus / risqués | non | non | oui (`CLAUDEBACKEND-REVIEW`) |
| Sortie | modifications sur place | un rapport | une branche git relisible + un résumé |

L'idée centrale : ClaudeBackend construit un **graphe de dépendances** de votre
code — il cartographie les imports Python *et aussi* les modèles ORM (Django /
SQLAlchemy), les Dockerfile et les fichiers de configuration — et fournit ce
contexte réel au Planner. Chaque fichier est présenté au modèle *accompagné de ses
dépendances* au sein d'une très grande fenêtre de contexte. C'est pour cela qu'il
sait implémenter des changements qui se propagent à travers les fichiers, au lieu
des éditions cassées, fichier par fichier, que produisent les outils purement
locaux.

## À qui cela s'adresse

- **Aux équipes qui livrent des fonctionnalités back-end** et veulent une branche
  relisible, pas une modification de masse en boîte noire.
- **Aux mainteneurs** qui modernisent des services, remodèlent des modèles de
  données ou résorbent de la dette technique à travers de nombreux fichiers.
- **Aux consultants et prestataires** qui réalisent de grands refactorings ou des
  migrations et veulent un diff relisible, pas une boîte noire.
- **À quiconque** possède une base de code héritée — y compris un utilitaire
  Python 2 qui « fonctionne encore » mais ne s'installe plus sur une machine
  moderne — et a besoin d'une mise à jour soigneuse et consciente des dépendances.

## Fonctionnalités clés

- **Développement inter-fichiers conscient des dépendances** — la capacité phare :
  il cartographie les imports, les modèles ORM, les Dockerfile et la configuration
  pour que le Planner voie le contexte réel.
- **Pipeline à trois agents** — Planner, Coder et Verifier s'exécutent comme des
  étapes isolées et déterministes, de sorte que chaque objectif suit le même
  cheminement rigoureux.
- **Vérification honnête et stratifiée** — un contrôle de syntaxe par fichier, puis
  une passe à l'échelle du projet (compilation + `ruff` + votre propre suite
  `pytest`, si elle se collecte), avec jusqu'à 3 tentatives en guise de filet de
  sécurité.
- **Sûr par conception** — il refuse un arbre de travail non propre, n'écrit que
  dans une nouvelle branche (`claudebackend/feature-<timestamp>`), et dispose d'un
  mode `--dry-run` (la valeur par défaut pour les agents) qui n'écrit rien.
- **Signale ce dont il n'est pas certain** — les changements ambigus ou sensibles
  du point de vue de la sécurité sont implémentés *et* marqués d'un commentaire
  `CLAUDEBACKEND-REVIEW` pour qu'un humain confirme.
- **Utilisez votre propre LLM** — Claude par défaut ; mais aussi d'autres
  fournisseurs compatibles OpenAI (OpenRouter, OpenAI, NVIDIA, DeepSeek et Gemini).
- **Utilisez-le depuis vos outils** — il est livré sous forme de MCP server,
  d'Agent Skill et de plugin Claude Code, de sorte que Cursor, Codex, Google
  Antigravity et Claude Code/Desktop peuvent l'appeler.

## Comment ça marche (en un coup d'œil)

1. **Graphe** — cartographier les dépendances du dépôt : les imports Python (avec
   le `tokenize` de la bibliothèque standard, afin de pouvoir analyser même du
   source Python 2 que `ast` rejette), les modèles ORM (Django / SQLAlchemy), les
   Dockerfile et les fichiers de configuration. Les cycles d'import se regroupent en
   une seule unité.
2. **Plan** — le Planner transforme votre objectif en une liste concrète de
   fichiers à créer, modifier ou supprimer, annotée du risque et de notes par
   fichier.
3. **Développement** — pour chaque étape, le Coder construit le contexte (le fichier
   plus ses dépendances, avec mise en cache des prompts), diffuse en flux le
   changement, vérifie sa syntaxe et réessaie en cas d'échec.
4. **Vérification** — une passe de compilation + lint + tests à l'échelle du
   projet : le véritable garde-fou inter-fichiers (avec jusqu'à 3 tentatives).
5. **Commit** — créer la branche, valider module par module et écrire un
   `DEV_SUMMARY.md` ainsi qu'un graphe de topologie interactif `DEV_GRAPH.md`.

## Honnête quant à ses limites

Les contrôles statiques sont un **filet de sécurité, pas une preuve de
correction**. Les contrôles de syntaxe et `ruff` détectent une catégorie d'erreurs
— mais les choix qui préservent le comportement tout en restant ambigus sont
tranchés par le modèle et *signalés* à votre intention, et non prouvés corrects. La
garantie la plus sûre reste la **réussite de votre propre suite de tests** après le
changement. ClaudeBackend est conçu pour rendre cette relecture rapide et honnête,
pas pour faire croire que le travail back-end est entièrement automatisable.

## Pour commencer

```bash
# 1. Installation (script d'amorçage par OS — voir les guides d'installation) :
#    Windows : powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#    macOS :   ./scripts/setup-macos.sh
#    Linux :   ./scripts/setup-linux.sh

# 2. Authentifiez-vous (p. ex. avec une clé d'API Anthropic) et prévisualisez d'abord le travail :
export ANTHROPIC_API_KEY=...
claudebackend develop path/to/repo "Add a /health endpoint" --dry-run  # n'écrit rien
```

**En savoir plus :** [README du projet](../../README.md) ·
[Backends LLM](../providers.md) · [Intégrations IDE / agents](../integrations.md)
· guides d'installation pour [Windows](../install/windows.md),
[macOS](../install/macos.md) et [Linux](../install/linux.md).
