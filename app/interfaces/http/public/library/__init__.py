"""Public server-rendered pages of the library host (`/b/{slug}`, `/sitemap.xml`).

`library_robots_txt` and `is_library_host` (module `robots`) are for the shared
`/robots.txt` route, which answers for every host.
"""

from app.interfaces.http.public.library.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
