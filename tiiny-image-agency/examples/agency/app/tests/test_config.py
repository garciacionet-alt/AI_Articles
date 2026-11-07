from tis.config import Settings, load_settings
import os
import tempfile

def test_inference_base_appends_v1():
    assert (
        Settings(base_url="http://openai.api.tiiny").inference_base
        == "http://openai.api.tiiny/v1"
    )


def test_inference_base_does_not_double_v1():
    assert (
        Settings(base_url="http://openai.api.tiiny/v1").inference_base
        == "http://openai.api.tiiny/v1"
    )


def test_load_settings_reads_key(monkeypatch):
    monkeypatch.setenv("TIINY_API_KEY", "secret")
    assert load_settings().api_key == "secret"


def test_load_settings_without_key_is_empty(monkeypatch):
    monkeypatch.delenv("TIINY_API_KEY", raising=False)
    assert load_settings().api_key == ""


def test_default_registry_path_exists():
    """Test that the default registry path actually points to the real file."""
    settings = Settings()
    assert settings.registry_path.exists()
    assert settings.registry_path.name == "image-models.json"


def test_registry_path_override(monkeypatch):
    """Test that TIIS_REGISTRY_PATH environment variable overrides the default."""
    with tempfile.NamedTemporaryFile() as tmp:
        monkeypatch.setenv("TIIS_REGISTRY_PATH", tmp.name)
        settings = Settings()
        assert str(settings.registry_path) == os.path.expanduser(tmp.name)


def test_registry_path_override_with_tilde(monkeypatch):
    """Test that TIIS_REGISTRY_PATH with ~ gets expanded properly."""
    monkeypatch.setenv("TIIS_REGISTRY_PATH", "~/somewhere/registry.json")
    settings = Settings()
    assert "~" not in str(settings.registry_path)
    assert settings.registry_path.is_absolute()