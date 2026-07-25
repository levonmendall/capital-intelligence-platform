"""Stable response serialization for identity accounts and sessions."""

from security import TokenPair, UserAccount


def token_pair_to_dict(tokens: TokenPair) -> dict[str, object]:
    return {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": tokens.token_type,
        "access_expires_at": tokens.access_expires_at.isoformat(),
        "refresh_expires_at": tokens.refresh_expires_at.isoformat(),
    }


def user_account_to_dict(account: UserAccount) -> dict[str, object]:
    return {
        "user_id": account.user_id,
        "email": account.email,
        "display_name": account.display_name,
        "investor_identifier": account.investor_identifier,
        "is_active": account.is_active,
        "roles": [role.value for role in account.roles],
        "mandates": [
            {
                "mandate_code": grant.mandate_code,
                "permission": grant.permission.value,
            }
            for grant in account.mandate_grants
        ],
        "investor_access": [
            {
                "investor_identifier": grant.investor_identifier,
                "permission": grant.permission.value,
            }
            for grant in account.investor_grants
        ],
        "created_at": account.created_at.isoformat(),
    }


__all__ = ["token_pair_to_dict", "user_account_to_dict"]
