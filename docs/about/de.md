# ClaudeBackend — was es ist und warum man es einsetzt

[English](en.md) · [فارسی](fa.md) · [日本語](ja.md) · [中文](zh.md) · [Русский](ru.md) · [Français](fr.md) · **Deutsch**

> Ein universelles, mandantenübergreifendes **Backend-Entwicklungssystem**: Geben
> Sie ihm ein Repository und ein in einfacher Sprache formuliertes Ziel, und es
> setzt die Änderung auf einem überprüfbaren git-Branch um — abhängigkeitsbewusst,
> verifiziert und ohne Ihr Arbeitsverzeichnis jemals anzutasten.

## Was ist ClaudeBackend?

ClaudeBackend ist ein Kommandozeilen-Agent, der ein Code-Repository sowie ein
beliebiges, in einfacher Sprache formuliertes Ziel entgegennimmt — „Füge
JWT-Authentifizierung hinzu", „Refaktoriere die SQLAlchemy-Modelle", „Füge einen
`/health`-Endpunkt hinzu" oder sogar „Migriere dies von Python 2 nach 3" — und es
umsetzt. Es wird von einem großen Sprachmodell angetrieben (standardmäßig Claude
Opus 4.8 mit einem Kontextfenster von 1 Million Token), eingebettet in eine
**deterministische, isolierte Pipeline aus drei Agenten**: Ein **Planner**
entscheidet, welche Dateien erstellt, geändert oder gelöscht werden; ein **Coder**
setzt jeden Schritt um; und ein **Verifier** führt als Sicherheitsnetz
Syntaxprüfungen, `ruff` und die projekteigene `pytest`-Suite aus (mit bis zu 3
Wiederholungen). Das Modell übernimmt die eigentliche Programmierung; das umgebende
Programm entscheidet, *was* geändert wird, *in welcher Reihenfolge*, und *prüft das
Ergebnis*. Die Ausgabe wird in einen **neuen git-Branch** geschrieben — Ihr
Arbeitsverzeichnis und Ihr aktueller Branch werden niemals angetastet.

## Das Problem, das es löst

Echte Backend-Arbeit passt selten in eine einzige Datei. Einen Endpunkt
hinzufügen, ein Authentifizierungsschema austauschen, ein Datenmodell umformen oder
eine Legacy-Codebasis modernisieren — all das breitet sich über Module,
ORM-Modelle, Konfiguration und Tests aus. Von Hand ist das langsam und
fehleranfällig; einem naiven Code-Assistenten überlassen ist es riskant, denn der
Assistent bearbeitet eine Datei nach der anderen und kann nicht erkennen, wie eine
Änderung an einer Stelle eine andere zerbricht.

Die gefährlichen Fehler sind diejenigen, die über Dateigrenzen hinweg auftreten:

> Eine Hilfsfunktion gibt `d.keys()` zurück. In Python 2 ist das eine `list`, sodass
> ein anderes Modul gefahrlos `keys()[0]` schreibt. In Python 3 ist `keys()` eine
> *View* — `keys()[0]` löst einen `TypeError` aus. Ein rein lokales Werkzeug
> „repariert" beide Dateien und hinterlässt eine defekte Codebasis, weil der Fehler
> nur sichtbar wird, wenn man beide Dateien *zusammen* betrachtet. Dieselbe Falle
> verbirgt sich in unzähligen Backend-Änderungen — benennen Sie ein Modellfeld um,
> und jede Abfrage und jeder Serializer, der es berührt hat, kann stillschweigend
> brechen.

## Warum ClaudeBackend anders ist

| | naive Code-Assistenten | Linter (z. B. SonarQube) | ClaudeBackend |
|---|---|---|---|
| Setzt eine Änderung um (nicht nur bearbeiten/berichten) | eine Datei nach der anderen | nur lesend | durchgängig über das Repository hinweg |
| Dateiübergreifende / abhängigkeitsbewusste Korrekturen | nein | nein | ja — kartiert Imports, ORM, Konfig |
| Markiert mehrdeutige / riskante Entscheidungen | nein | nein | ja (`CLAUDEBACKEND-REVIEW`) |
| Ausgabe | Änderungen vor Ort | ein Bericht | ein überprüfbarer git-Branch + Zusammenfassung |

Die Kernidee: ClaudeBackend erstellt einen **Abhängigkeitsgraphen** Ihres Codes —
es kartiert Python-Imports *und* ORM-Modelle (Django / SQLAlchemy), Dockerfiles und
Konfigurationsdateien — und gibt dem Planner diesen realen Kontext. Jede Datei wird
dem Modell *zusammen mit ihren Abhängigkeiten* in einem sehr großen Kontextfenster
gezeigt. Genau deshalb kann es Änderungen umsetzen, die sich über Dateien hinweg
ausbreiten, statt der defekten Datei-für-Datei-Bearbeitungen, die rein lokale
Werkzeuge erzeugen.

## Wer es braucht

- **Teams, die Backend-Funktionen ausliefern** und einen überprüfbaren Branch
  wollen, keine Massenbearbeitung als Blackbox.
- **Maintainer**, die Dienste modernisieren, Datenmodelle umformen oder technische
  Schulden über viele Dateien hinweg abbauen.
