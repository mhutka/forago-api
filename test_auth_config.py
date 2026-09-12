def test_jwks_url_uses_loaded_settings(monkeypatch):
    import auth

    monkeypatch.setattr(
        auth.settings,
        "jwt_jwks_url",
        "https://project.supabase.co/auth/v1/.well-known/jwks.json",
    )
    monkeypatch.delenv("JWT_JWKS_URL", raising=False)

    assert (
        auth._jwt_jwks_url()
        == "https://project.supabase.co/auth/v1/.well-known/jwks.json"
    )
