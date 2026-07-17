import json
from pathlib import Path


def test_plugin_json_valid():
    data = json.loads(Path(".claude-plugin/plugin.json").read_text())
    assert data["name"] == "dayoptimizer"
    assert "version" in data


def test_marketplace_json_valid():
    data = json.loads(Path(".claude-plugin/marketplace.json").read_text())
    assert data["name"] == "dayoptimizer"
    assert any(p["name"] == "dayoptimizer" for p in data["plugins"])


def test_mcp_json_points_at_server():
    data = json.loads(Path(".mcp.json").read_text())
    server = data["mcpServers"]["dayoptimizer"]
    assert "dayoptimizer.mcp_server" in " ".join(server["args"])


def test_commands_exist_and_reference_tools():
    for name in ("init", "plan", "today", "stats"):
        text = Path(f"commands/{name}.md").read_text()
        assert text.strip(), name
    assert "save_config" in Path("commands/init.md").read_text()
