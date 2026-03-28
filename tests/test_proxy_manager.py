from src.services.proxy_manager import ProxyManager


def test_parse_proxy_line_keeps_standard_socks5_auth():
    proxy_manager = ProxyManager(None)

    result = proxy_manager._parse_proxy_line(
        "socks5://DBxDnzCVerAF:jUwkAwgzsu@204.1.112.137:443"
    )

    assert result == "socks5://DBxDnzCVerAF:jUwkAwgzsu@204.1.112.137:443"


def test_parse_proxy_line_keeps_standard_socks5h_auth():
    proxy_manager = ProxyManager(None)

    result = proxy_manager._parse_proxy_line(
        "socks5h://DBxDnzCVerAF:jUwkAwgzsu@204.1.112.137:443"
    )

    assert result == "socks5h://DBxDnzCVerAF:jUwkAwgzsu@204.1.112.137:443"


def test_parse_proxy_line_normalizes_reversed_http_auth_order():
    proxy_manager = ProxyManager(None)

    result = proxy_manager._parse_proxy_line(
        "http://204.1.112.137:443@DBxDnzCVerAF:jUwkAwgzsu"
    )

    assert result == "http://DBxDnzCVerAF:jUwkAwgzsu@204.1.112.137:443"


def test_normalize_proxy_url_keeps_socks5h_protocol():
    proxy_manager = ProxyManager(None)

    result = proxy_manager.normalize_proxy_url(
        "socks5h://DBxDnzCVerAF:jUwkAwgzsu@204.1.112.137:443"
    )

    assert result == "socks5h://DBxDnzCVerAF:jUwkAwgzsu@204.1.112.137:443"


def test_parse_proxy_line_normalizes_reversed_plain_auth_order_to_http():
    proxy_manager = ProxyManager(None)

    result = proxy_manager._parse_proxy_line(
        "204.1.112.137:443@DBxDnzCVerAF:jUwkAwgzsu"
    )

    assert result == "http://DBxDnzCVerAF:jUwkAwgzsu@204.1.112.137:443"
