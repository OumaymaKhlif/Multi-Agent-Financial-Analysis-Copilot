import importlib
import pkgutil
import pytest
import app

# Ignorés : retriever charge le modèle Qwen dès l'import, server démarre le serveur MCP
SKIP = {"app.rag.retriever", "app.mcp.server"}


# Liste tous les modules du backend (hors tests et hors SKIP)
def all_modules():
    return [m.name for m in pkgutil.walk_packages(app.__path__, "app.")
            if m.name not in SKIP and not m.name.startswith("app.tests")]


# Chaque module doit s'importer sans erreur (détecte les imports cassés)
@pytest.mark.parametrize("name", all_modules())
def test_module_imports(name):
    importlib.import_module(name)