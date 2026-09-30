from app.core.issue_target import DEMO_BLOCKED_MESSAGE, resolve_issue_target

DEFAULTS = dict(default_owner="acme", default_repo="motif-demo")


def target(**kw):
    base = dict(shared_demo=False, signed_in=True, project_repo=None, requested_repo=None, **DEFAULTS)
    base.update(kw)
    return resolve_issue_target(**base)


def test_shared_demo_never_opens_real_issue_when_signed_in():
    t = target(shared_demo=True)
    assert not t.allowed
    assert t.message == DEMO_BLOCKED_MESSAGE


def test_shared_demo_can_be_enabled_by_operator_but_ignores_requested_repo():
    t = target(shared_demo=True, requested_repo="victim/private", demo_may_create_issues=True)
    assert t.allowed and (t.owner, t.repo) == ("acme", "motif-demo")


def test_project_uses_its_saved_repo_not_the_requested_one():
    t = target(project_repo="me/product", requested_repo="victim/private")
    assert t.allowed and (t.owner, t.repo) == ("me", "product")


def test_project_without_repo_falls_back_to_default_not_requested():
    t = target(requested_repo="victim/private")
    assert (t.owner, t.repo) == ("acme", "motif-demo")


def test_auth_off_keeps_local_behaviour():
    t = target(signed_in=False, shared_demo=True, requested_repo="me/local")
    assert t.allowed and (t.owner, t.repo) == ("me", "local")
