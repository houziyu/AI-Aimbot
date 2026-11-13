"""Named parameter sets, stored atomically beside the user's settings."""
from dataclasses import asdict, replace
import json

from .settings import CONFIG_PATH, Settings

PROFILE_PATH = CONFIG_PATH.with_name("profiles.json")


def load_profiles(path=PROFILE_PATH):
    if not path.exists():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("version") != 1 or not isinstance(document.get("profiles"), dict):
        raise ValueError("参数方案文件格式不支持，原文件已保留")
    profiles = {}
    for name, values in document["profiles"].items():
        validate_name(name)
        profiles[name] = Settings(**values).validate()
    return profiles


def validate_name(name):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 40 or any(ord(c) < 32 for c in name):
        raise ValueError("方案名称需为 1–40 个字符，不能包含换行或控制字符")
    return name.strip()


def save_profile(name, settings, path=PROFILE_PATH):
    name = validate_name(name)
    settings.validate()
    # Never overwrite an unreadable file with an empty set.
    profiles = load_profiles(path)
    profiles[name] = replace(settings, port="")
    document = {"version": 1, "profiles": {key: asdict(value) for key, value in profiles.items()}}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return profiles
