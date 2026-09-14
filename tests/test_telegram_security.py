from sut_control_center.telegram.security import is_owner


def test_owner_is_allowed():
    assert is_owner(42, {42, 99})


def test_non_owner_is_rejected():
    assert not is_owner(7, {42, 99})
    assert not is_owner(None, {42, 99})
