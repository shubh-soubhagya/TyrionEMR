"""D6: prove the path and query reach the upstream byte for byte before relying on httpx.URL(path=, query=)."""
import pytest

UUID_A = "0b7c1e2a-4d5f-4a6b-8c7d-0e1f2a3b5a69"
UUID_B = "9f8e7d6c-5b4a-4938-8271-605f4e3d2c1b"


@pytest.mark.parametrize(
    ("client_target", "upstream_target"),
    [
        (f"/api/labs/patients/{UUID_A}/results", f"/labs/patients/{UUID_A}/results"),
        ("/api/patients/a%7Eb", "/patients/a%7Eb"),                                  # benign escape kept as sent
        ("/api/patients/a~b", "/patients/a~b"),
        ("/api/patients/", "/patients/"),                                              # trailing slash kept
        ("/api/patients?q=Ramesh+Kulkarni", "/patients?q=Ramesh+Kulkarni"),
        (f"/api/patients?ids={UUID_A},{UUID_B}", f"/patients?ids={UUID_A},{UUID_B}"),
        ("/api/labs/x?from=2026-01-01T00:00:00%2B05:30", "/labs/x?from=2026-01-01T00:00:00%2B05:30"),
        ("/api/patients?q=a%20b&sort=-name&x=%E0%A4%85", "/patients?q=a%20b&sort=-name&x=%E0%A4%85"),
        ("/api/patients?flag", "/patients?flag"),
        ("/api/patients?a=1&a=2&b=", "/patients?a=1&a=2&b="),
    ],
)
async def test_target_reaches_the_upstream_byte_for_byte(gw, client_target, upstream_target):
    client, ups = gw
    await client.get(client_target)
    up = ups["lab" if "/labs/" in client_target else "patient"].last
    assert up.url.raw_path.decode("ascii") == upstream_target


async def test_the_documented_search_and_follow_up_query(gw):
    client, ups = gw
    q = f"q=Ramesh+Kulkarni&ids={UUID_A},{UUID_B}&from=2026-01-01T00:00:00%2B05:30"
    await client.get(f"/api/patients?{q}")
    assert ups["patient"].last.url.query.decode() == q


async def test_five_hundred_uuids_in_the_ids_filter(gw):
    """The Needs-attention filter: about 18.5 KB of query string, forwarded whole."""
    client, ups = gw
    ids = ",".join(f"{i:08x}-0000-4000-8000-{i:012x}" for i in range(500))
    r = await client.get(f"/api/patients?ids={ids}")
    assert r.status_code == 200
    assert ups["patient"].last.url.query.decode() == f"ids={ids}"
