import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_NAME = "migrate-python-2-to-3"
SKILL = ROOT / "skills" / SKILL_NAME / "SKILL.md"


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path} missing YAML frontmatter"
    block = text.split("---", 2)[1]
    fm = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


def test_skill_exists_with_valid_frontmatter():
    assert SKILL.is_file()
    fm = _frontmatter(SKILL)
    assert fm.get("name") == SKILL_NAME  # dir name matches frontmatter name
    # Skill-name rules: lowercase/digits/hyphens, no "claude"/"anthropic".
    assert all(c.islower() or c.isdigit() or c == "-" for c in fm["name"])
    assert "claude" not in fm["name"] and "anthropic" not in fm["name"]
    assert fm.get("description")
    assert len(fm["description"]) <= 1024


def test_plugin_manifest_valid():
    manifest = ROOT / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data.get("name")
    servers = data["mcpServers"]
    entry = next(iter(servers.values()))
    assert entry["command"] == "claudebackend"
    assert entry["args"] == ["mcp"]


def test_project_mcp_json_valid():
    data = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    entry = next(iter(data["mcpServers"].values()))
    assert entry["command"] == "claudebackend"
    assert entry["args"] == ["mcp"]


def test_docs_and_command_present():
    for rel in ("docs/providers.md", "docs/integrations.md", "commands/develop.md"):
        p = ROOT / rel
        assert p.is_file() and p.read_text(encoding="utf-8").strip()
