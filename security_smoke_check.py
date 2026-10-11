#!/usr/bin/env python3
"""Passive security smoke checks for the Maktab Boshqaruvi site.

Checks a small, fixed set of pages without logging in, following redirects,
submitting forms, or changing data. Run only against a site you own/manage.
"""

import argparse
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPRedirectHandler, Request, build_opener


PRIVATE_PATHS = (
    "/dashboard",
    "/teacher_dashboard",
    "/student_dashboard",
    "/attendance",
    "/grades",
    "/students",
    "/teachers",
    "/tests",
    "/presentations",
    "/games",
    "/leaderboard",
    "/clubs/manage",
)

REQUIRED_HEADERS = {
    "Content-Security-Policy": None,
    "Strict-Transport-Security": None,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


class DoNotFollowRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(opener, url):
    req = Request(url, headers={"User-Agent": "MaktabSecuritySmokeCheck/1.0"})
    try:
        # First-hit requests on shared hosting may cold-start the WSGI worker.
        response = opener.open(req, timeout=15)
        return response.status, response.headers
    except HTTPError as exc:
        # Redirects are returned as statuses so we can verify the gate without
        # following it into a public page.
        return exc.code, exc.headers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default="https://maktab-boshqaruv.alwaysdata.net",
        help="Your site's origin (default: the domain from your Observatory report)",
    )
    args = parser.parse_args()

    origin = args.target.rstrip("/")
    parsed = urlsplit(origin)
    if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.path:
        parser.error("--target must be an origin such as https://example.uz")

    opener = build_opener(DoNotFollowRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    failures = 0

    print(f"Target: {origin}")
    print("Anonymous access checks (expected: redirect, 401, or 403):")
    for path in PRIVATE_PATHS:
        try:
            status, _ = request(opener, origin + path)
        except (URLError, TimeoutError, OSError) as exc:
            print(f"  ERROR {path}: {exc}")
            failures += 1
            continue

        if status in (301, 302, 303, 307, 308, 401, 403):
            print(f"  PASS   {path}: HTTP {status}")
        elif status == 200:
            print(f"  CHECK  {path}: HTTP 200 (page may be public or route may not exist)")
            failures += 1
        elif status == 404:
            print(f"  SKIP   {path}: route not found")
        else:
            print(f"  CHECK  {path}: HTTP {status}")
            failures += 1

    print("\nSecurity response headers on the home page:")
    try:
        status, headers = request(opener, origin + "/")
        print(f"  Home page: HTTP {status}")
        for name, expected in REQUIRED_HEADERS.items():
            value = headers.get(name)
            valid = bool(value) and (expected is None or expected.lower() in value.lower())
            label = "PASS" if valid else "CHECK"
            print(f"  {label:5} {name}: {value or 'missing'}")
            if not valid:
                failures += 1
        cookie = headers.get("Set-Cookie", "")
        if cookie:
            cookie_lower = cookie.lower()
            flags = {
                "Secure": "; secure" in cookie_lower,
                "HttpOnly": "; httponly" in cookie_lower,
                "SameSite": "; samesite=" in cookie_lower,
            }
            cookie_ok = all(flags.values())
            shown_flags = ", ".join(f"{name}={'yes' if present else 'no'}" for name, present in flags.items())
            # Never print the cookie value: it can contain a live session token.
            print(f"  {'PASS' if cookie_ok else 'CHECK':5} Session cookie flags: {shown_flags}")
            if not cookie_ok:
                failures += 1
        else:
            print("  INFO  No session cookie was set on the public home page.")
    except (URLError, TimeoutError, OSError) as exc:
        print(f"  ERROR home page: {exc}")
        failures += 1

    print("\nNote: HTTP 200 needs manual review; a route may be public or nonexistent.")
    print("Cookie flags should also be checked after a normal login in browser DevTools.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
