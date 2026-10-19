"""Security (WP-11; FEATURES P2, P5): auth, roles, permission tiers, approvals, audit chain,
injection guard and web hardening.

Other work packages use the FastAPI dependencies in `app.security.deps`:

    from app.security.deps import current_principal
    def route(principal: Principal = Depends(current_principal)): ...

Every decision that depends on time reads the clock from `app.security.clock`, so tests can
move time instead of sleeping.
"""
