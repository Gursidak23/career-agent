from app.resume.roles import ROLES, get_role, role_keys


def test_required_roles_present():
    for key in ["ai_engineer", "software_developer", "web_developer", "data_engineer", "app_developer"]:
        assert key in ROLES


def test_get_role_by_label_and_fuzzy():
    assert get_role("AI Engineer").key == "ai_engineer"
    assert get_role("ai-engineer").key == "ai_engineer"
    assert get_role("Software Developer").key == "software_developer"


def test_get_role_unknown_falls_back():
    assert get_role("nonexistent role").key == "software_developer"


def test_role_keys_nonempty():
    assert len(role_keys()) >= 5
