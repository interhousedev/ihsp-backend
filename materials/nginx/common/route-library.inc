# lib.<domain>: the static library app from the web container (it routes by Host, so the Host
# header goes through unchanged), except the public server-rendered pages. The api process serves
# those like the room pages, from the same host:
#   /b/<slug>      a book or a material (HTML with Open Graph and JSON-LD)
#   /sitemap.xml   /robots.txt   /opds/   (catalogue feeds for crawlers and reader apps)
# Student projects (/p/) are not part of this release and stay with the static app.
location ^~ /b/ {
    include /etc/nginx/ihsp/proxy.inc;
    include /etc/nginx/ihsp/headers-html.inc;
    proxy_pass $up_api;
}

location = /sitemap.xml {
    include /etc/nginx/ihsp/proxy.inc;
    include /etc/nginx/ihsp/headers-html.inc;
    proxy_pass $up_api;
}

location = /robots.txt {
    include /etc/nginx/ihsp/proxy.inc;
    include /etc/nginx/ihsp/headers-html.inc;
    proxy_pass $up_api;
}

location ^~ /opds/ {
    include /etc/nginx/ihsp/proxy.inc;
    include /etc/nginx/ihsp/headers-html.inc;
    proxy_pass $up_api;
}

location / {
    include /etc/nginx/ihsp/proxy.inc;
    proxy_pass $up_web;
}
