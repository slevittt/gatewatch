import pytest

from gatewatch.net import Exit, Result, as_ip, judge

PH = ["пока не поддерживается в вашей стране", "not available in your country", "location=unsupported"]


def res(code=200, size=800_000, url="https://x/", body=""):
    return Result(code, size, url, body, 0.1)


def test_http_200_and_big_page_is_ok():
    assert judge(res(), 300_000, PH)[0] == "ok"


def test_stub_is_detected_even_with_http_200_and_a_big_page():
    r = res(body="<html>Сервис пока не поддерживается в вашей стране.</html>")
    assert judge(r, 300_000, PH)[0] == "stub"


def test_english_stub_and_redirect_marker():
    assert judge(res(body="This is not available in your country"), 1, PH)[0] == "stub"
    assert judge(res(url="https://app.example.com/?location=unsupported"), 1, PH)[0] == "stub"


def test_small_or_failed_responses_are_dead():
    assert judge(res(size=5000), 300_000, PH)[0] == "dead"
    assert judge(res(code=0, size=0), 300_000, PH)[0] == "dead"
    assert judge(res(code=403), 1, PH)[0] == "dead"


def test_stub_check_is_case_insensitive():
    assert judge(res(body="NOT AVAILABLE IN YOUR COUNTRY"), 1, PH)[0] == "stub"


@pytest.mark.parametrize("text,ok", [
    ("http://1.2.3.4:8080", True), ("socks5://1.2.3.4:1080", True), ("socks5h://h.example:1", True),
    ("ftp://1.2.3.4:21", False), ("1.2.3.4:8080", False), ("http://1.2.3.4", False), ("", False)])
def test_exit_parse(text, ok):
    assert (Exit.parse(text) is not None) is ok


def test_exit_credentials_roundtrip_and_masking():
    e = Exit.parse("socks5://user:p%40ss@1.2.3.4:1080")
    assert (e.user, e.password) == ("user", "p@ss")
    assert e.curl_proxy == "socks5h://user:p%40ss@1.2.3.4:1080"
    assert "p%40ss" not in e.display and "p@ss" not in e.display


def test_as_ip():
    assert as_ip("198.51.100.4\n") == "198.51.100.4"
    assert as_ip("<html>nope</html>") == ""
    assert as_ip("") == ""
