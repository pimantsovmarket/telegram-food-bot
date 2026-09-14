from collections.abc import Collection


def is_owner(user_id: int | None, owner_ids: Collection[int]) -> bool:
    return user_id is not None and user_id in owner_ids
