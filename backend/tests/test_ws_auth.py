"""WebSocket auth token extraction — token in the handshake header, not the URL."""
from app.api.routes.ws import _extract_ws_token


def test_token_from_subprotocol_header():
    tok, sub = _extract_ws_token("kaeos-bearer, my.jwt.token", None)
    assert tok == "my.jwt.token"
    assert sub == "kaeos-bearer"


def test_falls_back_to_query_token_when_no_subprotocol():
    tok, sub = _extract_ws_token("", "query-token")
    assert tok == "query-token"
    assert sub is None


def test_ignores_unrelated_subprotocol():
    tok, sub = _extract_ws_token("graphql-ws", "query-token")
    assert tok == "query-token"
    assert sub is None


def test_no_token_anywhere():
    assert _extract_ws_token("", None) == (None, None)
