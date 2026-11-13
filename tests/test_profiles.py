from dataclasses import replace
import pytest

from aim_assist.profiles import load_profiles, save_profile
from aim_assist.settings import Settings, load_settings


def test_named_profiles_preserve_parameters_without_binding_device(tmp_path):
    path = tmp_path / "profiles.json"
    first = replace(Settings(), port="COM3", confidence=.7, rate=120, result_max_age_ms=80, sound_enabled=True, cpu_threads=8)
    save_profile(" 测试窗口 ", first, path)
    save_profile("另一窗口", replace(Settings(), crop_size=640), path)
    profiles = load_profiles(path)
    assert profiles["测试窗口"] == replace(first, port="")
    assert profiles["另一窗口"].crop_size == 640
    save_profile("测试窗口", replace(first, confidence=.8), path)
    assert len(load_profiles(path)) == 2
    assert load_profiles(path)["测试窗口"].confidence == .8
    assert not path.with_suffix(".tmp").exists()


@pytest.mark.parametrize("contents", ["broken json", '{"version":99,"profiles":{}}', '{"version":1,"profiles":{"bad":{"rate":0}}}'])
def test_unreadable_profiles_are_not_overwritten(tmp_path, contents):
    path = tmp_path / "profiles.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError):
        save_profile("new", Settings(), path)
    assert path.read_text(encoding="utf-8") == contents


@pytest.mark.parametrize("name", ["", "  ", "a" * 41, "name\nline"])
def test_invalid_profile_name_does_not_create_file(tmp_path, name):
    path = tmp_path / "profiles.json"
    with pytest.raises(ValueError):
        save_profile(name, Settings(), path)
    assert not path.exists()


def test_existing_settings_gain_safe_new_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"confidence":0.65}', encoding="utf-8")
    settings = load_settings(path)
    assert settings.confidence == .65
    assert settings.result_max_age_ms == 100
    assert settings.cpu_threads == 0
    assert not settings.sound_enabled
    for values in ({"result_max_age_ms": 0}, {"result_max_age_ms": True},
                   {"result_max_age_ms": 100.5}, {"result_max_age_ms": 501}, {"sound_enabled": "false"},
                   {"cpu_threads": True}, {"cpu_threads": -1}, {"cpu_threads": 257}):
        with pytest.raises(ValueError):
            replace(settings, **values).validate()