- **Berater und Auftragnehmer**, die große Refaktorierungen oder Migrationen
  durchführen und ein überprüfbares Diff wollen, keine Blackbox.
- **Alle**, die eine Legacy-Codebasis haben — einschließlich eines
  Python-2-Hilfsprogramms, das „noch funktioniert", sich aber auf einer modernen
  Maschine nicht mehr installieren lässt — und eine sorgfältige,
  abhängigkeitsbewusste Aktualisierung benötigen.

## Hauptmerkmale

- **Abhängigkeitsbewusste, dateiübergreifende Entwicklung** — die herausragende
  Fähigkeit: Es kartiert Imports, ORM-Modelle, Dockerfiles und Konfiguration, damit
  der Planner den realen Kontext sieht.
- **Pipeline aus drei Agenten** — Planner, Coder und Verifier laufen als isolierte,
  deterministische Stufen, sodass jedes Ziel demselben disziplinierten Weg folgt.
- **Ehrliche, mehrschichtige Verifikation** — ein Syntaxgatter pro Datei, dann ein
  projektweiter Durchlauf (Kompilierung + `ruff` + Ihre eigene `pytest`-Suite,
  sofern sie sich erfassen lässt), mit bis zu 3 Wiederholungen als Sicherheitsnetz.
- **Sicher durch Konstruktion** — es verweigert ein verschmutztes
  Arbeitsverzeichnis, schreibt ausschließlich in einen neuen Branch
  (`claudebackend/feature-<timestamp>`) und verfügt über einen `--dry-run`-Modus
  (die Voreinstellung für Agenten), der nichts schreibt.
- **Markiert, worüber es sich unsicher ist** — mehrdeutige oder
  sicherheitsrelevante Änderungen werden umgesetzt *und* mit einem
  `CLAUDEBACKEND-REVIEW`-Kommentar versehen, damit ein Mensch sie bestätigen kann.
- **Verwenden Sie Ihr eigenes LLM** — standardmäßig Claude; außerdem andere
  OpenAI-kompatible Anbieter (OpenRouter, OpenAI, NVIDIA, DeepSeek und Gemini).
- **Nutzen Sie es aus Ihren Werkzeugen heraus** — es wird als MCP server, als Agent
  Skill und als Claude Code plugin ausgeliefert, sodass Cursor, Codex, Google
  Antigravity und Claude Code/Desktop es aufrufen können.

## Wie es funktioniert (auf einen Blick)

1. **Graph** — die Abhängigkeiten des Repositories kartieren: Python-Imports (mit
   dem Standardbibliotheks-`tokenize`, damit sogar Python-2-Quellcode geparst werden
   kann, den `ast` ablehnt), ORM-Modelle (Django / SQLAlchemy), Dockerfiles und
   Konfigurationsdateien. Importzyklen werden zu einer einzigen Einheit
   zusammengefasst.
2. **Plan** — der Planner überführt Ihr Ziel in eine konkrete Liste von Dateien, die
   erstellt, geändert oder gelöscht werden sollen, annotiert mit dateispezifischem
   Risiko und Hinweisen.
3. **Entwicklung** — für jeden Schritt baut der Coder den Kontext auf (die Datei plus
   ihre Abhängigkeiten, mit Prompt-Caching), streamt die Änderung, prüft ihre Syntax
   und versucht es bei Fehlschlag erneut.
4. **Verifikation** — ein projektweiter Durchlauf aus Kompilierung + Linting +
   Tests: das eigentliche dateiübergreifende Gatter (mit bis zu 3 Wiederholungen).
5. **Commit** — den Branch erstellen, pro Modul committen und eine `DEV_SUMMARY.md`
   sowie einen interaktiven Topologiegraphen `DEV_GRAPH.md` schreiben.

## Ehrlich über seine Grenzen

Die statischen Prüfungen sind ein **Sicherheitsnetz, kein Korrektheitsbeweis**.
Syntaxprüfungen und `ruff` fangen eine Klasse von Fehlern ab — aber
verhaltenserhaltende-und-doch-mehrdeutige Entscheidungen werden vom Modell getroffen
und für Sie *markiert*, nicht als korrekt bewiesen. Die sicherste Garantie ist das
Bestehen **Ihrer eigenen Testsuite** nach der Änderung. ClaudeBackend ist darauf
ausgelegt, diese Überprüfung schnell und ehrlich zu machen — nicht so zu tun, als
sei Backend-Arbeit vollständig automatisierbar.

## Erste Schritte

```bash
# 1. Installieren (betriebssystemspezifisches Bootstrap-Skript — siehe die Installationsanleitungen):
#    Windows: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#    macOS:   ./scripts/setup-macos.sh
#    Linux:   ./scripts/setup-linux.sh

# 2. Authentifizieren (z. B. mit einem Anthropic-API-Schlüssel) und die Arbeit zuerst in der Vorschau anzeigen:
export ANTHROPIC_API_KEY=...
claudebackend develop path/to/repo "Add a /health endpoint" --dry-run  # schreibt nichts
```

**Mehr erfahren:** [Projekt-README](../../README.md) ·
[LLM-Backends](../providers.md) · [IDE-/Agent-Integrationen](../integrations.md)
· Installationsanleitungen für [Windows](../install/windows.md),
[macOS](../install/macos.md) und [Linux](../install/linux.md).
